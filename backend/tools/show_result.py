"""命令行查看某次转写结果摘要。用法: python show_result.py <recording_id> [base_url]"""
import sys

import requests


def main():
    rid = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:5000"
    d = requests.get(base + "/api/v1/recordings/" + rid).json()
    job = d.get("job") or {}
    r = d.get("result")
    print("status=%s progress=%s chunks=%s/%s failed=%s" % (
        job.get("status"), job.get("progress"), job.get("done_chunks"),
        job.get("total_chunks"), job.get("failed_chunks")))
    if not r:
        print("无结果")
        return
    print("时长 %s | 说话人 %s | %s" % (r["duration"], r["num_speakers"], r["stats"]))
    print("说话人映射:", ", ".join("%s=%s" % (s["spk"], s["label"]) for s in r["speakers"]))
    print("\n--- 轮次(前 15) ---")
    for t in r["turns"][:15]:
        print("[%s - %s] SPK%s  %s" % (t["start"], t["end"], t["spk"], t["text"][:90]))


if __name__ == "__main__":
    main()
