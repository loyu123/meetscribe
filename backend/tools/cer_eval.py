"""对 4 个 Demo 场景做 CER 评测（走真实管线 engine.process_chunk，含 ITN 与 SenseVoice 护栏）。

参考文本: 测试音频/语音识别Demo对话脚本.txt
音频:     测试音频/语音Demo_0{1..4}_*.wav
CER = (替换+删除+插入)/参考字数；"数字中性化"把数字/百分号/中文数词统一成占位符，
以排除 ITN 差异干扰。默认每配置重复 1 次（子进程隔离已验证结果完全可复现，极差=0）。
"""
import os
import re
import time
import unicodedata

import engine

BASE = os.environ.get("MS_TEST_AUDIO", "./test-audio")
SCRIPT = os.path.join(BASE, "语音识别Demo对话脚本.txt")
AUDIO = {
    1: os.path.join(BASE, "语音Demo_01_部门周会.wav"),
    2: os.path.join(BASE, "语音Demo_02_客户售前通话.wav"),
    3: os.path.join(BASE, "语音Demo_03_项目复盘会.wav"),
    4: os.path.join(BASE, "语音Demo_04_现场沟通_办公噪声.wav"),
}

_PUNCT = re.compile(r"[，。！？、；：“”‘’（）《》【】…—～·,.!?;:\"'()\[\]{}<>~`@#\$%^&*_+=|\\/]")
_AR_NUM = re.compile(r"[0-9]+(?:\.[0-9]+)?[kKmM%]?")
_CN_NUM = re.compile(r"[零一二三四五六七八九十百千万亿]+")


def norm(t, neutral=True):
    t = unicodedata.normalize("NFKC", t).lower()
    t = _PUNCT.sub("", t)
    t = re.sub(r"\s+", "", t)
    if neutral:
        t = _AR_NUM.sub("#", t)
        t = _CN_NUM.sub("#", t)
        t = re.sub(r"#+", "#", t)
    return t


def cer(ref, hyp):
    n, m = len(ref), len(hyp)
    if n == 0:
        return 0.0
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        ci = ref[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ci == hyp[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[m] / n


def load_refs():
    refs, idx = {}, 0
    with open(SCRIPT, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith("场景") and any(x in s for x in "①②③④⑤"):
                idx += 1
            if s.startswith("[") and "：" in s:
                refs.setdefault(idx, []).append(s.split("：", 1)[1])
    return {k: "".join(v) for k, v in refs.items()}


def transcribe(wav, backend, hotword=""):
    dur = engine.probe_duration_ms(wav)
    out = engine.process_chunk(wav, 0, dur, "/tmp/cer_chunk.wav", hotword, None, backend)
    txt = "".join(s["text"] for s in out["sentences"])
    return txt, out.get("backend", backend), out.get("fallback", False)


def main():
    refs = load_refs()
    rep = int(os.environ.get("CER_REPEAT", "1"))
    hw = "智聆 智聆云 李响 Tom"
    print("场景数:", sorted(refs.keys()), "| 每配置重复:", rep)
    print("子进程隔离:", engine.config.SUBPROCESS_PER_CHUNK, "| ITN:", engine.config.ITN_ENABLED)

    table = []
    for i in range(1, 5):
        if i not in refs or i not in AUDIO:
            continue
        ref = refs[i]
        rows = []
        for name, hwarg, bk in (("paraformer", "", "paraformer"),
                                ("paraformer+短热词", hw, "paraformer"),
                                ("sensevoice", "", "sensevoice")):
            cs, tags, t0 = [], set(), time.time()
            for _ in range(rep):
                hyp, real_bk, fb = transcribe(AUDIO[i], bk, hwarg)
                cs.append(cer(norm(ref), norm(hyp)))
                tags.add(real_bk + ("+回退" if fb else ""))
            mean = sum(cs) / len(cs)
            rows.append((name, mean, min(cs), max(cs), "".join(sorted(tags))))
            print("  场景%d %-16s 平均CER=%5.1f%% (min %.1f max %.1f) 实走=%s %.0fs"
                  % (i, name, mean * 100, min(cs) * 100, max(cs) * 100, "".join(sorted(tags)),
                     time.time() - t0), flush=True)
        table.append((i, len(ref), rows))

    print("\n================ 汇总 ================")
    print("%-26s %8s %8s %8s %10s" % ("场景/配置", "平均CER", "最小", "最大", "实际后端"))
    for i, n, rows in table:
        for name, mean, lo, hi, tag in rows:
            print("%-26s %7.1f%% %7.1f%% %7.1f%% %10s"
                  % ("场景%d %s" % (i, name), mean * 100, lo * 100, hi * 100, tag))


if __name__ == "__main__":
    main()
