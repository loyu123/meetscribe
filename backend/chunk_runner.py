"""子进程入口：处理单个分片并输出 JSON。

目的：规避"进程内多次调用导致的 CUDA 分配器状态漂移"——每个分片都在全新进程中执行，
即始终是"新进程首调用"（实测该状态下结果稳定且最好）。

用法: python chunk_runner.py <wav> <start_ms> <end_ms> <backend> <hotword> <preset|0> <tmp_wav>
"""
import json
import sys

# 把引擎的打印重定向到 stderr，保证 stdout 只输出 JSON
_real_stdout = sys.stdout
sys.stdout = sys.stderr

import engine  # noqa: E402


def main():
    wav = sys.argv[1]
    s = int(sys.argv[2])
    e = int(sys.argv[3])
    backend = sys.argv[4]
    hotword = sys.argv[5]
    preset = int(sys.argv[6]) if sys.argv[6] not in ("", "0", "None") else None
    tmp = sys.argv[7] if len(sys.argv) > 7 else "/tmp/chunk_runner.wav"

    out = engine._run_backend(wav, s, e, tmp, hotword, preset, backend)
    c = out.get("centroids")
    out["centroids"] = c.tolist() if c is not None else None
    _real_stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
