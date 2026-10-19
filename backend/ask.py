"""AI 问答：基于单段或多段会议转写，用 LLM 回答用户问题。

设计：
- 提供 answer(rids, question, history) 纯函数，组装“转写全文 + 历史对话 + 当前问题”后调 gw.chat。
- 支持单录音（屏④/屏⑤ 右栏）与跨录音（工作台右栏，取最近若干已完成录音）。
- 转写文本截断到 MAX_CTX_CHARS，避免超出模型上下文；答案里鼓励引用 [mm:ss]。
"""
import json
import os

import config
import store
import gateway_client as gw

MAX_CTX_CHARS = 14000

_SYSTEM = (
    "你是「聆语会议」的会议纪要问答助手。下面提供了一段或多段会议转写的全文。"
    "请严格基于转写内容回答用户的问题；如果转写中没有相关信息，请明确说明“转写中未提及”，"
    "不要编造。回答尽量引用原话，并在可能时标注对应的 [mm:ss] 时间戳。保持简洁、准确、口语化。"
    "输出纯文本：不要使用任何 Markdown 标记（如 ** 加粗、- 或 * 列表符、# 标题、` 代码引号），"
    "列表项直接一行一条地写，用普通文字与标点分隔即可。"
)


def _load_text(rid):
    rec = store.get_recording(rid)
    if not rec:
        return None
    if rec.get("tenant_id") and config.MEDIA_SIGN_SECRET:
        pass  # 租户隔离在路由层统一处理
    job = store.get_job_by_recording(rid)
    text = ""
    if job and job.get("result_path") and os.path.isfile(job["result_path"]):
        try:
            with open(job["result_path"], "r", encoding="utf-8") as f:
                res = json.load(f)
            text = res.get("text") or ""
        except Exception:  # noqa: BLE001
            text = ""
    return {"filename": rec.get("filename", rid), "text": text}


def answer(rids, question, history=None):
    blocks = []
    used = []
    for rid in rids:
        c = _load_text(rid)
        if c and c["text"].strip():
            blocks.append("【会议文件：%s】\n%s" % (c["filename"], c["text"].strip()))
            used.append(rid)
    ctx = "\n\n".join(blocks)
    if len(ctx) > MAX_CTX_CHARS:
        ctx = ctx[:MAX_CTX_CHARS] + "\n…（转写过长已截断）"

    messages = [{"role": "system", "content": _SYSTEM}]
    if ctx:
        messages.append({"role": "user", "content": "<会议转写>\n%s\n</会议转写>" % ctx})
    for h in (history or []):
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": str(h["content"])})
    messages.append({"role": "user", "content": question})

    ans = gw.chat(messages, temperature=1, max_tokens=4096)
    return ans, used
