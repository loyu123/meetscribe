"""ASR + 说话人分离引擎（FunASR paraformer/fsmn-vad/ct-punc + CAM++）。

核心思路（既控内存、又能跨分片统一说话人）：
  1. 音频统一解码为 16k/单声道 wav；
  2. 按固定时长分片（切点尽量吸附到静音处，避免切断句子）；
  3. 每个分片用 FunASR 一次性得到：句级文本 + 时间戳 + 分片内说话人(local spk) + 说话人质心向量；
  4. 所有分片的质心向量在"全局"做一次聚类，把 local spk 映射为全局说话人编号。

仅做"会话内"说话人分离；不提取、不落库声纹。
"""
import json
import re
import subprocess
import threading
import time
from typing import List, Optional, Tuple

import numpy as np
import soundfile as sf
import torch
from funasr import AutoModel

# 关闭 TF32：实测显著降低 GPU 数值抖动（场景1 CER 极差 22.6%→5.8%）并略提升精度
torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cudnn.allow_tf32 = False
torch.backends.cudnn.benchmark = False

import config
import itn

_models = {}
_load_lock = threading.Lock()
# FunASR 推理非线程安全，串行化
_infer_lock = threading.Lock()

# ---------------- 常驻推理进程池 ----------------
# 解决"每个分片 fork 子进程重复加载整套模型"的开销：池内每个进程只加载一次模型，
# 反复从队列取分片推理；INFER_PROCESSES 控制并发进程数（= 并发推理数）。
import os as _os
import uuid as _uuid
import concurrent.futures as _cf
import multiprocessing as _mp

_INFER_POOL = None
_POOL_LOCK = threading.Lock()


def _pool_init():
    """池子进程初始化：父进程退出时自动自杀，避免遗留孤儿进程继续占用 GPU。"""
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl(1, 9)  # PR_SET_PDEATHSIG, SIGKILL
    except Exception:
        pass


def _get_infer_pool():
    global _INFER_POOL
    with _POOL_LOCK:
        if _INFER_POOL is None:
            ctx = _mp.get_context("spawn")
            n = max(1, int(getattr(config, "INFER_PROCESSES", 1)))
            _INFER_POOL = _cf.ProcessPoolExecutor(
                max_workers=n, mp_context=ctx, initializer=_pool_init)
        return _INFER_POOL


def _pool_infer(wav_path, start_ms, end_ms, out_dir, hotword, preset_spk_num, backend):
    """在池进程内执行单分片推理（含 SenseVoice 回退）；模型在该进程内只加载一次。"""
    chunk_wav = _os.path.join(out_dir, "pool_%s.wav" % _uuid.uuid4().hex)
    try:
        out = _run_backend(wav_path, start_ms, end_ms, chunk_wav, hotword, preset_spk_num, backend)
        out["backend"] = backend
        out["fallback"] = False
        if config.SV_FALLBACK and backend == "sensevoice":
            sp, ch = out["speech_sec"], out["chars"]
            cps = ch / sp if sp > 1 else 0.0
            if sp <= 1 or cps < config.SV_MIN_CPS:
                fb = _run_backend(wav_path, start_ms, end_ms, chunk_wav, hotword, preset_spk_num, "paraformer")
                fb["backend"] = "paraformer"
                fb["fallback"] = True
                fb["fallback_reason"] = "sensevoice 疑似漏识别(cps=%.2f)" % cps
                out = fb
        return out
    finally:
        try:
            _os.remove(chunk_wav)
        except OSError:
            pass


def submit_chunk(wav_path, start_ms, end_ms, out_dir, hotword, preset_spk_num, backend):
    """提交一个分片到常驻进程池，返回 Future。"""
    pool = _get_infer_pool()
    return pool.submit(_pool_infer, wav_path, start_ms, end_ms, out_dir,
                       hotword or "", preset_spk_num or 0, backend)


