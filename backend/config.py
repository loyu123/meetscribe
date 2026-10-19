"""全局配置（可用环境变量覆盖）。"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 应用版本（用于「关于」弹层与系统信息条；开源后与 Git tag 对齐）
APP_VERSION = "1.0.0"
DATA_DIR = os.environ.get("ASR_DATA_DIR", os.path.join(BASE_DIR, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")   # 分片上传临时目录
AUDIO_DIR = os.path.join(DATA_DIR, "audio")      # 原始音频 + 归一化 wav
RESULT_DIR = os.path.join(DATA_DIR, "results")   # 结果 JSON
# SQLite 数据库默认与应用数据放在一起；如在 Windows 挂载盘(/mnt/c, DrvFS)上运行，
# WAL 并发下偶发 "unable to open database file"，此时建议用 ASR_DB_PATH 指到 WSL 本地盘。
DB_PATH = os.environ.get("ASR_DB_PATH", os.path.join(DATA_DIR, "asr.db"))

# ---- 模型（FunASR + CAM++）----
ASR_MODEL = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_MODEL = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
SPK_MODEL = "cam++"  # -> iic/speech_campplus_sv_zh-cn_16k-common

# 可切换的 ASR 后端：paraformer(默认) | sensevoice
SENSEVOICE_MODEL = "iic/SenseVoiceSmall"
DEFAULT_ASR_BACKEND = os.environ.get("ASR_BACKEND", "paraformer")
# 降噪前处理（FR-14，默认关闭；开启后对解码后的 wav 做降噪）
DEFAULT_DENOISE = os.environ.get("ASR_DENOISE", "0") == "1"
DENOISE_FILTER = os.environ.get("ASR_DENOISE_FILTER", "afftdn=nr=12:nf=-25")
# 低置信度/异常段复核阈值（FR-17）
REVIEW_MIN_CHARS = int(os.environ.get("ASR_REVIEW_MIN_CHARS", "2"))
REVIEW_MAX_SEG_SEC = float(os.environ.get("ASR_REVIEW_SEG_SEC", "20"))
REVIEW_MAX_CHARS_PER_SEC = float(os.environ.get("ASR_REVIEW_CPS", "1.2"))
# 低置信度阈值（FR-14）：模型给出的段落置信度低于此值 → 标记人工复核
REVIEW_MIN_CONF = float(os.environ.get("ASR_REVIEW_MIN_CONF", "0.6"))
# 是否输出字级时间戳（FR-14，可选）：从 sentence_info 的 token 时间戳提取。关闭：ASR_WORD_TS=0
WORD_TIMESTAMP = os.environ.get("ASR_WORD_TS", "1") in ("1", "true", "True")

# 分段时长（秒）。长音频按此切成多个"工作单元"，便于控内存 + 失败段重跑
CHUNK_SECONDS = int(os.environ.get("ASR_CHUNK_SECONDS", "300"))
# 跨分片说话人合并的余弦距离阈值（越小越倾向合并）
SPK_DISTANCE_THRESHOLD = float(os.environ.get("ASR_SPK_THRESHOLD", "0.5"))
# 轮次合并的最大间隔(ms)：同说话人相邻句间隔超过它就不再并入同一轮
TURN_MAX_GAP_MS = int(os.environ.get("ASR_TURN_GAP_MS", "1500"))
# 热词：默认开启但**词表要短**（实测短表可改善远场场景：20.1%→11.7%，且不伤其他场景；
# 过长的表会因解码偏置导致循环/丢字）。可用 ASR_HOTWORDS 覆盖，或用 ASR_HOTWORDS_ENABLED=0 关闭。
# 注：原默认词表（智聆 智聆云 李响 Tom）已过时废弃（2026-10），默认置空；
#     机制保留，需要时按请求传 hotword 或设置 ASR_HOTWORDS 即可。
HOTWORDS_ENABLED = os.environ.get("ASR_HOTWORDS_ENABLED", "1") == "1"
DEFAULT_HOTWORDS = os.environ.get("ASR_HOTWORDS", "")
# SenseVoice 完整性护栏：字数/语音秒 低于该阈值 → 自动回退 Paraformer
SV_MIN_CPS = float(os.environ.get("ASR_SV_MIN_CPS", "2.5"))
# SenseVoice 疑似漏识别时是否自动回退 Paraformer（回退=同一分片双倍推理耗时）。
# 默认关闭：会议/门店场景正常语速几乎不触发漏识别，回退得不偿失。开启：ASR_SV_FALLBACK=1
SV_FALLBACK = os.environ.get("ASR_SV_FALLBACK", "0") in ("1", "true", "True")
# GPU 上启用 FP16 推理。注意：实测本机 Paraformer-large 强制 fp16 会输出空结果
# （推理变快 rtf 0.24→0.14 但识别文本为空，疑似 fp32 模型数值塌缩），故默认关闭。
# 如需再试：ASR_FP16=1
FP16 = os.environ.get("ASR_FP16", "0") in ("1", "true", "True")
# 每个分片用独立子进程处理：规避进程级 CUDA 状态漂移（结果更稳定），代价是每片多一次模型加载
SUBPROCESS_PER_CHUNK = os.environ.get("ASR_SUBPROCESS", "1") == "1"
# 常驻推理进程池（默认开启，优先级高于 SUBPROCESS_PER_CHUNK）：每个分片不再临时 fork
# 子进程重复加载整套模型，而是提交到常驻进程池，每个池进程仅加载一次模型、反复取分片推理。
# INFER_PROCESSES 控制并发进程数（= 并发推理数）；多卡/大显存可调高。关闭：ASR_INFER_POOL=0
INFER_POOL = os.environ.get("ASR_INFER_POOL", "1") == "1"
INFER_PROCESSES = int(os.environ.get("ASR_INFER_PROCESSES", "1"))
# ITN（中文数字/金额/百分比规整）
ITN_ENABLED = os.environ.get("ASR_ITN", "1") == "1"
# 后台 worker 线程数（GPU 单卡建议 1）
MAX_WORKERS = int(os.environ.get("ASR_WORKERS", "1"))

# ---- 分片失败容错：自动重试 + 子分片兜底（FR-18）----
# 单片失败后的自动重试次数（不含首次尝试）。达到上限仍失败再走切分/放弃
MAX_CHUNK_RETRY = int(os.environ.get("ASR_CHUNK_RETRY", "2"))
# 自动重试的指数退避基数（秒），第 k 次重试等待 base*(2**k)，上限 30s
CHUNK_RETRY_BASE_DELAY = float(os.environ.get("ASR_CHUNK_RETRY_DELAY", "2.0"))
# 超过重试上限后，是否把仍失败且足够大的分片对半切，子分片下一轮再处理
CHUNK_SPLIT_ON_FAIL = os.environ.get("ASR_CHUNK_SPLIT", "1") == "1"
# 分片时长小于该值（毫秒）则不再切分，直接判失败，避免无限细分
CHUNK_MIN_SPLIT_MS = int(os.environ.get("ASR_CHUNK_MIN_SPLIT_MS", "60000"))

# 上传
ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".amr", ".wma", ".mp4", ".mkv"}
MAX_UPLOAD_BYTES = int(os.environ.get("ASR_MAX_UPLOAD_MB", "4096")) * 1024 * 1024  # 默认 4GB

# 是否保留上传原始文件
KEEP_ORIGINAL = os.environ.get("ASR_KEEP_ORIGINAL", "1") == "1"

# ---- AI Gateway（文本总结 / 历史语义检索 用）----
# OpenAI 兼容模型网关，用于纪要生成 / AI 问答 / 语义检索。
# 默认值为空：启动后请在 Web 界面「设置 → AI 服务」中填写网关地址与密钥
# （配置持久化在 data/runtime_settings.json，改后即时生效，无需重启），
# 或用环境变量 ASR_GATEWAY_URL / ASR_GATEWAY_TOKEN 预置。
# 自部署参考：Xinference / vLLM / Ollama（OpenAI 兼容端点）或任意云厂商兼容 API。
GATEWAY_URL = os.environ.get("ASR_GATEWAY_URL", "")
GATEWAY_TOKEN = os.environ.get("ASR_GATEWAY_TOKEN", "")
GATEWAY_EMBED_MODEL = os.environ.get("ASR_EMBED_MODEL", "bge-m3")
GATEWAY_RERANK_MODEL = os.environ.get("ASR_RERANK_MODEL", "bge-reranker-v2-m3")
GATEWAY_LLM_MODEL = os.environ.get("ASR_LLM_MODEL", "qwen2.5-7b-instruct")
GATEWAY_TIMEOUT = float(os.environ.get("ASR_GATEWAY_TIMEOUT", "300"))
# rerank 专用超时：避免精排慢响应阻塞整个检索请求（默认 20s）
GATEWAY_RERANK_TIMEOUT = float(os.environ.get("ASR_RERANK_TIMEOUT", "20"))

# ---- API 鉴权与租户隔离（FR-31 / FR-08，opt-in）----
# 配置 ASR_API_KEYS 后，所有 /api 请求需带 "Authorization: Bearer <secret>"；
# 未配置则保持现状（不鉴权，向后兼容）。格式：逗号分隔，每项 "tenant:secret"
# 或仅 "secret"（归到默认租户 ""）；特例 "*:secret" 为管理员密钥，可见全部租户数据。
API_KEYS = [k.strip() for k in os.environ.get("ASR_API_KEYS", "").split(",") if k.strip()]

def _parse_api_keys():
    m = {}
    for k in API_KEYS:
        if ":" in k:
            t, s = k.split(":", 1)
            m[s.strip()] = t.strip()
        else:
            m[k] = ""
    return m

API_KEY_TENANTS = _parse_api_keys()  # secret -> tenant

# 媒体下载签名（FR-05，opt-in）：设置 ASR_MEDIA_SIGN_SECRET 后 /media 需带签名 token
MEDIA_SIGN_SECRET = os.environ.get("ASR_MEDIA_SIGN_SECRET", "")
MEDIA_SIGN_TTL = int(os.environ.get("ASR_MEDIA_SIGN_TTL", "3600"))

# ---- 租户级限流 / 配额（FR-08，opt-in，需先启用 ASR_API_KEYS）----
# JSON 映射：tenant -> {"max_concurrent": 并发任务数, "daily_seconds": 日处理时长配额(秒)}
# 通配键 "*" 作为未显式配置租户的默认限额；管理员/共享租户("") 始终不限。
# 例：'{"acme":{"max_concurrent":2,"daily_seconds":36000},"*":{"max_concurrent":10,"daily_seconds":864000}}'
TENANT_LIMITS = {}
_raw_limits = os.environ.get("ASR_TENANT_LIMITS", "")
if _raw_limits:
    try:
        TENANT_LIMITS = json.loads(_raw_limits)
    except Exception:
        print("[config] ASR_TENANT_LIMITS 解析失败，忽略限流配置: %r" % _raw_limits, flush=True)
        TENANT_LIMITS = {}


def ensure_dirs():
    for d in (DATA_DIR, UPLOAD_DIR, AUDIO_DIR, RESULT_DIR):
        os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
