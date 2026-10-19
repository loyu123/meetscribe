"""口语顺滑（FR-11 延伸）：清理转写文本中的语气词/填充词，提升阅读体验。

规则（保守，避免误伤正文）：
  1. 句内按标点切分，整段仅为语气词（嗯/呃/啊/哦…及 em/uh/hmm）的片段整体删除；
  2. 片段首尾粘附的语气词前缀/后缀去除（如 "嗯那个" -> "那个"）；
  3. 清洗后为空的句子/轮次直接移除，并重建全文；
  4. 不修改数据库中的原始转写，仅在展示/总结输入时使用，便于 A/B 对照。

注意：语气词集合刻意排除「额/哈」等可构成实词的字（额度/哈尔滨），防止误删。
"""
import copy
import re

FILLERS = "嗯呃啊哦噢喔唉哎欸呀呗啦嘛"
_FILLER_SEG = re.compile(r"^(?:[%s]+|(?:em+|uh+|um+|hmm+|ah+|oh+))$" % FILLERS, re.I)
_FILLER_LEAD = re.compile(r"^[%s]+(?=.)" % FILLERS)
_FILLER_TAIL = re.compile(r"(?<=.)[%s]+$" % FILLERS)
_EN_LEAD = re.compile(r"^\s*(?:em+|uh+|um+|hmm+|ah+|oh+)\b[,\s]*", re.I)
_EN_TAIL = re.compile(r"\s(?:em+|uh+|um+|hmm+|ah+|oh+)[.!？?]?\s*$", re.I)
_SENT = re.compile(r"([，。、,.！!？?；;：:\n])")
_PUNCT_DUP = re.compile(r"\s*([，,。.！!？?；;：:])(?:\s*\1)+")
_LEAD_PUNCT = re.compile(r"^[\s，。、,.！!？?；;：:]+")
_SPACES = re.compile(r"[ \t]{2,}")


def clean_sentence(text):
    """清洗单个句子/轮次文本；返回空串表示整句都是语气词。"""
    if not text:
        return ""
    parts = _SENT.split(text)
    out = []
    for i in range(0, len(parts), 2):
        seg = parts[i]
        punct = parts[i + 1] if i + 1 < len(parts) else ""
        seg = seg.strip()
        if not seg or _FILLER_SEG.match(seg):
            continue
        seg = _FILLER_LEAD.sub("", seg)
        seg = _FILLER_TAIL.sub("", seg)
        seg = _EN_LEAD.sub("", seg)
        seg = _EN_TAIL.sub("", seg)
        seg = seg.strip()
        if seg:
            out.append(seg + punct)
    cleaned = "".join(out)
    cleaned = _PUNCT_DUP.sub(r"\1", cleaned)
    cleaned = _LEAD_PUNCT.sub("", cleaned)
    cleaned = _SPACES.sub(" ", cleaned)
    return cleaned.strip()


def clean_result(result):
    """对转写结果做口语顺滑，返回新对象（不改动原 result）。"""
    r = copy.deepcopy(result)

    segs = []
    for s in r.get("segments", []):
        t = clean_sentence(s.get("text", ""))
        if t:
            x = dict(s)
            x["text"] = t
            segs.append(x)
    r["segments"] = segs

    turns = []
    for t0 in r.get("turns", []):
        t = clean_sentence(t0.get("text", ""))
        if t:
            x = dict(t0)
            x["text"] = t
            turns.append(x)
    r["turns"] = turns

    review = []
    for s in r.get("review", []):
        t = clean_sentence(s.get("text", ""))
        if t:
            x = dict(s)
            x["text"] = t
            review.append(x)
    r["review"] = review

    label = {sp["spk"]: sp["label"] for sp in r.get("speakers", [])}
    lines = ["%s(%s)：%s" % (label.get(t["spk"], "说话人?"), t["start"], t["text"])
             for t in turns]
    r["text"] = "\n".join(lines)

    if r.get("stats"):
        st = dict(r["stats"])
        st["sentences"] = len(segs)
        st["turns"] = len(turns)
        st["chars"] = sum(len(s["text"]) for s in segs)
        st["review_count"] = len(review)
        r["stats"] = st
    return r
