# MeetScribe 后端镜像（P0-4）
# CPU 版（默认）：
#   docker build -t meetscribe-backend ./backend
# GPU 版（CUDA 12.8 运行时，需 nvidia-container-toolkit）：
#   docker build --build-arg BASE=nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04 \
#     --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128 \
#     -t meetscribe-backend:gpu ./backend
ARG BASE=python:3.11-slim
FROM ${BASE}

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# ffmpeg：分片转码/静音点检测依赖；libgomp：torch 运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# 先装 torch（按架构选择 CPU/CUDA 源），再装其余锁定依赖
RUN pip install torch --index-url ${TORCH_INDEX}
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

WORKDIR /app
COPY . /app

# 数据（上传/音频/结果/SQLite）与模型缓存均走挂载卷，容器重建不丢数据、不重下模型
ENV ASR_DATA_DIR=/data \
    ASR_DB_PATH=/data/asr.db \
    MODELSCOPE_CACHE=/models
VOLUME ["/data", "/models"]

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
    CMD curl -sf http://127.0.0.1:5000/api/v1/system >/dev/null || exit 1

CMD ["python", "-u", "-m", "app"]
