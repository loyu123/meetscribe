"""从 AISHELL-4 parquet 分片抽出一场会议：导出 16k WAV + 说话人/时间戳分段文本。"""
import io
import json
import os
import sys

import pyarrow.parquet as pq
import soundfile as sf

OUT_DIR = os.path.join(os.environ.get("MS_TEST_AUDIO", "./test-audio"), "aishell4-zh")


def fmt(t):
    return "%02d:%02d:%06.3f" % (int(t) // 3600, int(t) % 3600 // 60, t % 60)


def main():
    p = sys.argv[1]
    os.makedirs(OUT_DIR, exist_ok=True)
    f = pq.ParquetFile(p)
    row = next(f.iter_batches(batch_size=1)).to_pylist()[0]
    audio_bytes = row["audio"]["bytes"]
    name = row["audio"]["path"] or os.path.splitext(os.path.basename(p))[0]
    name = str(name).replace("/", "_")

    a, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
    wav = os.path.join(OUT_DIR, "AISHELL4_%s_%ds.wav" % (name, int(len(a) / sr)))
    sf.write(wav, a, sr, subtype="PCM_16")

    ts = row.get("timestamps_start") or []
    te = row.get("timestamps_end") or []
    spk = row.get("speakers") or []
    speakers = sorted(set(spk))
    smap = {s: "S%d" % (i + 1) for i, s in enumerate(speakers)}
    txt = os.path.join(OUT_DIR, "AISHELL4_%s_分段(说话人+时间).txt" % name)
    with open(txt, "w", encoding="utf-8") as fo:
        fo.write("# AISHELL-4 中文真实会议 %s（16kHz 单声道，%.1fs）\n" % (name, len(a) / sr))
        fo.write("# 来源: ModelScope argmaxinc/aishell-4 (Apache-2.0)\n")
        fo.write("# 说话人 %d 位: %s\n" % (len(speakers), ", ".join("%s=%s" % (smap[s], s) for s in speakers)))
        fo.write("# 说明: 该分片仅含 说话人+时间戳 标注，未含转写文本\n")
        fo.write("# 格式: [起-止] 说话人\n\n")
        for i in range(len(ts)):
            fo.write("[%s - %s] %s\n" % (fmt(ts[i]), fmt(te[i]), smap.get(spk[i], spk[i])))

    print("会议:", name)
    print("时长: %.1f s (%.1f min)" % (len(a) / sr, len(a) / sr / 60))
    print("采样率:", sr, "| 说话人:", ", ".join("%s=%s" % (smap[s], s) for s in speakers))
    print("分段数:", len(ts))
    print("已写出:\n  音频:", wav, "(%.1f MB)" % (os.path.getsize(wav) / 1048576))
    print("  标注:", txt)


if __name__ == "__main__":
    main()
