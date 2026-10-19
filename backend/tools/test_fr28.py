"""FR-28 跨语言检索实测：中文查询(对照) vs 英文查询(跨语言) 的 recall@5 / MRR。
内容均为中文，用英文提问能命中对应录音即证明跨语言检索有效。"""
import store, search

# 按文件名前缀解析录音 id，避免硬编码
recs = {r["filename"]: r["id"] for r in store.list_recordings(limit=1000)}


def rid_of(sub):
    for fn, rid in recs.items():
        if sub in fn:
            return rid
    raise KeyError(sub)


R_OFFICE = rid_of("long_audio_1h_office")          # sprint/QPS 办公长音频
R_WEEKLY = rid_of("语音Demo_01_部门周会")            # 同一批 sprint/QPS 周会
R_MARKET = rid_of("AISHELL4_会议")                 # 超市经营会议
R_MARKET2 = rid_of("AISHELL4_S_R004S03C01")        # 同上（另一份）
R_REVIEW = rid_of("语音Demo_03_项目复盘会")          # 项目复盘/延期
R_PRESALE = rid_of("语音Demo_02_客户售前通话")       # 客户售前/报价
R_SITE = rid_of("语音Demo_04_现场沟通")             # 现场设备安装

# (语言, 查询, 可接受录音集合)
PAIRS = [
    ("ZH", "压测数据 峰值 QPS 还差一点", {R_OFFICE, R_WEEKLY}),
    ("EN", "load testing peak QPS still a bit short", {R_OFFICE, R_WEEKLY}),
    ("ZH", "超市 客流量 营业额 销售比例", {R_MARKET, R_MARKET2}),
    ("EN", "supermarket customer traffic and sales revenue", {R_MARKET, R_MARKET2}),
    ("ZH", "项目延期 复盘 action item 上线", {R_REVIEW}),
    ("EN", "project delay postmortem action items go-live", {R_REVIEW}),
    ("ZH", "客户售前 报价 折扣 赔付 方案", {R_PRESALE}),
    ("EN", "customer presales quotation discount refund proposal", {R_PRESALE}),
    ("ZH", "设备安装 水晶头 网线 点位", {R_SITE}),
    ("EN", "equipment installation network cable RJ45 connector", {R_SITE}),
]

K = 5
rows = []
for lang, q, expected in PAIRS:
    res = search.search(q, {}, 1, K)
    got = [x["recording_id"] for x in res["results"]]
    rank = next((i + 1 for i, r in enumerate(got) if r in expected), 0)
    rows.append((lang, q, rank))
    print("[%s] %-46s rank=%s top5=%s" % (lang, q[:46], rank or "MISS",
                                          [r[:8] for r in got]))

print()
for lang in ("ZH", "EN"):
    sub = [r for r in rows if r[0] == lang]
    recall = sum(1 for _, _, rk in sub if rk > 0) / len(sub)
    mrr = sum((1.0 / rk) for _, _, rk in sub if rk > 0) / len(sub)
    print("%s: recall@%d = %.2f  MRR = %.3f  (n=%d)" % (lang, K, recall, mrr, len(sub)))

zh = [r for r in rows if r[0] == "ZH"]
en = [r for r in rows if r[0] == "EN"]
zh_recall = sum(1 for _, _, rk in zh if rk > 0) / len(zh)
en_recall = sum(1 for _, _, rk in en if rk > 0) / len(en)
print()
print("跨语言(EN) recall 相对同语言(ZH) 保留率: %.0f%%" % (100 * en_recall / zh_recall if zh_recall else 0))
print("FR-28 判定:", "PASS" if en_recall >= 0.6 else ("PARTIAL" if en_recall > 0 else "FAIL"))
