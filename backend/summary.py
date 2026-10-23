"""文本总结模块（对应需求 FR-19~FR-24）。

基于转写 segments（含说话人、时间戳）调用网关 LLM 生成结构化摘要：
  - FR-19 模板：会议纪要 / 单人备忘，固定 JSON 结构
  - FR-20 超长文本：分段摘要 + 层级归并，保留要点
  - FR-21 溯源：每个要点附带说话人 + 音频时间戳(mm:ss)
  - FR-22 无依据不输出：仅基于提供的转写，未提及字段留空
  - FR-24 版本：留存模型名与摘要版本，便于重算

注：推理类模型（思考链消耗 token）建议放大 max_tokens 与超时；
本模块对"空响应/解析失败"做有限重试以提高稳定性。
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import config
import polish
import store
import gateway_client as gw

SUMMARY_VERSION = "v1"
CHUNK_CHARS = 6000  # 单次送 LLM 的转写字符上限，超则分段归并(FR-20)
LLM_TRIES = 2       # LLM 空响应/解析失败的本地重试次数
LLM_MAX_TOKENS = 24000  # 推理模型思考链消耗大量 token，
                        # 若沿用网关默认 6144 会被思考耗尽、final content 为空 → “空响应”
LLM_MAX_TOKENS_CAP = 32000  # 发生长度截断时重试的额度上限（逐次翻倍，不超过此值）


def _fmt_ts(ms):
    ms = ms or 0
    s = int(ms) // 1000
    return "%02d:%02d" % (s // 60, s % 60)


def _line(s):
    spk = s.get("global_spk")
    label = ("说话人%d" % spk) if spk is not None else "未知说话人"
    return "[%s @ %s] %s" % (label, _fmt_ts(s.get("start_ms")), s.get("text", ""))


def build_context(segments):
    """把 segments 拼成带说话人/时间戳标记的文本（供 LLM 溯源，FR-21）。"""
    return "\n".join(_line(s) for s in segments)


def _chunk_context(segments):
    """按字符上限切分上下文，返回多段字符串（FR-20）。"""
    chunks, cur, cur_len = [], [], 0
    for s in segments:
        line = _line(s)
        if cur and cur_len + len(line) + 1 > CHUNK_CHARS:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def _schema_hint(template):
    if template == "memo":
        return ('输出 JSON，结构严格如下（不要多余字段，未提及留空字符串或空数组）：\n'
                '{"owner":"谁的单人备忘(若可推断)","one_line":"一句话总结",'
                '"points":[{"content":"要点","speaker":"说话人","timestamp":"mm:ss"}],'
                '"todos":[{"task":"待办","owner":"责任人","deadline":"截止时间"}]}')
    return ('输出 JSON，结构严格如下（不要多余字段，未提及留空字符串或空数组）：\n'
            '{"title":"会议主题","attendees":["参与人"],"one_line":"一句话总结",'
            '"points":[{"content":"要点","speaker":"说话人","timestamp":"mm:ss"}],'
            '"action_items":[{"task":"行动项","owner":"责任人","deadline":"截止时间"}],'
            '"risks":[{"content":"风险/问题","level":"高/中/低"}]}')


def _custom_schema_hint(tpl):
    """自定义模板：按模板章节生成 sections 分组结构。"""
    opts = tpl.get("opts") or {}
    sections = tpl.get("sections") or []
    lines = "\n".join(
        "- %s：%s" % (s.get("title", ""), s.get("hint") or "从录音中提取该节相关的关键信息。")
        for s in sections
    )
    schema = ('{"one_line":"一句话总结",'
              '"sections":{' + ",".join('"%s":[]' % s.get("title", "") for s in sections) + '}')
    if opts.get("todos", 1):
        schema += (',"todos":[{"task":"待办","owner":"责任人","deadline":"截止时间"}]')
    hint = ('输出 JSON，结构严格如下（不要多余字段，未提及留空字符串或空数组）：\n' + schema + '\n'
            "sections 的每个键对应模板章节，值为要点数组，元素结构："
            '{"content":"要点内容","speaker":"说话人","timestamp":"mm:ss"}。\n'
            "每个要点必须归入最匹配的章节，不得遗漏章节键。章节提取要求：\n" + lines)
    if not opts.get("timestamps", 1):
        hint += "\n本模板不需要时间戳，timestamp 统一输出空字符串。"
    if opts.get("formal", 0):
        hint += "\n表达要求：书面化、简练、去除语气词。"
    return hint


def _schema_for(template):
    """按模板 id 分发 schema：内置走固定结构，自定义读 templates 表。"""
    if template in ("meeting", "memo"):
        return _schema_hint(template)
    tpl = store.get_template(template)
    if tpl:
        return _custom_schema_hint(tpl)
    return _schema_hint("meeting")


def _system_prompt(template):
    base = ("你是专业的会议内容总结助手。下面会给你一段[说话人 @ mm:ss]标记的会议转写文本。"
            "请仅依据文本内容进行总结，严禁编造文本中未出现的人名、数据、结论"
            "（FR-22 无依据不输出）；无法确定的字段留空。"
            "每个要点必须尽量附带其来源说话人与时间戳(mm:ss)，以便溯源跳转(FR-21)。"
            "只输出要求的 JSON，不要任何解释性文字。")
    return base + "\n" + _schema_for(template)


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```", 2)
        text = parts[1] if len(parts) > 1 else text
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 未返回 JSON: " + text[:200])
    return json.loads(text[start:end + 1])


def _chat_json(system_content, user_content):
    """调用 LLM 并解析 JSON。

    重试策略（最多 LLM_TRIES 次）：
      - 因 max_tokens 截断（GatewayError, finish_reason=length）→ 放大额度后重试；
      - 返回空串或 JSON 解析失败 → 重试。
    推理模型思考链偶发耗尽额度，故每次重试递增 max_tokens，避免原样重发必然再失败。
    """
    last_err = None
    max_tokens = LLM_MAX_TOKENS
    for _ in range(LLM_TRIES):
        try:
            raw = gw.chat([
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ], temperature=1, max_tokens=max_tokens)
        except gw.GatewayError as e:
            last_err = e
            max_tokens = min(max_tokens * 2, LLM_MAX_TOKENS_CAP)
            time.sleep(1)
            continue
        if raw and raw.strip():
            try:
                return _parse_json(raw)
            except ValueError as e:
                last_err = e
        max_tokens = min(max_tokens * 2, LLM_MAX_TOKENS_CAP)
        time.sleep(1)
    if last_err:
        raise last_err
    raise ValueError("LLM 未返回 JSON(空响应)")


# ---------------- P1-2 长会议纪要质量增强 ----------------
_COARSE_SYS = ('你是会议总结助手。下面是一份超长会议转写的各片段开头/结尾节选。'
               '请输出全局粗摘要 JSON：{"overall_topic":"会议主线主题",'
               '"key_threads":["贯穿会议的主要线索/议题(3~8条)"],'
               '"conclusions":["会议后段出现的结论/决定"]}。仅基于内容，不编造。')


def _coarse_digest(chunks):
    """每块取头尾节选拼成全局视角输入（控制 token 量，会议结论多在后段）。"""
    parts = []
    for i, c in enumerate(chunks):
        head = c[:800]
        tail = c[-400:] if len(c) > 1200 else ""
        parts.append("[片段 %d]\n%s%s" % (i + 1, head, ("\n…\n" + tail) if tail else ""))
    return "\n\n".join(parts)


def _validate_summary(data, template):
    """输出结构校验（P1-2）：必填字段缺失/类型错误返回问题描述，正常返回 None。"""
    if not isinstance(data, dict):
        return "输出必须是 JSON 对象"
    if isinstance(data.get("sections"), dict):  # 自定义模板
        return None if data["sections"] else "sections 不能为空"
    need = ["one_line", "points"] if template == "memo" else ["title", "one_line", "points"]
    missing = [k for k in need if k not in data]
    if missing:
        return "缺少字段: %s" % ",".join(missing)
    if not isinstance(data.get("points"), list):
        return "points 必须是数组"
    return None


def summarize(recording_id, template="meeting"):
    """生成并持久化摘要。返回附带 _id/_model/_version 的内容字典。"""
    rec = store.get_recording(recording_id)
    if not rec:
        raise ValueError("录音不存在")
    job = store.get_job_by_recording(recording_id)
    if not job:
        raise ValueError("任务不存在")
    segments = store.get_segments(job["id"])
    segs = []
    for s in segments:
        if s.get("need_review"):  # FR-17 低置信度不进总结
            continue
        t = polish.clean_sentence(s.get("text", ""))  # 口语顺滑后再交给 LLM
        if t:
            x = dict(s)
            x["text"] = t
            segs.append(x)
    if not segs:
        raise ValueError("无可用转写片段（可能全部低置信度或仅为语气词）")

    sys_p = _system_prompt(template)
    chunks = _chunk_context(segs)
    if len(chunks) == 1:
        data = _chat_json(sys_p, "会议转写如下：\n" + chunks[0])
    else:  # FR-20 + P1-2：全局粗摘要 → 分块并行摘要 → 以粗摘要为上下文归并，减少重复与主线丢失
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as ex:
            partials = list(ex.map(
                lambda c: _chat_json(sys_p, "会议转写如下：\n" + c), chunks))
        try:
            coarse = _chat_json(_COARSE_SYS, _coarse_digest(chunks))
        except Exception as e:  # noqa: BLE001 粗摘要失败不阻塞，退回纯归并
            print("[summary] 全局粗摘要失败，退回纯归并: %r" % e, flush=True)
            coarse = None
        merge_sys = ("你是会议总结助手。下面是多段会议转写的分段摘要(JSON数组)，"
                     "请合并去重，输出最终统一的结构化摘要(同一JSON结构)，"
                     "保留每个要点的说话人与时间戳；仅基于提供内容，不编造。")
        merge_user = "分段摘要：\n" + json.dumps(partials, ensure_ascii=False)
        if coarse:
            merge_user = ("全局粗摘要（仅供把握会议主线，不得引入分段摘要中未出现的具体信息）：\n"
                          + json.dumps(coarse, ensure_ascii=False) + "\n\n" + merge_user)
        data = _chat_json(merge_sys + "\n" + _schema_for(template), merge_user)

    # P1-2 输出校验：必填字段缺失时尝试一次补全重试；仍失败保留原结果（FR-24 不阻塞）
    err = _validate_summary(data, template)
    if err:
        print("[summary] 结构校验未通过(%s)，尝试补全重试" % err, flush=True)
        try:
            fixed = _chat_json(
                sys_p + "\n结构校验问题：%s。请补全所有必填字段后重新输出完整 JSON"
                        "（保留原内容，只补结构），不要任何解释。" % err,
                "你上次的输出：\n" + json.dumps(data, ensure_ascii=False))
            if not _validate_summary(fixed, template):
                data = fixed
        except Exception as e:  # noqa: BLE001
            print("[summary] 结构补全重试失败: %r" % e, flush=True)

    sid = store.save_summary(recording_id, job["id"], template,
                             config.GATEWAY_LLM_MODEL, SUMMARY_VERSION, data,
                             tenant_id=rec.get("tenant_id") or "")
    data["_id"] = sid
    data["_model"] = config.GATEWAY_LLM_MODEL
    data["_version"] = SUMMARY_VERSION
    return data


# ---------------- 要点主题智能分组（FR-19 展示增强） ----------------

_GROUP_SYSTEM = ("你是会议纪要整理助手。只输出 JSON，不要输出任何解释或多余字段；"
                 "严格基于给定的要点列表做分组，不得编造或改写要点内容。")


def group_points(points):
    """把纪要要点按主题智能分组（LLM）。

    points: [{"content": str, "speaker": str|None, "timestamp": str|None}, ...]
    返回: [{"title": 主题名, "idx": [要点原始下标...]}, ...]，未覆盖的要点并入「其他」。
    """
    lines = []
    for i, p in enumerate(points):
        meta = [str(p[k]) for k in ("speaker", "timestamp") if p.get(k)]
        body = (p.get("content") or "").strip()
        lines.append("%d. %s%s" % (i, body, ("（%s）" % " · ".join(meta)) if meta else ""))

    user = ("下面是会议纪要的要点列表（行首编号为下标）。请按主题把它们分成 2~5 组，"
            "主题名简短贴切（如「进度与联调」「商务与报价」「问题与风险」）；"
            "每个下标必须恰好归入一组，不得遗漏或重复。\n\n"
            + "\n".join(lines)
            + '\n\n输出 JSON：{"groups":[{"title":"主题名","idx":[0,1,2]}]}')

    data = _chat_json(_GROUP_SYSTEM, user)
    groups, used = [], set()
    for g in data.get("groups", []) if isinstance(data, dict) else []:
        idx = []
        for x in (g.get("idx") or []):
            try:
                xi = int(x)
            except (TypeError, ValueError):
                continue
            if 0 <= xi < len(points) and xi not in used:
                idx.append(xi)
                used.add(xi)
        title = (str(g.get("title") or "").strip() or "未分类")
        if idx:
            groups.append({"title": title, "idx": idx})
    rest = [i for i in range(len(points)) if i not in used]
    if rest:
        groups.append({"title": "其他", "idx": rest})
    return groups
