#!/usr/bin/env bash
# MeetScribe 后端启动脚本（前台运行，Ctrl+C 停止）
#
# 首次运行会自动创建 .venv 并安装依赖；GPU 版 torch 请先按 README 手动安装，
# 再运行本脚本（已存在的 .venv 不会被覆盖）。
set -e
cd "$(dirname "$0")"

PY="${ASR_PYTHON:-python3}"

if [ ! -x .venv/bin/python ]; then
  echo ">> 首次运行：创建虚拟环境 .venv 并安装依赖 ..."
  "$PY" -m venv .venv
  . .venv/bin/activate
  pip install -U pip
  pip install -r requirements.txt
else
  . .venv/bin/activate
fi

echo ">> 启动 MeetScribe 后端：http://127.0.0.1:5000"
exec python -u -m app
