"""音频诊断：VAD 人声分布 + 对脚本标注片段做定向转写，用于比对"脚本 vs 转写"。

用法:
    python probe_audio.py /path/to/long.wav
"""
import sys
import time

import torch
from funasr import AutoModel

import config
import engine


def fmt(ms):
    s = int(ms // 1000)
    return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


def main():
    wav = sys.argv[1]
    dev = engine.device()
    print("device:", dev, flush=True)

    # 1) VAD 人声分布
    vad = AutoModel(model=config.VAD_MODEL, device=dev, disable_update=True, hub="modelscope")
    t0 = time.time()
    res = vad.generate(input=wav)
    segs = (res[0] or {}).get("value") or []
    print("\n=== VAD：共 %d 段人声，耗时 %.1fs ===" % (len(segs), time.time() - t0))
    total = 0
    for b, e in segs:
        total += e - b
        print("  %s - %s   %.1fs" % (fmt(b), fmt(e), (e - b) / 1000.0))
    print("  人声合计: %.1f 分钟 / %d 分钟" % (total / 60000.0, engine.probe_duration_ms(wav) // 60000))
    del vad
    torch.cuda.empty_cache()

    # 2) 对脚本标注的 6 个片段做定向转写
    asr = engine.get_model()
    windows = [
        ("片段①部门周会", 120, 215),
        ("片段②技术评审", 569, 664),
        ("片段③项目复盘", 1136, 1628),
        ("片段④跨部门同步", 2217, 2315),
        ("片段⑤客户售前", 2787, 2887),
        ("片段⑥现场排查", 3359, 3483),
    ]
    for name, s, e in windows:
        out = engine.process_chunk(wav, s * 1000, e * 1000, "/tmp/probe_chunk.wav", "")
        txt = "".join(x["text"] for x in out["sentences"])
        print("\n=== %s  %s-%s (%ds) 句数=%d ===" % (name, fmt(s * 1000), fmt(e * 1000), e - s, len(out["sentences"])))
        print(txt[:500] if txt else "(无有效语音)")


if __name__ == "__main__":
    main()
