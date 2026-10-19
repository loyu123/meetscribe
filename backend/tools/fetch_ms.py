"""从 ModelScope 数据集下载文件（规避 shell 引号限制）。

用法:
    python fetch_ms.py list  [ns/name]
    python fetch_ms.py get   <路径> [路径...] [--ds ns/name]
    python fetch_ms.py getall [--audio] [--ds ns/name]
默认数据集: MagicData/A_CHINESE_CONVERSATIONAL_MEETING_SPEECH_CORPUS
输出目录:   测试音频/中文会议_真实
"""
import os
import sys

import requests

OUT_DIR = os.path.join(os.environ.get("MS_TEST_AUDIO", "./test-audio"), "mandarin-meetings")
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg")
DEFAULT_DS = "MagicData/A_CHINESE_CONVERSATIONAL_MEETING_SPEECH_CORPUS"


def urls(dsid):
    ns, name = dsid.split("/", 1)
    base = "https://www.modelscope.cn/api/v1/datasets/%s/%s/repo" % (ns, name)
    return base + "/tree", base


def list_files(dsid):
    tree, _ = urls(dsid)
    r = requests.get(tree, params={"Revision": "master", "Recursive": "true"}, timeout=120)
    r.raise_for_status()
    return r.json()["Data"]["Files"]


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024
    return "%.1f TB" % n


def do_list(dsid):
    fs = list_files(dsid)
    audio = [f for f in fs if f["Path"].lower().endswith(AUDIO_EXT)]
    other = [f for f in fs if not f["Path"].lower().endswith(AUDIO_EXT)]
    print("数据集: %s" % dsid)
    print("文件总数 %d | 音频 %d 个 | 其他 %d 个 | 音频总体积 %s"
          % (len(fs), len(audio), len(other), human(sum(f["Size"] for f in audio))))
    for f in sorted(fs, key=lambda x: -x["Size"])[:60]:
        print("  %-70s %s" % (f["Path"], human(f["Size"])))


def download(dsid, path):
    _, raw = urls(dsid)
    dst = os.path.join(OUT_DIR, dsid.replace("/", "__"), path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        print("  已存在, 跳过:", path)
        return
    with requests.get(raw, params={"Revision": "master", "FilePath": path},
                      stream=True, timeout=900) as r:
        r.raise_for_status()
        tmp = dst + ".part"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        os.replace(tmp, dst)
    print("  已下载: %s (%s)" % (path, human(os.path.getsize(dst))))


def parse_ds(argv):
    ds = DEFAULT_DS
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--ds":
            ds = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    return ds, rest


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "list":
        ds, rest = parse_ds(argv[1:])
        for a in rest:
            if "/" in a:
                ds = a
                break
        do_list(ds)
        return
    ds, rest = parse_ds(argv)
    if not rest:
        print(__doc__)
        return
    cmd = rest[0]
    if cmd == "get":
        for p in rest[1:]:
            download(ds, p)
    elif cmd == "getall":
        only_audio = "--audio" in rest
        for f in list_files(ds):
            p = f["Path"]
            if only_audio and not p.lower().endswith(AUDIO_EXT):
                continue
            download(ds, p)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
