"""AI 网关运行时配置：允许在界面上查看/修改网关地址、密钥与模型名，无需改环境变量重启。

- 覆盖值持久化到 <DATA_DIR>/runtime_settings.json，启动时应用（环境变量仍可作初始默认）。
- gateway_client 每次调用都读 config.GATEWAY_* 属性，因此直接改 config 模块属性即可热生效。
- 密钥读取时做掩码处理，前端只在用户真正修改密钥时才回传新值。
"""
import json
import os
import urllib.request
import urllib.error

import config

_PATH = os.path.join(config.DATA_DIR, "runtime_settings.json")

# 允许通过界面修改的网关字段 -> config 模块属性
_KEYS = ("gateway_url", "gateway_token", "llm_model", "embed_model", "rerank_model")
_ATTR = {
    "gateway_url": "GATEWAY_URL",
    "gateway_token": "GATEWAY_TOKEN",
    "llm_model": "GATEWAY_LLM_MODEL",
    "embed_model": "GATEWAY_EMBED_MODEL",
    "rerank_model": "GATEWAY_RERANK_MODEL",
}


def _mask(token):
    if not token:
        return ""
    if len(token) <= 8:
        return "****"
    return token[:4] + "****" + token[-4:]


def _load_file():
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def apply_startup():
    """服务启动时把持久化的覆盖值应用到 config（环境变量优先级最低）。"""
    saved = _load_file()
    for k in _KEYS:
        v = saved.get(k)
        if v:
            setattr(config, _ATTR[k], str(v))


def get():
    """返回当前网关配置（密钥掩码）。token_set 表示是否已配置密钥。"""
    token = getattr(config, "GATEWAY_TOKEN", "")
    return {
        "gateway_url": getattr(config, "GATEWAY_URL", ""),
        "gateway_token_masked": _mask(token),
        "token_set": bool(token),
        "llm_model": getattr(config, "GATEWAY_LLM_MODEL", ""),
        "embed_model": getattr(config, "GATEWAY_EMBED_MODEL", ""),
        "rerank_model": getattr(config, "GATEWAY_RERANK_MODEL", ""),
    }


def update(payload):
    """更新网关配置。gateway_token 为空 / 掩码值 / 缺省时不改动现有密钥。"""
    saved = _load_file()
    changed = []
    for k in _KEYS:
        if k not in payload:
            continue
        v = str(payload.get(k) or "").strip()
        if k == "gateway_url":
            if not v:
                raise ValueError("网关地址不能为空")
            if not v.startswith(("http://", "https://")):
                raise ValueError("网关地址必须以 http:// 或 https:// 开头")
        if k == "gateway_token":
            # 空值或与掩码相同 -> 不修改
            if not v or v == _mask(getattr(config, "GATEWAY_TOKEN", "")):
                continue
        if k != "gateway_url" and not v:
            raise ValueError("模型名不能为空")
        cur = str(getattr(config, _ATTR[k], ""))
        if v == cur:
            continue
        setattr(config, _ATTR[k], v)
        saved[k] = v
        changed.append(k)
    if changed:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _PATH)
    return get(), changed


def test():
    """探测网关连通性：GET /models（OpenAI 兼容）。返回可用模型 id 列表。"""
    url = getattr(config, "GATEWAY_URL", "").rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + getattr(config, "GATEWAY_TOKEN", ""),
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError("HTTP %s: %s" % (e.code, body)) from e
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("连接失败: %r" % e) from e
    ids = []
    for m in data.get("data", []):
        mid = m.get("id") if isinstance(m, dict) else None
        if mid:
            ids.append(str(mid))
    return ids


apply_startup()
