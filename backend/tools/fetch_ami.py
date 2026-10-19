"""从 HuggingFace AMI 数据集(edinburghcstr/ami, sdm 配置)抓取真实会议录音片段，
按时间轴重建为一段连续会议音频，并生成"说话人 + 时间戳 + 文本"的参考转写。

用法:
    python fetch_ami.py list [pages]           # 列出各会议及各含多少句
    python fetch_ami.py <meeting_id> [秒数]    # 抓取并重建（默认 300 秒）
"""
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
import soundfile as sf

API = "https://datasets-server.huggingface.co/rows"
DS, CONFIG, SPLIT = "edinburghcstr/ami", "sdm", "test"
OUT_DIR = os.path.join(os.environ.get("MS_TEST_AUDIO", "./test-audio"), "ami-en")
SR = 16000


def fetch_page(offset, length=100):
    for attempt in range(6):
        r = requests.get(API, params={"dataset": DS, "config": CONFIG, "split": SPLIT,
                                      "offset": offset, "length": length}, timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(4 + attempt * 4)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def scan(target=None, max_pages=300, start=0):
    rows, offset, miss, total = [], start, 0, None
    for _ in range(max_pages):
        d = fetch_page(offset)
        total = d.get("num_rows_total", total)
        rs = d.get("rows", [])
        if not rs:
            break
        hit = False
        for it in rs:
            rw = it["row"]
            if target is None:
                rows.append(rw)
            elif rw.get("meeting_id") == target:
                rows.append(rw)
                hit = True
        offset += len(rs)
        time.sleep(0.4)
        if target is not None:
            if hit:
                miss = 0
            else:
                miss += 1
                if miss >= 3 and rows:
                    break
        if total and offset >= total:
            break
    return rows, total


def download_audio(row, retries=4):
    src = row["audio"][0]["src"]
    last = None
    for i in range(retries):
        try:
            r = requests.get(src, timeout=90)
            if r.status_code == 429:
                time.sleep(3 + i * 3)
                continue
            r.raise_for_status()
            a, sr = sf.read(io.BytesIO(r.content), dtype="float32")
            return a
        except Exception as e:  # noqa
            last = e
            time.sleep(2 + i * 2)
    raise last


def fmt(t):
    h = int(t // 3600)
    m = int((t - h * 3600) // 60)
    s = t - h * 3600 - m * 60
    return "%02d:%02d:%06.3f" % (h, m, s)


def do_list(pages, start=0):
    rows, total = scan(None, max_pages=pages, start=start)
    cnt = {}
    for r in rows:
        cnt[r["meeting_id"]] = cnt.get(r["meeting_id"], 0) + 1
    print("扫描 %d 行 (总 %s)，会议分布：" % (len(rows), total))
    for k, v in sorted(cnt.items()):
        print("  %-10s %d 句" % (k, v))


def do_fetch(meeting, max_seconds, start=0):
    print("扫描会议 %s 的行 ..." % meeting, flush=True)
    rows, total = scan(meeting, start=start)
    if not rows:
        print("未找到会议", meeting)
        return
    rows.sort(key=lambda r: r["begin_time"])
    end_limit = max_seconds
    rows = [r for r in rows if r["begin_time"] < end_limit]
    dur = min(end_limit, max(r["end_time"] for r in rows))
    print("命中 %d 句，重建 0 - %.1fs" % (len(rows), dur), flush=True)

    speakers = sorted({r["speaker_id"] for r in rows})
    smap = {s: "S%d" % (i + 1) for i, s in enumerate(speakers)}

    os.makedirs(OUT_DIR, exist_ok=True)
    wav_path = os.path.join(OUT_DIR, "%s_sdm_%ds.wav" % (meeting, int(dur)))

    if os.path.exists(wav_path):
        print("  音频已存在，跳过下载:", wav_path, flush=True)
    else:
        audio = np.zeros(int(dur * SR) + SR, dtype=np.float32)

        def work(r):
            try:
                return r, download_audio(r)
            except Exception as e:  # noqa
                print("  片段下载失败:", r.get("audio_id"), e, flush=True)
                return r, None

        done = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for r, a in ex.map(work, rows):
                done += 1
                if a is None:
                    continue
                b = int(r["begin_time"] * SR)
                a = a[: len(audio) - b]
                audio[b:b + len(a)] += a
                if done % 50 == 0:
                    print("  已拼接 %d/%d" % (done, len(rows)), flush=True)

        sf.write(wav_path, np.clip(audio[: int(dur * SR)], -1, 1), SR, subtype="PCM_16")

    txt_path = os.path.join(OUT_DIR, "%s_sdm_%ds_参考文本.txt" % (meeting, int(dur)))
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("# AMI 会议 %s（sdm 单远端麦克风重建，%.1fs）\n" % (meeting, dur))
        f.write("# 来源: HuggingFace edinburghcstr/ami | 说话人 %d 位: %s\n" % (
            len(speakers), ", ".join("%s=%s" % (smap[s], s) for s in speakers)))
        f.write("# 格式: [起-止] 说话人(原始ID): 文本\n\n")
        for r in rows:
            f.write("[%s - %s] %s (%s): %s\n" % (
                fmt(r["begin_time"]), fmt(r["end_time"]),
                smap.get(r["speaker_id"], "?"), r["speaker_id"], r["text"]))

    print("已写出:")
    print("  音频:", wav_path, "(%.1f MB)" % (os.path.getsize(wav_path) / 1048576))
    print("  文本:", txt_path)
    print("  说话人:", ", ".join("%s=%s" % (smap[s], s) for s in speakers))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    if sys.argv[1] == "list":
        pages = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        start = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        do_list(pages, start)
    else:
        meeting = sys.argv[1]
        secs = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
        start = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        do_fetch(meeting, secs, start)


if __name__ == "__main__":
    main()
