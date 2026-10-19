"""智能润色（LLM）：合并碎句 + 去语气词 + 书面化标点。

与 polish.py（正则轻量去语气词）的区别：本模块用 LLM 做语义级润色，
能跨碎片合并被 ASR 切得过碎的片段，输出更易读的「润色版」转写，
作为导出/阅读用途，与原始落库转写并存，不改动数据库原文。

实现要点：
  - 按「同一说话人的连续发言」成块（块内碎片以独立行 + [mm:ss] 锚点呈现），
    明确告诉模型“这些是被 ASR 切碎的连续发言，请合并为通顺句子”；
  - 推理模型会消耗大量 token 于思考，故每块 max_tokens 给足（24000）；
  - 超长发言再按字数二次切分；单块解析失败时退化为保留该块带时间戳的碎片原文。
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import gateway_client as gw
import store
from polish import clean_sentence  # 先正则清一遍，降噪再交给 LLM

_SYSTEM = (
    "你是一名专业的会议转写文本润色助手。输入是某一位说话人的一段连续发言，"
    "被语音识别（ASR）切成了很多碎句，每一行前面的中括号时间戳如 [00:05] 是各碎片的"
    "起点时间。请输出书面、易读、忠于原意的中文，严格遵守：\n"
    "1. 将这段连续发言中语义相连的碎句合并为若干通顺、自然的句子"
    "（不要保留被切碎的断句；相邻碎句应拼接成完整句子）；\n"
    "2. 去除语气词（嗯/呃/啊/哦/额/噢等）与过度口语填充词"
    "（那个/就是/然后/的话/对吧/这样子 等）；\n"
    "3. 规范并修正标点，但不要臆造事实、不要修改数字、人名、时间、术语；\n"
    "4. 每个合并后的句子用其首个碎片的 [mm:ss] 时间戳标注开头；\n"
    "5. 请直接输出最终的 JSON 数组，不要输出任何思考过程、分析或说明文字，"
    "也不要代码块标记；元素为 {\"start\":\"00:05\",\"text\":\"...\" }。"
)

_ANCHOR_RE = re.compile(r"\[([\d:]+)\]\s*(.*)")


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            for v in obj.values():
                if isinstance(v, list):
                    return v
        except Exception:
            pass
    raise ValueError("LLM 未返回可解析的 JSON")


def _ms_of(ts):
    if not ts:
        return 0
    try:
        p = [int(x) for x in str(ts).split(":")]
    except Exception:
        return 0
    if len(p) >= 3:
        return (p[0] * 3600 + p[1] * 60 + p[2]) * 1000
    return (p[0] * 60 + (p[1] if len(p) > 1 else 0)) * 1000


def _fmt_ms(ms):
    s = int(ms // 1000)
    return "%02d:%02d" % (s // 60, s % 60)


def _group_runs(segs):
    runs, cur, cur_spk = [], [], None
    for s in segs:
        if s.get("spk") != cur_spk:
            if cur:
                runs.append(cur)
            cur, cur_spk = [], s.get("spk")
        cur.append(s)
    if cur:
        runs.append(cur)
    return runs


def _chunk_runs(runs, max_chars=2000):
    out = []
    for run in runs:
        cur, n = [], 0
        for s in run:
            cur.append(s)
            n += len(s.get("text", ""))
            if n >= max_chars:
                out.append(cur)
                cur, n = [], 0
        if cur:
            out.append(cur)
    return out


def _anchored_text(run):
    parts = []
    for s in run:
        txt = clean_sentence(s.get("text", ""))
        if txt:
            parts.append("[%s] %s" % (s.get("start", "00:00"), txt))
    return "\n".join(parts)


def _fallback_turns(run, label_map, spk):
    out = []
    for s in run:
        txt = clean_sentence(s.get("text", ""))
        if not txt:
            continue
        start_ms = _ms_of(s.get("start"))
        out.append({"spk": spk, "label": label_map.get(spk, "说话人?"),
                    "start_ms": start_ms, "start": s.get("start", "00:00"),
                    "end_ms": start_ms, "end": s.get("start", "00:00"), "text": txt})
    return out


def polish_transcript(rid):
    """对给定录音的转写做 LLM 润色，返回与 result 同构的 dict（不写库）。"""
    rec = store.get_recording(rid)
    if not rec:
        raise ValueError("录音不存在")
    job = store.get_job_by_recording(rid)
    if not job:
        raise ValueError("该录音无转写任务")
    result = None
    if job.get("result_path"):
        try:
            with open(job["result_path"], "r", encoding="utf-8") as f:
                result = json.load(f)
        except Exception:
            result = None
    if not result:
        raise ValueError("暂无转写结果")

    label_map = {s["spk"]: s["label"] for s in result.get("speakers", [])}
    segs_in = result.get("segments") or result.get("turns") or []
    if not segs_in:
        raise ValueError("转写片段为空")

    chunks = _chunk_runs(_group_runs(segs_in), max_chars=2000)

    def _polish_chunk(ch):
        spk = ch[0].get("spk")
        label = label_map.get(spk, "说话人?")
        anchored = _anchored_text(ch)
        if not anchored:
            return []
        user = "以下是「%s」的一段连续发言（被 ASR 切碎，每行 [mm:ss] 为各碎片起点）：\n%s" % (label, anchored)
        try:
            content = gw.chat(
                [{"role": "system", "content": _SYSTEM},
                 {"role": "user", "content": user}],
                temperature=1, max_tokens=24000)
            arr = _extract_json(content)
            out = []
            for item in arr:
                start_ms = _ms_of(item.get("start"))
                out.append({
                    "spk": spk, "label": label,
                    "start_ms": start_ms, "start": item.get("start") or "00:00",
                    "end_ms": start_ms, "end": item.get("start") or "00:00",
                    "text": (item.get("text") or "").strip(),
                })
            return out
        except Exception:
            return _fallback_turns(ch, label_map, spk)

    # 分块并行调用 LLM（每块独立请求，总耗时≈最慢一块）
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as ex:
        results = list(ex.map(_polish_chunk, chunks))
    out_turns = [t for r in results for t in r]

    for i, t in enumerate(out_turns):
        nxt = out_turns[i + 1]["start_ms"] if i + 1 < len(out_turns) else (result.get("duration_ms") or 0)
        t["end_ms"] = nxt if nxt > t["start_ms"] else t["start_ms"]
        t["end"] = _fmt_ms(t["end_ms"])
    out_turns = [t for t in out_turns if t["text"]]

    segments = [{
        "spk": t["spk"], "text": t["text"],
        "start_ms": t["start_ms"], "end_ms": t["end_ms"],
        "start": t["start"], "end": t["end"],
        "need_review": 0, "review_reason": "",
    } for t in out_turns]

    lines_out = ["%s(%s)：%s" % (t["label"], t["start"], t["text"]) for t in out_turns]
    polished = dict(result)
    polished["turns"] = out_turns
    polished["segments"] = segments
    polished["text"] = "\n".join(lines_out)
    polished["review"] = []
    polished["stats"] = {
        "sentences": len(segments),
        "turns": len(out_turns),
        "chars": sum(len(s["text"]) for s in segments),
        "chunks": result.get("stats", {}).get("chunks", 0),
        "failed_chunks": result.get("stats", {}).get("failed_chunks", 0),
        "review_count": 0,
    }
    return polished
