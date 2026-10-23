"""后台 worker：消费任务队列，执行"分段转写 + 说话人分离"流水线。

流水线：
  解码 -> 分片计划 -> 逐片 ASR+CAM++ -> 落库 -> 跨片说话人合并 -> 汇总结果 -> 回调
失败段可单独重跑（见 retry_job）。
"""
import json
import os
import threading
import time
import traceback
from concurrent.futures.process import BrokenProcessPool

import numpy as np
import requests

import config
import store
import search
import ratelimit


def _engine():
    """懒加载 engine（D2）：engine 依赖 torch/funasr 重型库，
    测试与 CI 只需 API/存储层，导入 app→worker 时不应被迫拉起推理栈。"""
    import engine
    return engine

_threads = []
_stop = threading.Event()


def _log(jid, kind, detail=""):
    store.add_event(jid, kind, detail)
    print("[job %s] %s %s" % (jid, kind, detail), flush=True)


def _hotwords(user_hw):
    """合并热词：默认关闭；仅当 ASR_HOTWORDS_ENABLED=1 且配置了词表时才并入默认词表。"""
    parts = [p for p in (user_hw or "").split() if p]
    if config.HOTWORDS_ENABLED:
        for w in config.DEFAULT_HOTWORDS.split():
            if w and w not in parts:
                parts.append(w)
    return " ".join(parts)


def _result_path(jid):
    return os.path.join(config.RESULT_DIR, jid + ".json")


# ---------------- Webhook SSRF 防护（阶段 A2，实现在 netguard.py） ----------------
from netguard import webhook_url_allowed as _webhook_url_allowed  # noqa: E402


def _notify(callback_url, payload, jid):
    if not callback_url:
        return
    ok, reason = _webhook_url_allowed(callback_url)
    if not ok:
        # SSRF 防护（A2）：拒绝时记录事件，任务本身不受影响
        _log(jid, "webhook_blocked", "%s: %s" % (reason, callback_url[:200]))
        return
    try:
        # S1：requests 默认 allow_redirects=True，"公网 URL → 302 内网" 可绕过校验。
        # 故禁用自动重定向，改为手动跟随一次并对 Location 重新过 SSRF 校验。
        r = requests.post(callback_url, json=payload, timeout=10, allow_redirects=False)
        if 300 <= r.status_code < 400 and r.headers.get("Location"):
            loc = r.headers["Location"]
            ok2, reason2 = _webhook_url_allowed(loc)
            if not ok2:
                _log(jid, "webhook_blocked", "redirect %s: %s" % (reason2, loc[:200]))
                return
            _log(jid, "webhook_redirect", loc[:200])
            requests.post(loc, json=payload, timeout=10, allow_redirects=False)
            _log(jid, "webhook_ok", loc)
        else:
            _log(jid, "webhook_ok", callback_url)
    except Exception as e:  # noqa
        _log(jid, "webhook_fail", "%s: %s" % (callback_url, e))


