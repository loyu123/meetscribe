"""AI Gateway 客户端：封装 OpenAI 兼容模型网关的 Embedding / Rerank / Chat 调用。

功能对应：
  - 混合检索（向量召回 + BM25 + rerank）
  - 切块规范（块上携带说话人/时间戳/录音ID/日期）
  - 文本总结 / AI 问答（依赖 LLM chat）

网关为 OpenAI 兼容风格，鉴权用 Bearer Token。地址、密钥与模型名均可在
Web 界面「设置 → AI 服务」中配置（持久化于 data/runtime_settings.json），
也可用环境变量 ASR_GATEWAY_URL / ASR_GATEWAY_TOKEN 等预置。
自部署示例：Xinference / vLLM / Ollama（OpenAI 兼容端点）。
"""
import json
import urllib.request
import urllib.error

import config


class GatewayError(RuntimeError):
    pass


def _post(path, payload, timeout=None):
    if not (getattr(config, "GATEWAY_URL", "") or "").strip():
        raise GatewayError(
            "AI 网关未配置：请在 Web 界面「设置 → AI 服务（模型网关）」填写地址与密钥，"
            "或设置环境变量 ASR_GATEWAY_URL / ASR_GATEWAY_TOKEN 后重启服务")
    url = config.GATEWAY_URL.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": "Bearer " + config.GATEWAY_TOKEN,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            req, timeout=(timeout if timeout is not None else config.GATEWAY_TIMEOUT)
        ) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise GatewayError("HTTP %s: %s" % (e.code, body)) from e
    except Exception as e:  # noqa: BLE001
        raise GatewayError("网关调用失败: %r" % e) from e


def embed(texts):
    """文本向量化。texts 可为单条字符串或字符串列表，返回同形状的向量列表。

    用于 FR-26 切块后的向量化、FR-25 向量召回、以及查询句的向量化。
    """
    if isinstance(texts, str):
        single = True
        texts = [texts]
    else:
        single = False
    resp = _post("/embeddings", {"model": config.GATEWAY_EMBED_MODEL, "input": texts})
    # 兼容 OpenAI 结构 data[*].embedding；按 index 排序保证顺序
    items = sorted(resp.get("data", []), key=lambda x: x.get("index", 0))
    vecs = [it["embedding"] for it in items]
    if len(vecs) != len(texts):
        # 网关丢条/部分返回会导致向量与文本静默错位，必须显式失败
        raise GatewayError("embeddings 返回条数不匹配: %d/%d" % (len(vecs), len(texts)))
    return vecs[0] if single else vecs


def embed_dim():
    """探测向量维度（用于初始化向量库索引）。"""
    return len(embed("维度探测"))


def rerank(query, documents, top_n=None):
    """重排序。返回 [(index, relevance_score, text), ...] 按相关性降序。

    用于 FR-25：向量/BM25 粗召回后，用 rerank 精排提升命中精度。
    """
    payload = {
        "model": config.GATEWAY_RERANK_MODEL,
        "query": query,
        "documents": list(documents),
    }
    if top_n is not None:
        payload["top_n"] = top_n
    resp = _post("/rerank", payload, timeout=config.GATEWAY_RERANK_TIMEOUT)
    out = []
    for r in resp.get("results", []):
        doc = r.get("document", {})
        text = doc.get("text", "") if isinstance(doc, dict) else str(doc)
        out.append((r.get("index"), r.get("relevance_score", 0.0), text))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def chat(messages, temperature=1, max_tokens=6144):
    """调用 LLM 生成文本（用于 FR-19~FR-24 总结）。

    messages: [{"role":"system"/"user"/"assistant", "content": "..."}, ...]
    注意：部分推理模型仅允许 temperature=1，故默认值为 1；
    若换用其它模型可覆盖。

    健壮性：推理模型会把思考链放在 reasoning_content、正文放在
    content；当思考耗尽 max_tokens 时 content 为空且 finish_reason=length。
    这里区分处理：空 content 先尝试 reasoning_content 兜底；若确因长度截断
    则抛出明确错误（而非静默返回空串，让上层只报“空响应”而难以定位）。
    """
    resp = _post(
        "/chat/completions",
        {
            "model": config.GATEWAY_LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    choices = resp.get("choices") or []
    if not choices:
        raise GatewayError("网关返回无 choices: %r" % (str(resp)[:200],))
    choice = choices[0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    if not content.strip():
        # 兼容不同网关字段名：reasoning_content / reasoning
        content = msg.get("reasoning_content") or msg.get("reasoning") or ""
    finish = choice.get("finish_reason")
    if finish == "length" and not content.strip():
        raise GatewayError(
            "LLM 输出被 max_tokens=%s 截断(finish_reason=length)："
            "推理模型思考链耗尽额度，请提高 max_tokens" % max_tokens)
    return content


if __name__ == "__main__":
    print("dim:", embed_dim())
    print("embed[0][:3]:", embed("测试一句话")[:3])
    print("rerank:", rerank("什么是 AI Gateway？",
                            ["AI Gateway 用于统一管理模型调用。",
                             "数据库用于存储结构化数据。"]))