def shutdown_infer_pool():
    global _INFER_POOL
    with _POOL_LOCK:
        if _INFER_POOL is not None:
            _INFER_POOL.shutdown(wait=False)
            _INFER_POOL = None


def device() -> str:
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def get_model(backend: str = "paraformer"):
    """按后端返回(并缓存)模型：paraformer | sensevoice。"""
    backend = (backend or "paraformer").lower()
    if backend in _models:
        return _models[backend]
    with _load_lock:
        if backend in _models:
            return _models[backend]
        t0 = time.time()
        if backend == "sensevoice":
            print(">> 加载 SenseVoice (SenseVoiceSmall + fsmn-vad + cam++) device=%s fp16=%s"
                  % (device(), config.FP16 and torch.cuda.is_available()), flush=True)
            m = AutoModel(
                model=config.SENSEVOICE_MODEL,
                vad_model=config.VAD_MODEL,
                spk_model=config.SPK_MODEL,
                device=device(),
                disable_update=True,
                hub="modelscope",
                fp16=config.FP16 and torch.cuda.is_available(),
            )
        else:
            print(">> 加载 Paraformer (paraformer + fsmn-vad + ct-punc + cam++) device=%s fp16=%s"
                  % (device(), config.FP16 and torch.cuda.is_available()), flush=True)
            m = AutoModel(
                model=config.ASR_MODEL,
                vad_model=config.VAD_MODEL,
                punc_model=config.PUNC_MODEL,
                spk_model=config.SPK_MODEL,
                device=device(),
                disable_update=True,
                hub="modelscope",
                fp16=config.FP16 and torch.cuda.is_available(),
            )
        _models[backend] = m
        print(">> 模型加载完成 %.1fs" % (time.time() - t0), flush=True)
    return _models[backend]


def _sv_clean(t: str) -> str:
    """去掉 SenseVoice 的特殊标签（<|zh|><|NEUTRAL|> 等）。"""
    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
        return rich_transcription_postprocess(t or "")
    except Exception:
        return re.sub(r"<\|[^|]*\|>", "", t or "")


# ---------------- 音频工具 ----------------
def probe_duration_ms(path: str) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return int(float(out) * 1000)
    except ValueError:
        return 0