def process_job(job):
    jid = job["id"]
    rid = job["recording_id"]
    rec = store.get_recording(rid)
    tenant = (rec.get("tenant_id") or "") if rec else ""
    duration_ms = 0
    if not rec:
        store.update_job(jid, status="failed", error="recording not found", stage="失败")
        return

    hotword = _hotwords(job.get("hotword"))
    preset = job.get("preset_spk_num")
    backend = (job.get("asr_model") or config.DEFAULT_ASR_BACKEND)
    denoise = bool(job.get("denoise"))
    _log(jid, "job_start", "backend=%s denoise=%s" % (backend, denoise))
    store.mark_job_started(jid)  # P2-2：记录任务开始时间（可观测性）

    try:
        # 1) 解码
        store.update_job(jid, stage="解码音频", status="processing")
        src = rec["path"]
        wav = os.path.join(config.AUDIO_DIR, rid + ".norm.wav")
        _engine().decode_to_wav(src, wav, denoise=denoise)
        duration_ms = _engine().probe_duration_ms(wav)
        store.set_recording_status(rid, "processing", duration_ms=duration_ms)

        # 2) 分片计划（已存在则复用，便于重跑失败段）
        if not store.get_chunks(jid):
            silences = _engine().detect_silences_ms(wav)
            ranges = _engine().plan_chunks(duration_ms, silences, config.CHUNK_SECONDS * 1000)
            store.create_chunks(jid, ranges)
        store.update_job(jid, stage="转写中")

        # 3) 逐片处理（失败自动重试 / 子分片兜底，直至无 pending 分片）
        tmp_chunk = os.path.join(config.AUDIO_DIR, rid + "_chunk_tmp.wav")
        _process_chunks(jid, wav, tmp_chunk, hotword, preset, backend)
        try:
            os.remove(tmp_chunk)
        except OSError:
            pass

        # 4) 跨分片说话人合并
        store.update_job(jid, stage="说话人合并")
        cents = store.get_all_centroids(jid)
        n_spk = None
        vp_labels = {}  # P3-3：声纹库自动匹配的说话人名称 {global_spk: name}
        if cents:
            keys = [(c[0], c[1]) for c in cents]
            mat = np.stack([c[2] for c in cents], axis=0)
            labels = _engine().cluster_speakers(mat, config.SPK_DISTANCE_THRESHOLD, preset)
            mapping = {keys[i]: int(labels[i]) for i in range(len(keys))}
            store.set_segments_global_spk(jid, mapping)
            n_spk = len(set(mapping.values()))

            # P3-3 声纹匹配：各全局说话人质心与本租户声纹库比对，达阈值即采用库名
            if config.VOICEPRINT_ENABLED:
                try:
                    lib = store.list_voiceprints(tenant, with_vectors=True)
                    if lib:
                        cents_g = store.speaker_centroids_by_global(jid)
                        for g, v in cents_g.items():
                            hit, sim = store.match_voiceprint(v, lib)
                            if hit and sim >= config.VOICEPRINT_THRESHOLD:
                                vp_labels[int(g)] = hit["name"]
                                _log(jid, "voiceprint_match",
                                     "spk=%s -> %s sim=%.3f" % (g, hit["name"], sim))
                except Exception as e:  # noqa: BLE001 声纹匹配失败不阻塞转写
                    print("[worker] 声纹匹配失败: %r" % e, flush=True)

        # 5) 汇总结果
        prog = store.refresh_job_progress(jid)
        result = _build_result(jid, rid, rec, duration_ms, n_spk, prog, label_overrides=vp_labels)
        with open(_result_path(jid), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        if prog["failed"] == 0:
            status = "done"
        elif prog["done"] > 0:
            status = "partial"
        else:
            status = "failed"
        store.update_job(jid, status=status, stage="完成" if status == "done" else "部分完成",
                         progress=100.0 if status != "failed" else prog["progress"],
                         result_path=_result_path(jid))
        store.mark_job_finished(jid)  # P2-2：记录任务结束时间
        store.set_recording_status(rid, status, duration_ms=duration_ms, num_speakers=n_spk)
        # FR-24：转写（重跑）完成后，基于旧转写生成的摘要标记失效，提示重新生成
        store.mark_summaries_stale(rid)
        _log(jid, "job_%s" % status, "speakers=%s chunks=%s" % (n_spk, prog))

        # 增量建立检索索引（FR-30）：异步进行，不阻塞任务完成
        if status in ("done", "partial"):
            threading.Thread(target=search.index_recording, args=(rid,), daemon=True).start()

        _notify(job.get("callback_url"), {
            "job_id": jid, "recording_id": rid, "status": status,
            "progress": prog, "num_speakers": n_spk,
            "result_url": "/api/v1/recordings/%s" % rid,
        }, jid)

    except Exception as e:  # noqa
        traceback.print_exc()
        store.update_job(jid, status="failed", stage="失败", error=str(e)[:800])
        store.set_recording_status(rid, "failed", error=str(e)[:800])
        store.mark_job_finished(jid)  # P2-2
        _log(jid, "job_error", str(e))
    finally:
        # FR-08 累计当日已处理时长（用于配额）
        ratelimit.add_usage(tenant, duration_ms / 1000.0)


def _save_chunk(jid, idx, res):
    store.clear_chunk_segments(jid, idx)
    store.add_chunk_segments(jid, idx, res["sentences"])
    if res["centroids"] is not None:
        for k, vec in enumerate(res["centroids"]):
            store.add_chunk_speaker(jid, idx, k, vec.tobytes())


def _process_chunks(jid, wav, tmp_chunk, hotword, preset, backend):
    """逐片处理；失败按策略自动重试 / 子分片兜底，直至所有分片 done 或 failed。

    常驻进程池模式下改用并发提交（见 _process_chunks_pool），以利用多进程并行推理。
    """
    if config.INFER_POOL:
        return _process_chunks_pool(jid, wav, hotword, preset, backend)
    _process_chunks_serial(jid, wav, tmp_chunk, hotword, preset, backend)


def _process_chunks_pool(jid, wav, hotword, preset, backend):
    """常驻进程池模式：一次性并发提交所有 pending 分片到池（并发度=INFER_PROCESSES），
    待各自完成后落库；失败按策略重试 / 切分（与串行逻辑一致）。
    """
    while True:
        # 排除永久 failed 的分片（同串行版）：仅可由用户手动重试复活，避免无限重跑
        pending = [c for c in store.pending_chunks(jid) if c.get("status") != "failed"]
        if not pending:
            break
        futures = {}
        for ch in pending:
            idx, s, e = ch["idx"], ch["start_ms"], ch["end_ms"]
            attempts_before = ch["attempts"]
            store.set_chunk_status(jid, idx, "processing", inc_attempt=True)
            fut = _engine().submit_chunk(wav, s, e, config.AUDIO_DIR, hotword, preset, backend)
            futures[idx] = (fut, attempts_before, s, e)
        requeue = False
        for idx, (fut, attempts_before, s, e) in futures.items():
            t0 = time.perf_counter()  # P2-2：分片耗时（含排队）
            try:
                res = fut.result()
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                _save_chunk(jid, idx, res)
                store.set_chunk_status(jid, idx, "done")
                store.set_chunk_elapsed(jid, idx, elapsed_ms)
                _log(jid, "chunk_done", "idx=%d seg=%d dropped=%d backend=%s elapsed=%.1fs%s" % (
                    idx, len(res["sentences"]), res.get("dropped", 0), res.get("backend"),
                    elapsed_ms / 1000.0, " FALLBACK" if res.get("fallback") else ""))
            except BrokenProcessPool:
                # 池进程崩溃（OOM/CUDA）：销毁旧池，下轮 submit 自动重建（engine._get_infer_pool）
                _engine().shutdown_infer_pool()
                store.set_chunk_status(jid, idx, "pending", error="infer pool broken, rebuilt")
                _log(jid, "chunk_requeue", "idx=%d pool broken -> rebuilt" % idx)
                requeue = True
            except Exception as exc:  # noqa
                err = str(exc)[:500]
                if attempts_before < config.MAX_CHUNK_RETRY:
                    store.set_chunk_status(jid, idx, "pending", error=err)
                    delay = min(config.CHUNK_RETRY_BASE_DELAY * (2 ** attempts_before), 30)
                    _log(jid, "chunk_retry", "idx=%d attempt=%d delay=%.0fs %s" % (idx, attempts_before + 1, delay, exc))
                    if delay > 0:
                        time.sleep(delay)
                    requeue = True
                elif config.CHUNK_SPLIT_ON_FAIL and (e - s) >= config.CHUNK_MIN_SPLIT_MS:
                    new_idxs = store.split_failed_chunk(jid, idx, 2)
                    _log(jid, "chunk_split", "idx=%d (%d->%dms) -> %s" % (idx, s, e, new_idxs))
                    requeue = True
                else:
                    store.set_chunk_status(jid, idx, "failed", error=err)
                    _log(jid, "chunk_fail", "idx=%d %s" % (idx, exc))
            store.refresh_job_progress(jid)  # 每片完成即刷新，前端进度实时可见
        if not requeue:
            break


def _process_chunks_serial(jid, wav, tmp_chunk, hotword, preset, backend):
    """逐片处理（串行，旧逻辑）；失败自动重试 / 子分片兜底。

    闭环逻辑（每片）：
      1) 抛错且重试次数未达上限  -> 退回 pending，指数退避后下一轮重跑
      2) 达上限且分片够大        -> 对半切，子分片下一轮再处理（保留时间顺序）
      3) 达上限且分片过小        -> 标记永久 failed，放弃该段
    """
    while True:
        # 排除永久 failed 的分片：它们只能由用户「重试失败分片」手动复活，
        # 否则每轮 pending 都会捞回它们，重跑→失败→再标 failed 无限循环
        pending = [c for c in store.pending_chunks(jid) if c.get("status") != "failed"]
        if not pending:
            break
        for ch in pending:
            idx, s, e = ch["idx"], ch["start_ms"], ch["end_ms"]
            attempts_before = ch["attempts"]
            store.set_chunk_status(jid, idx, "processing", inc_attempt=True)
            t0 = time.perf_counter()  # P2-2：分片耗时
            try:
                res = _engine().process_chunk(wav, s, e, tmp_chunk, hotword, preset, backend)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                _save_chunk(jid, idx, res)
                store.set_chunk_status(jid, idx, "done")
                store.set_chunk_elapsed(jid, idx, elapsed_ms)
                _log(jid, "chunk_done", "idx=%d seg=%d dropped=%d backend=%s elapsed=%.1fs%s" % (
                    idx, len(res["sentences"]), res.get("dropped", 0), res.get("backend"),
                    elapsed_ms / 1000.0, " FALLBACK" if res.get("fallback") else ""))
            except Exception as exc:  # noqa
                err = str(exc)[:500]
                if attempts_before < config.MAX_CHUNK_RETRY:
                    # 自动重试：退回 pending，等待下一轮（指数退避避免雪崩）
                    store.set_chunk_status(jid, idx, "pending", error=err)
                    delay = min(config.CHUNK_RETRY_BASE_DELAY * (2 ** attempts_before), 30)
                    _log(jid, "chunk_retry", "idx=%d attempt=%d delay=%.0fs %s" % (idx, attempts_before + 1, delay, exc))
                    if delay > 0:
                        time.sleep(delay)
                elif config.CHUNK_SPLIT_ON_FAIL and (e - s) >= config.CHUNK_MIN_SPLIT_MS:
                    # 超重试上限且够大：对半切，子分片下一轮再处理
                    new_idxs = store.split_failed_chunk(jid, idx, 2)
                    _log(jid, "chunk_split", "idx=%d (%d->%dms) -> %s" % (idx, s, e, new_idxs))
                else:
                    # 放弃：标记永久失败
                    store.set_chunk_status(jid, idx, "failed", error=err)
                    _log(jid, "chunk_fail", "idx=%d %s" % (idx, exc))
            store.refresh_job_progress(jid)


def _build_result(jid, rid, rec, duration_ms, n_spk, prog, label_overrides=None):
    segs = store.get_segments(jid)
    out_segs = []
    for s in segs:
        g = s["global_spk"]
        words = None
        if s.get("words"):
            try:
                words = json.loads(s["words"])
            except Exception:
                words = None
        out_segs.append({
            "start_ms": s["start_ms"], "end_ms": s["end_ms"],
            "start": _engine().fmt_ms(s["start_ms"]), "end": _engine().fmt_ms(s["end_ms"]),
            "spk": g if g is not None else s["local_spk"],
            "text": s["text"],
            "need_review": s.get("need_review", 0),
            "review_reason": s.get("review_reason") or "",
            "confidence": s.get("confidence"),
            "words": words,
        })

    # 按说话人合并连续句 -> 轮次（同说话人且间隔不超过阈值才并）
    turns = []
    gap = config.TURN_MAX_GAP_MS
    for s in out_segs:
        if (turns and turns[-1]["spk"] == s["spk"]
                and (s["start_ms"] - turns[-1]["end_ms"]) <= gap):
            turns[-1]["end_ms"] = s["end_ms"]
            turns[-1]["end"] = s["end"]
            turns[-1]["text"] += s["text"]
        else:
            turns.append({"spk": s["spk"], "start_ms": s["start_ms"], "end_ms": s["end_ms"],
                          "start": s["start"], "end": s["end"], "text": s["text"]})

    speaker_ids = sorted({s["spk"] for s in out_segs})
    # P3-3：声纹库匹配到的说话人直接使用库名（可读名贯穿全文/纪要/检索）
    speakers = []
    for i, k in enumerate(speaker_ids):
        nm = (label_overrides or {}).get(k)
        sp = {"spk": k, "label": nm or "说话人 %d" % (i + 1)}
        if nm:
            sp["matched"] = True
        speakers.append(sp)
    label_map = {x["spk"]: x["label"] for x in speakers}

    lines = []
    for t in turns:
        lines.append("%s(%s)：%s" % (label_map.get(t["spk"], "说话人?"), t["start"], t["text"]))

    review = [s for s in out_segs if s.get("need_review")]
    return {
        "recording_id": rid, "job_id": jid, "filename": rec["filename"],
        "duration_ms": duration_ms, "duration": _engine().fmt_ms(duration_ms),
        "num_speakers": n_spk or len(speaker_ids), "speakers": speakers,
        "segments": out_segs, "turns": turns, "review": review,
        "text": "\n".join(lines),
        "stats": {
            "sentences": len(out_segs), "turns": len(turns),
            "chars": sum(len(s["text"]) for s in out_segs),
            "chunks": prog["total"], "failed_chunks": prog["failed"],
            "review_count": len(review),
        },
    }


def retry_job(jid):
    """把失败分片重置为 pending 并重新入队，返回重新入队的分片数。"""
    n = store.reset_failed_chunks(jid)
    store.update_job(jid, status="queued", stage="排队中", error=None)
    store.add_event(jid, "retry", "failed chunks re-queued: %d" % n)
    return n


def _loop(worker_id):
    while not _stop.is_set():
        try:
            # 批量查看排队任务，跳过已达并发上限的租户，避免队头阻塞整个队列
            candidates = store.peek_queued(limit=20)
            picked = None
            for job in candidates:
                rec = store.get_recording(job["recording_id"])
                tenant = (rec.get("tenant_id") or "") if rec else ""
                if ratelimit.can_process(tenant):
                    picked = (job, tenant)
                    break
            if picked:
                job, tenant = picked
                claimed = store.claim_job(job["id"])
                if claimed:
                    # 原子占用并发名额：can_process 与 begin 之间可能被其他 worker 抢占
                    if not ratelimit.try_begin(tenant):
                        store.requeue_job(claimed["id"])
                        _stop.wait(0.5)
                        continue
                    try:
                        process_job(claimed)
                    finally:
                        ratelimit.end_process(tenant)
                    continue
                # 已被其它 worker 领取，进入下一轮
                _stop.wait(0.2)
            else:
                _stop.wait(1.0)
        except Exception:  # noqa
            traceback.print_exc()
            _stop.wait(2.0)


def start_workers(n=None):
    n = n or config.MAX_WORKERS
    for i in range(n):
        t = threading.Thread(target=_loop, args=(i,), daemon=True, name="asr-worker-%d" % i)
        t.start()
        _threads.append(t)
    print(">> 已启动 %d 个 worker 线程" % n, flush=True)


def stop_workers():
    _stop.set()
