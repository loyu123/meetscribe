"""历史语义检索（对应需求 FR-25~FR-32）。

索引（FR-26 / FR-30）：
  - 切块：复用转写结果，按"说话人轮次"聚合（同说话人且间隔不超过 TURN_MAX_GAP_MS
    才并入同一轮），每块携带 录音ID / 说话人 / 时间戳 / 日期 等元数据；
    检索文本 search_text 在轮次文本基础上追加相邻轮次的少量上下文，近似"重叠上下文"。
  - 向量化：调用 AI Gateway 的 embed 批量接口（与转写结果异步解耦）。
  - 增量：录制完成时由 worker 触发 index_recording；删除录音时同步清理（delete_index）。

检索（FR-25 / FR-27 / FR-29）：
  - 混合召回：BM25（关键词，专名/编号友好） + 向量（语义）→ RRF 倒数排名融合。
  - 精排：融合 top-K 送 rerank 重排序。
  - 结构化过滤：日期范围 / 说话人 / 录音ID（FR-27）。
  - 结果呈现：命中片段文本 + 时间戳 + 可播放定位链接 + 关键词高亮 + 分页（FR-29）。

审计（FR-32）：每次检索记录 查询语句 / 命中数 / 命中录音ID（脱敏，不存原文）。
"""
import json
import re
import time

import numpy as np

import config
import gateway_client
import store

_SEARCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recording_id TEXT,
  job_id TEXT,
  start_ms INTEGER,
  end_ms INTEGER,
  speaker TEXT,
  date TEXT,
  text TEXT,
  search_text TEXT,
  embedding BLOB,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS search_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  query TEXT,
  hit_count INTEGER,
  recordings TEXT
);
CREATE INDEX IF NOT EXISTS idx_sc_rec ON search_chunks(recording_id);
CREATE INDEX IF NOT EXISTS idx_sc_date ON search_chunks(date);
CREATE TABLE IF NOT EXISTS search_meta (
  k TEXT PRIMARY KEY,
  v TEXT
);
"""

# U2：分词/切块口径版本。任何改变 _tokenize 或 search_text 组成方式的改动都必须 +1，
# 否则旧索引与查询侧 token 口径不一致（专名召回明显变差），前端会提示重建。
TOKENIZE_VERSION = 2

_K1 = 1.5
_B = 0.75
_RRF_K = 60
_FUSE_TOP = 50          # 融合后送 rerank 的候选数
_CONTEXT_TURNS = 1      # 检索文本向前后各借的相邻轮次数（重叠上下文）


def init_search_db():
    with store.conn() as c:
        c.executescript(_SEARCH_SCHEMA)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 索引元信息（U2：分词版本一致性） ----------------
def _meta_get(k):
    with store.conn() as c:
        row = c.execute("SELECT v FROM search_meta WHERE k=?", (k,)).fetchone()
    return row["v"] if row else None


def _meta_set(k, v):
    with store.conn() as c:
        c.execute("INSERT OR REPLACE INTO search_meta(k,v) VALUES(?,?)", (k, str(v)))


def index_meta():
    """当前程序的分词口径 vs 已建索引的口径。

    needs_reindex：仅当索引确实带版本且与当前版本不同时为真。
    历史库无版本记录时不做误报（下一次建索引会自动补写版本）。
    """
    raw = _meta_get("tokenize_version")
    try:
        idx_ver = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        idx_ver = None
    stale = idx_ver is not None and idx_ver != TOKENIZE_VERSION
    return {
        "tokenize_version": TOKENIZE_VERSION,
        "index_tokenize_version": idx_ver,
        "needs_reindex": bool(stale and _all_indexed_recording_ids()),
        "indexed_at": _meta_get("indexed_at"),
    }


# ---------------- 切块（FR-26） ----------------
def _build_turns(rid, jid, labels=None):
    """从 segments 表按说话人轮次聚合，返回与前端 turns 对齐的切块列表。

    与 worker._build_result 的轮次合并规则保持一致：同说话人且间隔 <= 阈值才并入。
    labels: {spk: 可读名}（来自结果 JSON 的重命名/声纹匹配标签），缺省回退「说话人 N」。
    返回 [{"start_ms","end_ms","spk","label","text"}]
    """
    segs = store.get_segments(jid)
    if not segs:
        return []
    out = []
    for s in segs:
        g = s["global_spk"]
        out.append({
            "start_ms": s["start_ms"], "end_ms": s["end_ms"],
            "spk": g if g is not None else s["local_spk"],
            "text": s["text"] or "",
        })
    turns = []
    gap = config.TURN_MAX_GAP_MS
    for s in out:
        if (turns and turns[-1]["spk"] == s["spk"]
                and (s["start_ms"] - turns[-1]["end_ms"]) <= gap):
            turns[-1]["end_ms"] = s["end_ms"]
            turns[-1]["text"] += s["text"]
        else:
            turns.append({"spk": s["spk"], "start_ms": s["start_ms"],
                          "end_ms": s["end_ms"], "text": s["text"]})
    label_map = {}
    for i, k in enumerate(sorted({t["spk"] for t in turns})):
        label_map[k] = "说话人 %d" % (i + 1)
    labels = {int(k): v for k, v in (labels or {}).items()}
    for t in turns:
        # P1-1/P3-3：优先使用结果 JSON 的可读名（重命名/声纹匹配），保证检索 snippet 一致
        t["label"] = labels.get(t["spk"]) or label_map.get(t["spk"], "说话人?")
    return turns


def _search_text_for(turns, i):
    """检索文本：当前轮 + 前后相邻轮次的少量上下文（重叠上下文，FR-26）。"""
    ctx = []
    for j in range(max(0, i - _CONTEXT_TURNS), min(len(turns), i + _CONTEXT_TURNS + 1)):
        if j == i:
            ctx.append(turns[i]["text"])
        else:
            t = turns[j]["text"]
            ctx.append(t[:60])  # 相邻上下文截断，避免污染主块语义
    return "\n".join(ctx)


# ---------------- 索引（FR-26 / FR-30，P0-2 异步化） ----------------
import threading  # noqa: E402

_INDEX_LOCK = threading.Lock()
_INDEX_INFLIGHT = set()  # 正在索引中的 rid，避免同录音并发重建


def index_recording(rid):
    """为某录音建/重建检索索引（幂等：先删旧块再写新块）。返回切块数。

    P0-2：全程记录 index_status（indexing/done/failed），失败可观测、可重试。
    """
    rec = store.get_recording(rid)
    if not rec:
        return 0
    job = store.get_job_by_recording(rid)
    if not job or not job.get("result_path"):
        return 0
    if rec.get("status") not in ("done", "partial"):
        return 0
    store.set_index_status(rid, "indexing")
    # P1-1/P3-3：读取结果 JSON 中的说话人标签（重命名/声纹匹配后的可读名）
    labels = {}
    try:
        with open(job["result_path"], "r", encoding="utf-8") as f:
            for s in (json.load(f).get("speakers") or []):
                labels[s.get("spk")] = s.get("label")
    except Exception:
        labels = {}
    turns = _build_turns(rid, job["id"], labels=labels)
    turns = [t for t in turns if t["text"].strip()]
    if not turns:
        delete_index(rid)
        store.set_index_status(rid, "none")
        return 0
    date = (rec.get("created_at") or "")[:10]
    try:
        vecs = gateway_client.embed([_search_text_for(turns, i) for i in range(len(turns))])
    except Exception as e:  # noqa: BLE001
        print("[search] embed 失败 rid=%s: %r" % (rid, e), flush=True)
        store.set_index_status(rid, "failed", error=str(e)[:500])
        return 0
    rows = []
    for i, t in enumerate(turns):
        v = vecs[i] if i < len(vecs) else None
        rows.append((
            rid, job["id"], t["start_ms"], t["end_ms"], t["label"], date,
            t["text"], _search_text_for(turns, i),
            np.asarray(v, dtype=np.float32).tobytes() if v is not None else None,
            _now(),
        ))
    with store.conn() as c:
        c.execute("DELETE FROM search_chunks WHERE recording_id=?", (rid,))
        c.executemany(
            "INSERT INTO search_chunks(recording_id,job_id,start_ms,end_ms,speaker,date,"
            "text,search_text,embedding,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    store.set_index_status(rid, "done")
    # U2：记录本次索引使用的分词版本，供搜索页判断是否需要重建
    _meta_set("tokenize_version", TOKENIZE_VERSION)
    _meta_set("indexed_at", _now())
    print("[search] 已索引 rid=%s 切块=%d" % (rid, len(rows)), flush=True)
    return len(rows)


def index_recording_async(rid):
    """后台线程建索引（P0-2）：接口/worker 调用后立即返回，不阻塞请求。同录音去重。"""
    with _INDEX_LOCK:
        if rid in _INDEX_INFLIGHT:
            return
        _INDEX_INFLIGHT.add(rid)

    def _run():
        try:
            index_recording(rid)
        except Exception as e:  # noqa: BLE001
            print("[search] 异步索引异常 rid=%s: %r" % (rid, e), flush=True)
            try:
                store.set_index_status(rid, "failed", error=str(e)[:500])
            except Exception:  # noqa: BLE001
                pass
        finally:
            with _INDEX_LOCK:
                _INDEX_INFLIGHT.discard(rid)

    threading.Thread(target=_run, daemon=True).start()


def delete_index(rid):
    with store.conn() as c:
        c.execute("DELETE FROM search_chunks WHERE recording_id=?", (rid,))


def index_all_done(progress=None):
    """为所有已完成录音建立索引（维护用，P0-2 改为后台任务调用）。返回 (成功数, 跳过数)。

    progress(done, failed, total)：可选进度回调，供 /search/reindex 状态查询。
    """
    recs = store.list_recordings(limit=1000)
    targets = [r["id"] for r in recs if r.get("status") in ("done", "partial")]
    total = len(targets)
    ok = failed = 0
    for i, rid in enumerate(targets):
        n = index_recording(rid)
        if n > 0:
            ok += 1
        else:
            rec = store.get_recording(rid)
            # embed 失败会标记 failed；无结果/空转写归为跳过
            if rec and rec.get("index_status") == "failed":
                failed += 1
        if progress:
            try:
                progress(ok + failed + (i + 1 - ok - failed), failed, total)
            except Exception:  # noqa: BLE001
                pass
    return ok, total - ok - failed


def _all_indexed_recording_ids():
    with store.conn() as c:
        return [x["recording_id"] for x in
                c.execute("SELECT DISTINCT recording_id FROM search_chunks").fetchall()]


def _scope_indexed(allowed_rids):
    """按租户可见录音裁剪已索引列表（FR-31 检索隔离）。"""
    ids = _all_indexed_recording_ids()
    if not allowed_rids:
        return ids
    allowed = set(allowed_rids)
    return [r for r in ids if r in allowed]


# ---------------- 检索（FR-25 / FR-27 / FR-29） ----------------
def _tokenize(text):
    """分词（阶段 B1）：拉丁/数字按词；中文按 2-gram（单字串保留单字）。

    相比逐字切分，bigram 让「张伟」「合同」等专名/词组成为独立 token，
    BM25 的 idf/短语区分度显著提升；查询与索引两侧共用本函数，天然一致。
    注意：改动后必须把 TOKENIZE_VERSION +1 并全量重建索引
    （search_chunks.search_text 的 token 口径变化，旧索引与新查询不再同构）。
    """
    text = (text or "").lower()
    toks = re.findall(r"[a-z0-9]+", text)
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    for run in cjk_runs:
        if len(run) == 1:
            toks.append(run)
        else:
            toks.extend(run[i:i + 2] for i in range(len(run) - 1))
    return toks


def _load_chunks(filters):
    """读取已索引切块并应用结构化过滤（FR-27）。"""
    where, params = [], []
    if filters.get("date_from"):
        where.append("date >= ?"); params.append(filters["date_from"])
    if filters.get("date_to"):
        where.append("date <= ?"); params.append(filters["date_to"])
    if filters.get("speaker"):
        where.append("speaker LIKE ?"); params.append("%" + filters["speaker"] + "%")
    if filters.get("recording_id"):
        where.append("recording_id = ?"); params.append(filters["recording_id"])
    rids = filters.get("recording_ids")
    if rids is not None:
        # 显式传入空列表 = 该租户无可见录音，必须返回空而非全量（越权防护）
        if not rids:
            where.append("0")
        else:
            ph = ",".join("?" for _ in rids)
            where.append("recording_id IN (%s)" % ph)
            params.extend(rids)
    sql = "SELECT * FROM search_chunks"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with store.conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(x) for x in rows]


def _bm25(query_tokens, chunks):
    """返回 {chunk_id: score} 与 文档排名列表。"""
    corpus = [_tokenize(ch["search_text"]) for ch in chunks]
    N = len(corpus)
    if N == 0:
        return {}, []
    df = {}
    for toks in corpus:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    idf = {t: np.log(1 + (N - d + 0.5) / (d + 0.5)) for t, d in df.items()}
    lengths = [len(t) for t in corpus]
    avgdl = sum(lengths) / N if N else 0
    scores = {}
    for i, toks in enumerate(corpus):
        if not toks:
            continue
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in query_tokens:
            if t in tf:
                f = tf[t]
                denom = f + _K1 * (1 - _B + _B * lengths[i] / avgdl) if avgdl else f + _K1
                s += idf.get(t, 0.0) * (f * (_K1 + 1)) / denom
        if s > 0:
            scores[chunks[i]["id"]] = s
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return scores, ranked


def _vector_scores(query, chunks):
    """返回 {chunk_id: cosine} 与 文档排名列表；向量不可用时回退空。"""
    valid = [c for c in chunks if c.get("embedding")]
    if not valid:
        return {}, []
    try:
        q = np.asarray(gateway_client.embed(query), dtype=np.float32)
    except Exception as e:  # noqa: BLE001
        print("[search] query embed 失败: %r" % e, flush=True)
        return {}, []
    qn = np.linalg.norm(q) or 1.0
    vecs = np.stack([np.frombuffer(c["embedding"], dtype=np.float32) for c in valid], axis=0)
    norms = np.linalg.norm(vecs, axis=1)
    norms[norms == 0] = 1.0
    sims = vecs.dot(q) / (norms * qn)
    scores = {valid[i]["id"]: float(sims[i]) for i in range(len(valid))}
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return scores, ranked


def _rrf(ranked_lists, k=_RRF_K):
    fused = {}
    for ranked in ranked_lists:
        for rank, (cid, _) in enumerate(ranked):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def _highlight(text, query):
    import html
    text = html.escape(text or "")
    toks = set(_tokenize(query))
    if not toks:
        return text
    pattern = re.compile("(" + "|".join(re.escape(t) for t in toks) + ")", re.IGNORECASE)
    return pattern.sub(r"<mark>\1</mark>", text)


def search(query, filters=None, page=1, page_size=10):
    """执行一次混合检索，返回 {results, total, facets, indexed_recordings, unindexed, meta}。

    P0-2：请求路径不再同步 ensure_indexed 全量扫描，仅查询已索引数据；
    未索引的已完成录音数量通过 unindexed 返回，由前端提示/后台异步补建。
    U2：meta 返回索引分词版本，版本落后时前端提示重建索引。
    """
    filters = filters or {}
    query = (query or "").strip()

    allowed_rids = filters.get("recording_ids")  # 租户隔离：仅限可见录音
    unindexed = store.count_unindexed(allowed_rids)
    meta = index_meta()

    if not query:
        return {"results": [], "total": 0, "facets": _facets(allowed_rids),
                "indexed_recordings": _scope_indexed(allowed_rids), "unindexed": unindexed,
                "meta": meta}

    chunks = _load_chunks(filters)
    if not chunks:
        return {"results": [], "total": 0, "facets": _facets(allowed_rids),
                "indexed_recordings": _scope_indexed(allowed_rids), "unindexed": unindexed,
                "meta": meta}

    q_tokens = _tokenize(query)
    bm25_scores, bm25_ranked = _bm25(q_tokens, chunks)
    vec_scores, vec_ranked = _vector_scores(query, chunks)

    # 1) 粗召回：BM25 + 向量 RRF，取候选
    fused0 = _rrf([bm25_ranked, vec_ranked])[:_FUSE_TOP]
    cand = [next(c for c in chunks if c["id"] == cid) for cid, _ in fused0]

    # 2) 精排 rerank：纳入 RRF 融合（而非覆盖），保留 BM25/向量信号，
    #    缓解同一会议内 rerank 区分度差导致排序翻转（FR-25/29 准确性）
    rerank_scores = {}
    rerank_ranked = None
    try:
        reranked = gateway_client.rerank(query, [c["search_text"] for c in cand])
        rerank_ranked = [cand[r[0]]["id"] for r in reranked if r[0] < len(cand)]
        # 补回未出现在 rerank 结果里的候选（极少见）
        seen = set(rerank_ranked)
        rerank_ranked += [c["id"] for c in cand if c["id"] not in seen]
        for r in reranked:
            if r[0] < len(cand):
                rerank_scores[cand[r[0]]["id"]] = float(r[1])
    except Exception as e:  # noqa: BLE001
        print("[search] rerank 失败，回退 BM25+向量融合: %r" % e, flush=True)
        rerank_ranked = None

    ranked_lists = [bm25_ranked, vec_ranked]
    if rerank_ranked is not None:
        ranked_lists.append([(cid, 0.0) for cid in rerank_ranked])
    fused = _rrf(ranked_lists)[:_FUSE_TOP]
    order = [next(c for c in chunks if c["id"] == cid) for cid, _ in fused]

    total = len(order)
    start = (max(1, page) - 1) * page_size
    page_items = order[start:start + page_size]

    # 文件名映射
    rid_names = {r["id"]: r["filename"] for r in store.list_recordings(limit=1000)}
    results = []
    for c in page_items:
        results.append({
            "recording_id": c["recording_id"],
            "filename": rid_names.get(c["recording_id"], c["recording_id"]),
            "speaker": c["speaker"],
            "date": c["date"],
            "start_ms": c["start_ms"],
            "end_ms": c["end_ms"],
            "snippet": _highlight(c["text"], query),
            "score": round(rerank_scores.get(c["id"], 0.0), 4),
        })

    _log_query(query, total, [c["recording_id"] for c in order[:10]])
    return {"results": results, "total": total, "page": page, "page_size": page_size,
            "facets": _facets(allowed_rids), "indexed_recordings": _scope_indexed(allowed_rids),
            "unindexed": unindexed, "meta": meta}


def _facets(allowed_rids=None):
    with store.conn() as c:
        if allowed_rids:
            ph = ",".join("?" for _ in allowed_rids)
            spk = c.execute(
                "SELECT speaker, COUNT(*) n FROM search_chunks WHERE recording_id IN (%s) "
                "GROUP BY speaker ORDER BY n DESC" % ph, list(allowed_rids)).fetchall()
            recs = c.execute(
                "SELECT DISTINCT sc.recording_id, r.filename, r.folder FROM search_chunks sc "
                "LEFT JOIN recordings r ON r.id=sc.recording_id "
                "WHERE sc.recording_id IN (%s)" % ph, list(allowed_rids)).fetchall()
        else:
            spk = c.execute("SELECT speaker, COUNT(*) n FROM search_chunks GROUP BY speaker ORDER BY n DESC").fetchall()
            recs = c.execute("SELECT DISTINCT sc.recording_id, r.filename, r.folder FROM search_chunks sc "
                             "LEFT JOIN recordings r ON r.id=sc.recording_id").fetchall()
    # P1-4：文件夹 facet（按录音数计），'' 归类为「未归档」
    folder_counts = {}
    for x in recs:
        f = x["folder"] or ""
        folder_counts[f] = folder_counts.get(f, 0) + 1
    return {
        "speakers": [{"speaker": x["speaker"], "count": x["n"]} for x in spk],
        "recordings": [{"id": x["recording_id"], "filename": x["filename"]} for x in recs],
        "folders": [{"folder": f or "", "count": n} for f, n in
                    sorted(folder_counts.items(), key=lambda kv: -kv[1])],
        "indexed_total": sum(x["n"] for x in spk),
    }


def _log_query(query, hit_count, top_recordings):
    """检索审计（FR-32）：仅记录查询与命中数，脱敏不存原文片段。"""
    try:
        with store.conn() as c:
            c.execute("INSERT INTO search_logs(ts,query,hit_count,recordings) VALUES(?,?,?,?)",
                      (_now(), query[:200], hit_count, ",".join(top_recordings)))
    except Exception:  # noqa: BLE001
        pass


def recent_search_logs(limit=50):
    with store.conn() as c:
        rows = c.execute(
            "SELECT ts,query,hit_count,recordings FROM search_logs ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    out = []
    for x in rows:
        d = dict(x)
        rec = (d.get("recordings") or "")
        d["recordings"] = [r for r in rec.split(",") if r]
        out.append(d)
    return out
