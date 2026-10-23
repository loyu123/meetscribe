"""Q4：检索召回回归集（recall@5 / MRR）。

固定语料 + 固定查询集，直接跑 search() 全链路（网关未配置时自动退化为 BM25），
用于在改动分词/_K1/_B/RRF/rerank 融合逻辑后及时发现召回劣化。
"""
import re

import search
import store

RIDS = ("rq4-a", "rq4-b")

CORPUS = [
    # (rid, speaker, date, start_ms, text)
    ("rq4-a", "1", "2026-03-05", 0, "张伟说下周一交付验收报告，风险是把控测试时间"),
    ("rq4-a", "1", "2026-03-05", 2000, "合同金额是3.5万元，含三年维护"),
    ("rq4-a", "2", "2026-03-05", 4000, "采购型号XT-2000共三台，XT-3000两台备用"),
    ("rq4-a", "2", "2026-03-05", 6000, "阿里巴巴集团的对接人是李娜"),
    ("rq4-a", "3", "2026-03-05", 8000, "覃雨薇负责前端联调，谭宇薇负责后端"),
    ("rq4-a", "3", "2026-03-05", 10000, "客户担心数据迁移会丢字段"),
    ("rq4-a", "1", "2026-03-05", 12000, "预算超支的部分需要财务复核"),
    ("rq4-a", "2", "2026-03-05", 14000, "上线时间定在4月15日，灰度10%"),
    ("rq4-b", "1", "2026-03-08", 0, "这次会议确认了三个待办事项"),
    ("rq4-b", "2", "2026-03-08", 2000, "报价单已发给采购部王经理"),
    ("rq4-b", "2", "2026-03-08", 4000, "测试覆盖率目标是80%"),
    ("rq4-b", "1", "2026-03-08", 6000, "下一版把导出改成PDF"),
    ("rq4-b", "3", "2026-03-08", 8000, "服务器扩容到32核128G"),
    ("rq4-b", "3", "2026-03-08", 10000, "语音识别模型换成Paraformer"),
    ("rq4-b", "1", "2026-03-08", 12000, "会议纪要需要包含风险与决策"),
]

# (query, 期望命中的片段特征)
CASES = [
    ("张伟 交付", "交付验收报告"),
    ("合同金额", "合同金额是3.5万元"),
    ("XT-2000", "XT-2000共三台"),
    ("李娜", "对接人是李娜"),
    ("覃雨薇", "覃雨薇负责前端"),
    ("数据迁移", "数据迁移会丢字段"),
    ("预算 超支", "预算超支"),
    ("灰度", "灰度10%"),
    ("待办事项", "三个待办事项"),
    ("王经理", "采购部王经理"),
    ("测试覆盖率", "覆盖率目标是80%"),
    ("PDF", "导出改成PDF"),
    ("32核", "32核128G"),
    ("Paraformer", "换成Paraformer"),
    ("决策", "包含风险与决策"),
]

MIN_RECALL = 0.95
MIN_MRR = 0.85


def _seed():
    search.init_search_db()
    with store.conn() as c:
        for rid in RIDS:
            c.execute("DELETE FROM search_chunks WHERE recording_id=?", (rid,))
            c.execute("DELETE FROM recordings WHERE id=?", (rid,))
        c.execute("INSERT INTO recordings(id,filename,status,created_at) "
                  "VALUES('rq4-a','产品评审.mp3','done','2026-03-05 09:00:00')")
        c.execute("INSERT INTO recordings(id,filename,status,created_at) "
                  "VALUES('rq4-b','客户访谈.mp3','done','2026-03-08 14:00:00')")
        for rid, spk, date, start, text in CORPUS:
            c.execute("INSERT INTO search_chunks(recording_id, speaker, date, start_ms, end_ms, "
                      "text, search_text, created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (rid, spk, date, start, start + 1800, text, text, "2026-03-09 00:00:00"))


def _drop():
    with store.conn() as c:
        for rid in RIDS:
            c.execute("DELETE FROM search_chunks WHERE recording_id=?", (rid,))
            c.execute("DELETE FROM recordings WHERE id=?", (rid,))


def test_recall_at_5_and_mrr(db):
    _seed()
    try:
        assert len(search._load_chunks({"recording_ids": list(RIDS)})) == len(CORPUS), "种子数据未写入"
        ranks = []
        misses = []
        for q, marker in CASES:
            body = search.search(q, {"recording_ids": list(RIDS)}, page=1, page_size=5)
            # 高亮会用 <mark> 包裹命中词，比对前先去掉标签，否则长标记会被拆开
            hits = [re.sub(r"</?mark>", "", r["snippet"]) for r in body["results"]]
            pos = next((i + 1 for i, s in enumerate(hits) if marker in s), None)
            ranks.append(pos)
            if pos is None:
                misses.append(q)
        recall = sum(1 for r in ranks if r) / len(ranks)
        mrr = sum(1.0 / r for r in ranks if r) / len(ranks)
        assert recall >= MIN_RECALL, "recall@5=%.3f 未命中=%s 全部排名=%s" % (recall, misses, ranks)
        assert mrr >= MIN_MRR, "MRR=%.3f 排名=%s" % (mrr, ranks)
    finally:
        _drop()


def test_unknown_proper_noun_has_no_hits(db):
    """语料里不存在的人名不应产生命中（防止 bigram 误召回）。"""
    _seed()
    try:
        body = search.search("周杰伦", {"recording_ids": list(RIDS)}, page_size=5)
        assert body["total"] == 0
    finally:
        _drop()
