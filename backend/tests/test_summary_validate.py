"""纪要输出结构校验（P1-2）单元测试。"""
from summary import _validate_summary


def test_meeting_ok():
    data = {"title": "t", "one_line": "o", "points": [], "action_items": [], "risks": []}
    assert _validate_summary(data, "meeting") is None


def test_meeting_missing_fields():
    err = _validate_summary({"title": "t", "points": []}, "meeting")
    assert err and "one_line" in err


def test_meeting_points_not_list():
    err = _validate_summary({"title": "t", "one_line": "o", "points": "x"}, "meeting")
    assert err and "points" in err


def test_memo_needs_one_line_and_points():
    assert _validate_summary({"one_line": "o", "points": []}, "memo") is None
    err = _validate_summary({"one_line": "o"}, "memo")
    assert err and "points" in err


def test_custom_template_sections():
    assert _validate_summary({"sections": {"要点": []}}, "custom") is None
    assert _validate_summary({"sections": {}}, "custom") is not None


def test_not_a_dict():
    assert _validate_summary([1, 2], "meeting") is not None
    assert _validate_summary("x", "meeting") is not None
