"""检索分词（B1 bigram）单元测试。"""
from search import _tokenize


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
