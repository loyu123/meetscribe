"""ITN：把中文数字/金额/百分比规整为阿拉伯数字表达。

例：百分之八十 -> 80% ；十二万 -> 12万 ；五千 -> 5000 ；五点四万 -> 5.4万 ；二点三 -> 2.3
编号/序列式数字走「逐位」通道（不能按数值语义折算）：
  二零二六杠零九幺二 -> 2026-0912 ；三零零 -> 300 ；幺三九二 -> 1392 ；XH杠300 -> XH-300
  （此前 二零二六 会被 _cn2int 折成 6，导致工单号 2026-0912 变成 "6杠9幺2"）
保护常见口语搭配（一下/一样/一起…），避免"一下"被误转成"1下"。
成语/专名（五四运动、说一不二、乱七八糟…）与约数（三四个、五六个…）同样不转写；
真实数值（三十八个、十五分钟、一九七八年）照常转换。
"""
import re

_DIGITS = {"零": 0, "一": 1, "幺": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1000}
_BIG = {"万": 10000, "亿": 100000000}

_PROTECT = ["一下儿", "一会儿", "一下子", "一点儿", "一下", "一样", "一起", "一直",
            "一边", "一般", "一些", "一定", "万一", "第一", "一定", "一块儿"]

# ---- 成语/专名等含数字的固定搭配：不转写（防回归：五四运动/说一不二/朝三暮四 等）----
_IDIOMS = [
    "说一不二", "独一无二", "数一数二", "一五一十", "一心一意", "一生一世",
    "一模一样", "一清二楚", "一干二净", "一穷二白", "一来二去", "一差二错",
    "三心二意", "三长两短", "三言两语", "三三两两", "三五成群", "三番五次",
    "三令五申", "三头六臂", "三教九流", "不三不四", "朝三暮四", "丢三落四",
    "低三下四", "推三阻四", "隔三差五", "张三李四", "朝九晚五", "四分五裂",
    "四面八方", "五湖四海", "五花八门", "六神无主", "七上八下", "七嘴八舌",
    "九牛一毛", "十全十美", "半斤八两", "五四运动", "乱七八糟", "杂七杂八",
    "七零八落", "七扭八歪", "横七竖八", "夹七夹八",
]
# ---- 约数（三四个/五六个/两三次…）：两位单个数字 + 量词 → 不转写 ----
# 前置否定环视排除"前面还是数字"的情况，保证 一九七八年/三十八个 等真实数值照常转换。
_MEASURES = ("个位名辆件套台次遍回步页家款天年月日分秒点双对群批层行列号课门"
             "本张块句段篇场局轮笔项起例份盒包箱瓶杯棵颗朵首周班级")
_APPROX = re.compile(
    r"(?<![零一二三四五六七八九十百千万亿两幺0-9])"
    r"([两二三四五六七八九][一二三四五六七八九])(?=[" + _MEASURES + r"])")

_NUM_BODY = r"[零一二三四五六七八九十百千万亿两]+(?:点[零一二三四五六七八九]+)?[万亿]?"
_PCT = re.compile(r"百分之(" + _NUM_BODY + r")")
_NUM = re.compile(_NUM_BODY)

# ---- 编号/序列式数字（逐位读出，无十百千万单位）----
# 触发条件（保守）：总位数>=3，或含"幺"且>=2位。
# 避免误伤口语搭配：五四运动 / 三四个 / 幺蛾子 / 说一不二 等（位数不足不触发）。
_SEQ_DIGIT = {"零": "0", "一": "1", "幺": "1", "二": "2", "两": "2", "三": "3",
              "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
_SEQ_BODY = re.compile(r"[0-9零一二三四五六七八九幺]+")
# 读出来的连字符：字母/数字之间的 杠/横 -> "-"（XH杠300 -> XH-300）
_SPOKEN_HYPHEN = re.compile(
    r"(?<=[0-9A-Za-z零一二三四五六七八九幺])[杠横](?=[0-9A-Za-z零一二三四五六七八九幺])")


def _seq_repl(m):
    s = m.group(0)
    if not (len(s) >= 3 or ("幺" in s and len(s) >= 2)):
        return s
    return "".join(_SEQ_DIGIT.get(c, c) for c in s)


def _cn2int(s: str) -> int:
    total = section = number = 0
    for ch in s:
        if ch in _DIGITS:
            number = _DIGITS[ch]
        elif ch in _UNITS:
            unit = _UNITS[ch]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
        elif ch in _BIG:
            section += number
            total += section * _BIG[ch]
            section = number = 0
    return total + section + number


def _convert(s: str) -> str:
    unit = ""
    for u in ("亿", "万"):
        if s.endswith(u):
            unit, s = u, s[:-1]
            break
    if "点" in s:
        ip, fp = s.split("点", 1)
        i = _cn2int(ip) if ip else 0
        f = "".join(str(_DIGITS[c]) for c in fp if c in _DIGITS)
        val = ("%d.%s" % (i, f)) if f else str(i)
    else:
        val = str(_cn2int(s)) if s else "1"
    return val + unit


def _repl(m):
    s = m.group(0)
    if s in ("一", "两", "零"):   # 单个字太容易误伤，保持原样
        return s
    return _convert(s)


def normalize_text(t: str) -> str:
    if not t:
        return t
    holders = {}

    def hold(w):
        key = "\ue000%d\ue001" % len(holders)
        holders[key] = w
        return key

    for w in _PROTECT:
        if w in t:
            t = t.replace(w, hold(w))
    for w in _IDIOMS:
        if w in t:
            t = t.replace(w, hold(w))
    t = _APPROX.sub(lambda m: hold(m.group(1)), t)

    t = _SPOKEN_HYPHEN.sub("-", t)
    t = _SEQ_BODY.sub(_seq_repl, t)
    t = _PCT.sub(lambda m: _convert(m.group(1)) + "%", t)
    t = _NUM.sub(_repl, t)

    for k, v in holders.items():
        t = t.replace(k, v)
    return t
