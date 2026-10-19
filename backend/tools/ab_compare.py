"""A/B 对比：同一段音频分别用 Paraformer / SenseVoice / 降噪 转写，打印结果与耗时。

用法: python ab_compare.py <16k wav> [start_sec] [dur_sec]
"""
import sys
import time

import engine


def run(wav, s, e, backend, tag):
    t0 = time.time()
    r = engine.process_chunk(wav, int(s * 1000), int(e * 1000), "/tmp/ab_chunk.wav", "", None, backend)
    dt = time.time() - t0
    txt = "".join(x["text"] for x in r["sentences"])
    print("\n" + "=" * 74)
    print("%s | 后端=%s | 耗时 %.1fs | 句数 %d | 丢弃 %d" % (tag, backend, dt, len(r["sentences"]), r["dropped"]))
    print("-" * 74)
    print(txt[:900])


def main():
    wav = sys.argv[1]
    s = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    d = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0
    e = s + d
    print("音频: %s  区间: %.0f - %.0f s" % (wav, s, e))
    print("设备:", engine.device())

    run(wav, s, e, "paraformer", "① 原始音频")
    run(wav, s, e, "sensevoice", "① 原始音频")

    den = "/tmp/ab_denoise.wav"
    engine.decode_to_wav(wav, den, denoise=True)
    run(den, s, e, "paraformer", "② 降噪后")


if __name__ == "__main__":
    main()
