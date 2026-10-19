"""长音频 CER / 覆盖率评测（独立运行，不依赖 ASR 引擎）。

用途：对长音频转写结果做「字符级 CER」+「分段覆盖率」评估，并显式检测：
  - 参考脚本中缺失的片段（整段漏识别 / 音频缺失）
  - 转写里重复出现的片段（冗余 / 音频串段）
  - 各片段内容 CER（只统计已转写内容的字准）
  - 全局 CER（整篇对齐，含缺失/重复/乱序）

验收口径（语音系统计划方案.md 八）：中英混说 CER ≤ 12%，清晰近讲 ≤ 8%。

用法：
  python cer_long.py <参考脚本.txt> <转写结果.json|转写.txt> [文件名=xxx]
未给参数时，尝试在常见根目录下自动发现 1小时长音频_对话脚本.txt 与 long_audio 结果。
"""
import json
import os
import re
import sys

PUNCT = set('，。、；：？！“”‘’（）《》【】…—.,;:?!()[]{}<>\'"\n\r\t /\\')


def norm(t):
    return "".join(c for c in (t or "").lower() if c not in PUNCT)


def lev(a, b):
    m, n = len(a), len(b)
    if not m:
        return n
    if not n:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        ai = a[i - 1]
        for j in range(1, n + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def load_ref(path):
    """解析对话脚本，返回 [(片段名, 归一化文本), ...]。"""
    text = open(path, encoding="utf-8").read()
    parts = re.split(r"【片段[①②③④⑤⑥]】", text)
    names = re.findall(r"【片段[①②③④⑤⑥]】([^\n]+)", text)
    out = []
    for i, p in enumerate(parts[1:]):
        body = re.split(r"【(本字段抽取|字段抽取)】", p)[0]
        lines = re.findall(r"\[说话人[AB]\]：(.*)", body)
        nm = names[i].strip() if i < len(names) else "片段%d" % (i + 1)
        out.append((nm, norm("".join(lines))))
    return out


def load_blocks(path, gap_s=180):
    """读转写结果，按时间跳变(>gap_s 秒)切成「会议块」，返回 [(起分, 归一化文本), ...]。"""
    if path.lower().endswith(".json"):
        data = json.load(open(path, encoding="utf-8"))
        if isinstance(data, dict) and "result" in data and data["result"]:
            data = data["result"]
        segs = data.get("segments") or []
        items = [(int(s.get("start_ms", 0)), s.get("text", "")) for s in segs]
    else:
        items, pat = [], re.compile(r"说话人\s*\d+\((\d+):(\d+):(\d+)\)：(.*)")
        for line in open(path, encoding="utf-8"):
            mt = pat.match(line.rstrip("\n"))
            if mt:
                ms = (int(mt.group(1)) * 3600 + int(mt.group(2)) * 60 + int(mt.group(3))) * 1000
                items.append((ms, mt.group(4)))
    items.sort(key=lambda x: x[0])
    blocks, cur, cur_end = [], [], None
    for st, t in items:
        if cur and cur_end is not None and st - cur_end > gap_s * 1000:
            blocks.append((cur_end, norm("".join(cur))))
            cur = []
        if t:
            cur.append(t)
        cur_end = st
    if cur:
        blocks.append((cur_end, norm("".join(cur))))
    return blocks


def evaluate(ref, blocks):
    ref_names = [n for n, _ in ref]
    use = [0] * len(ref)
    print("=" * 78)
    print("逐块内容 CER（每块独立匹配最相似片段，忽略标点/空白）")
    print("%-9s%-20s%8s%8s%7s%9s" % ("起(分)", "匹配片段", "ref字", "hyp字", "编辑", "CER"))
    c_ed = c_ref = 0
    for st, hn in blocks:
        if not hn:
            continue
        bj, bd = 0, 1 << 30
        for j, (_, rn) in enumerate(ref):
            if rn:
                d = lev(hn, rn)
                if d < bd:
                    bd, bj = d, j
        rn = ref[bj][1]
        use[bj] += 1
        c_ed += bd
        c_ref += len(rn)
        flag = " (重复)" if use[bj] > 1 else ""
        print("%-9d%-20s%8d%8d%7d%8.1f%%" % (st // 60000, ref_names[bj][:16] + flag,
                                             len(rn), len(hn), bd, bd / len(rn) * 100))
    print("-" * 78)
    content_cer = c_ed / c_ref if c_ref else 0.0
    print("逐块加权内容 CER（已转写内容的字准） = %.1f%%" % (content_cer * 100))

    print("\n【结构完整性】")
    for j, nm in enumerate(ref_names):
        if use[j] == 0:
            print("  缺失片段: %s（整段未被转写，约 %d 字）" % (nm, len(ref[j][1])))
        elif use[j] > 1:
            print("  重复片段: %s（被转写 %d 次，多余 %d 次）" % (nm, use[j], use[j] - 1))

    ref_full = "".join(rn for _, rn in ref)
    hyp_full = "".join(hn for _, hn in blocks)
    g = lev(hyp_full, ref_full)
    print("\n【全局文档 CER（整篇对齐，含缺失/重复/乱序）】")
    print("  ref=%d  hyp=%d  编辑距离=%d" % (len(ref_full), len(hyp_full), g))
    print("  全局 CER = %.1f%%" % (g / len(ref_full) * 100))
    print("=" * 78)
    return content_cer, g / len(ref_full)


def _discover():
    roots = [os.environ.get("MS_TEST_AUDIO", ".")]
    ref = hyp = None
    for base in roots:
        for r, d, fs in os.walk(base):
            for f in fs:
                p = os.path.join(r, f)
                if f == "1小时长音频_对话脚本.txt":
                    ref = p
                if f.endswith(".json"):
                    try:
                        head = open(p, encoding="utf-8").read(2000)
                    except Exception:
                        continue
                    if "long_audio_1h_office" in head and "segments" in head:
                        hyp = p
        if ref and hyp:
            break
    return ref, hyp


def main():
    if len(sys.argv) >= 3:
        ref_path, hyp_path = sys.argv[1], sys.argv[2]
    else:
        ref_path, hyp_path = _discover()
    if not ref_path or not hyp_path:
        print("未找到参考脚本/转写结果，请显式传入路径。")
        return
    print("参考脚本:", ref_path)
    print("转写结果:", hyp_path)
    ref = load_ref(ref_path)
    blocks = load_blocks(hyp_path)
    cc, gc = evaluate(ref, blocks)
    print("\n判定：内容CER=%.1f%% (%s ≤12%%) | 全局CER=%.1f%% (%s ≤12%%)" % (
        cc * 100, "通过" if cc <= 0.12 else "不通过",
        gc * 100, "通过" if gc <= 0.12 else "不通过"))


if __name__ == "__main__":
    main()
