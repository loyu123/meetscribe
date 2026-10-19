"""查看 AISHELL-4(HF parquet) 分片的结构与样例。"""
import sys

import pyarrow.parquet as pq


def show(v, n=160):
    if isinstance(v, (bytes, bytearray)):
        return "<bytes %d>" % len(v)
    s = str(v)
    return (s[:n] + "...") if len(s) > n else s


def main():
    p = sys.argv[1]
    f = pq.ParquetFile(p)
    print("文件:", p)
    print("行数:", f.metadata.num_rows, "| 行组:", f.metadata.num_row_groups)
    print("schema:")
    print(f.schema_arrow)
    print("\n前 3 行:")
    batch = next(f.iter_batches(batch_size=3))
    for i, row in enumerate(batch.to_pylist()):
        print("--- row", i, "---")
        for k, v in row.items():
            print("  %-16s %s" % (k, show(v)))


if __name__ == "__main__":
    main()
