"""检索分词（B1 bigram）单元测试 + 专名/编号召回断言（Q3）。"""
from search import _bm25, _tokenize


def test_cjk_bigram():
    assert _tokenize("张伟说合同") == ["张伟", "伟说", "说合", "合同"]


def test_cjk_single_char_kept():
    assert _tokenize("好") == ["好"]


def test_latin_and_numbers():
    assert _tokenize("MeetScribe 2024 v2") == ["meetscribe", "2024", "v2"]


def test_mixed():
    toks = _tokenize("合同金额3.5万")
    assert "合同" in toks and "金额" in toks and "万" in toks
    assert "3" in toks and "5" in toks


def test_empty():
    assert _tokenize("") == []
    assert _tokenize(None) == []


# ---------------- Q3：专名 / 编号类查询 ----------------
def test_proper_noun_person_name_is_one_token():
    """两字人名必须整词成 token，否则「张伟」会被拆成单字而无区分度。"""
    assert _tokenize("张伟") == ["张伟"]


def test_proper_noun_org_keeps_key_bigram():
    toks = _tokenize("阿里巴巴集团")
    assert toks == ["阿里", "里巴", "巴巴", "巴集", "集团"]
    assert "集团" in toks


def test_proper_noun_in_sentence_keeps_token():
    """专名嵌在句子里时，仍应产生与查询侧完全相同的人名 token（两侧同构）。"""
    toks = _tokenize("张伟负责下周一交付")
    assert "张伟" in toks
    assert _tokenize("张伟") == ["张伟"]


def test_model_number_with_separator():
    """型号/编号：字母与数字各自成 token，连字符不作为 token 内容。"""
    assert _tokenize("XT-2000") == ["xt", "2000"]
    assert _tokenize("XT-2000") == _tokenize("xt 2000")  # 大小写/分隔符不影响口径


def test_amount_and_unit():
    toks = _tokenize("报价3.5万元")
    assert "3" in toks and "5" in toks
    assert "万元" in toks and "报价" in toks


def test_bm25_proper_noun_ranks_exact_chunk_first():
    """专名查询应命中含该专名的切块，且完全不命中字面相近但无该专名的切块。"""
    chunks = [
        {"id": 1, "search_text": "张伟说下周一交付验收报告"},
        {"id": 2, "search_text": "张三说合同条款没问题"},
    ]
    scores, ranked = _bm25(_tokenize("张伟"), chunks)
    assert ranked and ranked[0][0] == 1
    assert 2 not in scores


def test_bm25_model_number_recall():
    chunks = [
        {"id": 1, "search_text": "采购型号 XT-2000 共三台"},
        {"id": 2, "search_text": "采购型号 XT-3000 共两台"},
    ]
    scores, ranked = _bm25(_tokenize("XT-2000"), chunks)
    # 同品牌前缀只能拿到部分信号（xt），完整型号应显著排在前面
    assert ranked and ranked[0][0] == 1
    assert scores.get(2, 0.0) < scores[1]