def probe_audio(path: str) -> dict:
    """探测音频元数据（FR-03 上传校验）：时长/采样率/声道数/编码，并判定是否可解码。

    返回 {duration_ms, sample_rate, channels, codec, ok}。ok=False 表示文件损坏或无法解码。
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration:stream=sample_rate,channels,codec_name",
             "-of", "json", path],
            capture_output=True, text=True,
        )
        d = json.loads(out.stdout or "{}")
        fmt = d.get("format", {})
        dur_ms = int(float(fmt.get("duration", 0) or 0) * 1000)
        stream = (d.get("streams") or [{}])[0]
        codec = stream.get("codec_name") or ""
        return {
            "duration_ms": dur_ms,
            "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0),
            "codec": codec,
            "ok": dur_ms > 0 and bool(codec),
        }
    except Exception:
        return {"duration_ms": 0, "sample_rate": 0, "channels": 0, "codec": "", "ok": False}


def decode_to_wav(src: str, dst: str, denoise: bool = False) -> str:
    """转 16k / 单声道 / PCM16 wav（可选降噪前处理，FR-14）。"""
    cmd = ["ffmpeg", "-y", "-i", src, "-ac", "1", "-ar", "16000"]
    if denoise:
        cmd += ["-af", config.DENOISE_FILTER]
    cmd += ["-f", "wav", dst]
    subprocess.run(cmd, capture_output=True, check=True)
    return dst


def detect_silences_ms(path: str) -> List[Tuple[int, int]]:
    """用 ffmpeg silencedetect 找静音区间（用于选择分片切点）。"""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af", "silencedetect=noise=-35dB:d=0.6", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    txt = p.stderr or ""
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", txt)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", txt)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else s + 0.6
        out.append((int(s * 1000), int(e * 1000)))
    return out


def plan_chunks(duration_ms: int, silences: List[Tuple[int, int]], chunk_ms: int) -> List[Tuple[int, int]]:
    """把整段音频划分成若干 (start_ms, end_ms)，切点尽量落在静音中点。"""
    if duration_ms <= 0:
        return [(0, 0)]
    if duration_ms <= chunk_ms:
        return [(0, duration_ms)]

    centers = [(s + e) / 2.0 for s, e in silences]
    ranges = []
    prev = 0
    target = chunk_ms
    while target < duration_ms - 2000:
        best, bestd = None, None
        for c in centers:
            if c <= prev + 30_000:  # 与上一个切点至少隔 30s
                continue
            d = abs(c - target)
            if bestd is None or d < bestd:
                bestd, best = d, c
        if best is not None and bestd is not None and bestd <= 60_000 and best < duration_ms - 2000:
            cut = int(best)
        else:
            cut = int(target)
        if cut > prev + 30_000:
            ranges.append((prev, cut))
            prev = cut
        target += chunk_ms
    ranges.append((prev, duration_ms))
    return ranges


def extract_chunk(wav_path: str, start_ms: int, end_ms: int, out_path: str) -> str:
    """按时间区间从 16k wav 中截取一段并写出（流式 seek，不整文件载入）。"""
    with sf.SoundFile(wav_path) as f:
        sr = f.samplerate
        f.seek(int(start_ms * sr / 1000))
        frames = int((end_ms - start_ms) * sr / 1000)
        data = f.read(frames, dtype="float32")
    sf.write(out_path, data, sr, subtype="PCM_16")
    return out_path


# ---------------- 文本后处理 ----------------
_DUP_CHAR = re.compile(r"(.)\1{2,}")                       # 连续重复 >=3 次同一字符
_DUP_PUNCT = re.compile(r"([，。！？、；：,.!?;:~…])\1+")   # 连续重复标点
_MEANINGFUL = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")     # 至少含一个中文/字母/数字
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)   # SenseVoice 情感标签会渲染成 emoji，会议转写中应剔除


def clean_text(t) -> str:
    """清洗 ASR 文本：去 emoji、折叠重度重复字与重复标点、压缩空白。

    兼容 FunASR 某些版本把 sentence_info 的 text 返回为 list 的情况。
    """
    if not t:
        return ""
    if isinstance(t, (list, tuple)):
        t = "".join(str(x) for x in t)
    t = str(t).strip()
    t = _EMOJI.sub("", t)
    t = _DUP_CHAR.sub(r"\1", t)
    t = _DUP_PUNCT.sub(r"\1", t)
    t = re.sub(r"\s+", " ", t)
    # 英文大小写规整（FR-12）：段首小写英文字母首字母大写，不改动已大写/缩写词
    if t and "a" <= t[0] <= "z":
        t = t[0].upper() + t[1:]
    return t.strip()


def is_meaningful(t: str) -> bool:
    """是否含有效内容（过滤纯标点/纯空白段）。"""
    return bool(t) and bool(_MEANINGFUL.search(t))


def _heuristic_confidence(base: str, cleaned: str, start_ms: int, end_ms: int) -> float:
    """启发式置信度（0~1）：模型未输出概率时的质量代理指标。

    综合 异常字符折叠、过短、疑似漏字 三个信号给出评分，仅作质量参考，
    不是模型输出的真实概率。
    """
    score = 1.0
    if base.strip() != cleaned.strip():
        score -= 0.3                       # 有重复字/异常标点
    if len(cleaned) <= config.REVIEW_MIN_CHARS:
        score -= 0.3                       # 过短
    dur = max(0.001, (end_ms - start_ms) / 1000.0)
    if dur >= config.REVIEW_MAX_SEG_SEC and len(cleaned) / dur < config.REVIEW_MAX_CHARS_PER_SEC:
        score -= 0.3                       # 疑似漏字
    return max(0.0, min(1.0, score))


def review_flag(base: str, cleaned: str, start_ms: int, end_ms: int, conf=None):
    """低置信度/异常段启发式标记（FR-17 / FR-14）。返回 (0/1, 原因)。"""
    reasons = []
    if len(cleaned) <= config.REVIEW_MIN_CHARS:
        reasons.append("过短")
    if base.strip() != cleaned.strip():
        reasons.append("重复字/异常标点")
    dur = max(0.001, (end_ms - start_ms) / 1000.0)
    if dur >= config.REVIEW_MAX_SEG_SEC and len(cleaned) / dur < config.REVIEW_MAX_CHARS_PER_SEC:
        reasons.append("疑似漏字")
    if conf is not None and conf < config.REVIEW_MIN_CONF:
        reasons.append("低置信度")
    return (1 if reasons else 0), ",".join(reasons)


# ---------------- 单分片处理 ----------------
def _run_backend(wav_path: str, start_ms: int, end_ms: int, chunk_wav: str,
                 hotword: str, preset_spk_num, backend: str) -> dict:
    model = get_model(backend)
    extract_chunk(wav_path, start_ms, end_ms, chunk_wav)
    kwargs = {
        "input": chunk_wav,
        "batch_size_s": 300,
        "sentence_timestamp": True,
        "return_spk_center": True,
    }
    if backend == "sensevoice":
        kwargs["use_itn"] = True
        kwargs["language"] = "auto"
    if hotword:
        kwargs["hotword"] = hotword
    if preset_spk_num:
        kwargs["preset_spk_num"] = int(preset_spk_num)

    with _infer_lock:
        res = model.generate(**kwargs)
    item = res[0] if res else {}

    sentences = []
    dropped = 0
    for s in item.get("sentence_info") or []:
        raw = s.get("text") or ""
        if isinstance(raw, (list, tuple)):      # FunASR 某些版本 text 返回 list
            raw = "".join(str(x) for x in raw)
        # SenseVoice 逐句结果带 <|zh|><|NEUTRAL|><|Speech|><|withitn|> 等富标签，必须先剥离
        base = _sv_clean(str(raw))
        cleaned = clean_text(base)
        if not is_meaningful(cleaned):
            dropped += 1
            continue
        st = int(s.get("start", 0)) + start_ms
        en = int(s.get("end", 0)) + start_ms
        # ---- 置信度（FR-14）----
        cf_raw = s.get("confidence")             # 标量 或 按 token 的列表
        seg_conf = None
        if isinstance(cf_raw, (list, tuple)):
            vals = [float(x) for x in cf_raw if x is not None]
            seg_conf = (sum(vals) / len(vals)) if vals else None
        elif isinstance(cf_raw, (int, float)):
            seg_conf = float(cf_raw)
        if seg_conf is None:
            # 该 FunASR/Paraformer 版本不输出模型概率，用启发式代理（非模型概率，仅作质量参考）
            seg_conf = _heuristic_confidence(base, cleaned, st, en)
        need, reason = review_flag(base, cleaned, st, en, seg_conf)
        # ---- 字级时间戳（FR-14，可选）----
        # 时间戳对齐到模型原始 token(base)；仅当规整/ITN 未改变文本时才输出，
        # 以保证 words 与展示 text 逐字对齐，避免错位的字级时间戳。
        txt = itn.normalize_text(cleaned) if config.ITN_ENABLED else cleaned
        words = None
        ts_list = s.get("timestamp")
        if (config.WORD_TIMESTAMP and isinstance(ts_list, (list, tuple)) and ts_list
                and txt == base):
            chars = list(base)
            n = min(len(chars), len(ts_list))
            words = []
            for i in range(n):
                t0, t1 = ts_list[i]
                wconf = None
                if isinstance(cf_raw, (list, tuple)) and i < len(cf_raw) and cf_raw[i] is not None:
                    wconf = float(cf_raw[i])
                words.append({"t": chars[i], "start_ms": int(t0) + start_ms,
                              "end_ms": int(t1) + start_ms, "conf": wconf})
        sentences.append({
            "start_ms": st,
            "end_ms": en,
            "text": txt,
            "local_spk": int(s.get("spk", 0) or 0),
            "need_review": need,
            "review_reason": reason,
            "confidence": seg_conf,
            "words": words,
        })

    centroids = None
    c = item.get("spk_embedding_center")
    if c is not None:
        try:
            arr = c.detach().cpu().numpy() if hasattr(c, "detach") else np.asarray(c)
            centroids = arr.astype(np.float32)
        except Exception:
            centroids = None
    speech = sum((x["end_ms"] - x["start_ms"]) for x in sentences) / 1000.0
    return {"sentences": sentences, "centroids": centroids, "dropped": dropped,
            "speech_sec": speech, "chars": sum(len(x["text"]) for x in sentences)}


def _subprocess_run(wav_path, start_ms, end_ms, chunk_wav, hotword, preset_spk_num, backend):
    """在独立子进程中处理一个分片（规避进程级 CUDA 状态漂移）。"""
    import json
    import os
    import subprocess
    import sys as _sys

    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chunk_runner.py")
    cmd = [_sys.executable, runner, wav_path, str(start_ms), str(end_ms), backend,
           hotword or "", str(preset_spk_num or 0), chunk_wav]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError("chunk_runner 失败: %s" % (p.stderr[-400:] or p.stdout[-400:]))
    d = json.loads(p.stdout)
    if d.get("centroids") is not None:
        d["centroids"] = np.asarray(d["centroids"], dtype=np.float32)
    return d


def process_chunk(wav_path: str, start_ms: int, end_ms: int, chunk_wav: str,
                  hotword: str = "", preset_spk_num: Optional[int] = None,
                  backend: str = "paraformer") -> dict:
    """处理单个分片；SenseVoice 若疑似漏识别则自动回退 Paraformer。

    返回 {sentences, centroids, dropped, backend, fallback[, fallback_reason]}
    """
    if config.INFER_POOL:
        out = submit_chunk(wav_path, start_ms, end_ms, config.AUDIO_DIR,
                           hotword, preset_spk_num, backend).result()
        out.setdefault("backend", backend)
        out.setdefault("fallback", False)
        return out
    if config.SUBPROCESS_PER_CHUNK:
        out = _subprocess_run(wav_path, start_ms, end_ms, chunk_wav, hotword, preset_spk_num, backend)
    else:
        out = _run_backend(wav_path, start_ms, end_ms, chunk_wav, hotword, preset_spk_num, backend)
    out["backend"] = backend
    out["fallback"] = False
    if config.SV_FALLBACK and backend == "sensevoice":
        sp, ch = out["speech_sec"], out["chars"]
        cps = ch / sp if sp > 1 else 0.0
        if sp <= 1 or cps < config.SV_MIN_CPS:
            fb = _run_backend(wav_path, start_ms, end_ms, chunk_wav, hotword, preset_spk_num, "paraformer")
            fb["backend"] = "paraformer"
            fb["fallback"] = True
            fb["fallback_reason"] = "sensevoice 疑似漏识别(cps=%.2f)" % cps
            return fb
    return out


def cluster_speakers(centroids: np.ndarray, threshold: float, n_clusters: Optional[int] = None):
    """对质心向量聚类，返回每个质心的全局说话人标签列表。"""
    from sklearn.cluster import AgglomerativeClustering

    X = np.asarray(centroids, dtype=np.float32)
    if len(X) == 0:
        return []
    if len(X) == 1:
        return [0]
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    if n_clusters:
        k = max(1, min(int(n_clusters), len(X)))
        m = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
        return m.fit_predict(X).tolist()
    m = AgglomerativeClustering(n_clusters=None, distance_threshold=threshold,
                                metric="cosine", linkage="average")
    return m.fit_predict(X).tolist()


def fmt_ms(ms: int) -> str:
    if ms is None:
        return ""
    s = int(ms // 1000)
    return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)
