#!/usr/bin/env bash
# MeetScribe 数据备份（2.3 备份与迁移）。
#
# 用法：bash scripts/backup.sh [DATA_DIR] [OUT_DIR] [KEEP]
#   DATA_DIR  数据目录，默认 ./data（即 ASR_DATA_DIR）
#   OUT_DIR   备份输出目录，默认 ./backups
#   KEEP      保留最近多少份整包备份，默认 14；0 = 不清理
#
# 产出：
#   - meetscribe-data-<时间>.tar.gz   data/ 整目录打包（建议停服后执行）
#   - asr-<时间>.db                   若装有 sqlite3，额外输出一致性数据库快照
#                                     （服务运行中备份也安全；恢复时用它替换包内
#                                      asr.db，并删除 asr.db-wal / asr.db-shm）
#
# 恢复：停后端 → 用备份覆盖 data/ → 启动。
set -euo pipefail

DATA_DIR="${1:-./data}"
OUT_DIR="${2:-./backups}"
KEEP="${3:-14}"

if [ ! -d "$DATA_DIR" ]; then
  echo "[backup] 数据目录不存在: $DATA_DIR" >&2
  exit 1
fi
mkdir -p "$OUT_DIR"
TS="$(date +%Y%m%d-%H%M%S)"

# 1) 一致性数据库快照（有 sqlite3 时；运行中执行也安全）
DB="$DATA_DIR/asr.db"
if [ -f "$DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".backup '$OUT_DIR/asr-$TS.db'"
  echo "[backup] 已生成一致性数据库快照: asr-$TS.db"
fi

# 2) 整目录打包
OUT="$OUT_DIR/meetscribe-data-$TS.tar.gz"
tar -C "$(dirname "$DATA_DIR")" -czf "$OUT" "$(basename "$DATA_DIR")"
echo "[backup] 已打包: $OUT ($(du -h "$OUT" | cut -f1))"

# 3) 只保留最近 KEEP 份整包
if [ "$KEEP" -gt 0 ] 2>/dev/null; then
  ls -1t "$OUT_DIR"/meetscribe-data-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) |
    while IFS= read -r f; do
      rm -f "$f"
      echo "[backup] 清理旧备份: $f"
    done
fi
echo "[backup] 完成。恢复：停后端 → 用备份覆盖 data/ → 启动。"
