"""API 冒烟测试（匿名模式 + 鉴权开关）。"""
import io
import json
from urllib.parse import quote

import config
import pytest

import store


def test_system_ok(client):
    r = client.get("/api/v1/system")
    assert r.status_code == 200
    body = r.get_json()
    assert "recordings" in body and "version" in body


def test_search_empty_query(client):
    r = client.post("/api/v1/search", json={"query": ""})
    assert r.status_code == 200
    body = r.get_json()
    assert body["results"] == []


def test_export_missing_recording_404(client):
    r = client.get("/api/v1/recordings/nonexistent/export?fmt=txt")
    assert r.status_code == 404
    # U3：错误体必须是可直接展示的中文原因（前端会读 error 字段弹提示）
    assert "不存在" in r.get_json()["error"]


def _seed_done_recording(tmp_path, rid="rid-exp", jid="jid-exp", with_result=True):
    """造 录音 + 已完成任务（可选写入结果 JSON），返回结果文件路径。"""
    rp = tmp_path / "result.json"
    if with_result:
        rp.write_text(json.dumps({"turns": [], "speakers": [], "text": "你好"}, ensure_ascii=False),
                      encoding="utf-8")
    store.init_db()
    with store.conn() as c:
        c.execute("DELETE FROM jobs WHERE recording_id=?", (rid,))
        c.execute("DELETE FROM recordings WHERE id=?", (rid,))
        c.execute("INSERT INTO recordings(id, filename, status, created_at) "
                  "VALUES(?, '产品评审.mp3', 'done', '2026-01-01 00:00:00')", (rid,))
        c.execute("INSERT INTO jobs(id, recording_id, status, result_path, created_at, updated_at) "
                  "VALUES(?, ?, 'done', ?, '2026-01-01 00:00:00', '2026-01-01 00:00:00')",
                  (jid, rid, str(rp) if with_result else None))
    return rid


def _drop_recording(rid="rid-exp"):
    with store.conn() as c:
        c.execute("DELETE FROM jobs WHERE recording_id=?", (rid,))
        c.execute("DELETE FROM recordings WHERE id=?", (rid,))


def test_export_without_result_is_readable(client, tmp_path):
    rid = _seed_done_recording(tmp_path, with_result=False)
    try:
        r = client.get("/api/v1/recordings/%s/export?fmt=txt" % rid)
        assert r.status_code == 400
        assert "转写" in r.get_json()["error"]
    finally:
        _drop_recording(rid)


def test_export_unsupported_format_is_readable(client, tmp_path):
    rid = _seed_done_recording(tmp_path)
    try:
        r = client.get("/api/v1/recordings/%s/export?fmt=pdf" % rid)
        assert r.status_code == 400
        msg = r.get_json()["error"]
        assert "不支持" in msg and "pdf" in msg
    finally:
        _drop_recording(rid)


def test_subtitle_unsupported_format_is_readable(client, tmp_path):
    rid = _seed_done_recording(tmp_path)
    try:
        r = client.get("/api/v1/recordings/%s/subtitle?fmt=txt" % rid)
        assert r.status_code == 400
        assert "不支持" in r.get_json()["error"]
    finally:
        _drop_recording(rid)


# ---------------- U4：导出文件名 / 元数据 ----------------
def test_export_filename_and_md_meta(client, tmp_path):
    rid = _seed_done_recording(tmp_path)
    try:
        r = client.get("/api/v1/recordings/%s/export?fmt=md" % rid)
        assert r.status_code == 200
        cd = r.headers["Content-Disposition"]
        assert ('filename="%s.md"' % rid) in cd  # ASCII 兜底
        assert quote("产品评审_20260101.md") in cd  # RFC5987 中文名
        body = r.get_data(as_text=True)
        assert "日期：2026-01-01" in body
        assert "录音文件：产品评审.mp3" in body
    finally:
        _drop_recording(rid)


def test_export_txt_filename(client, tmp_path):
    rid = _seed_done_recording(tmp_path)
    try:
        r = client.get("/api/v1/recordings/%s/export?fmt=txt" % rid)
        assert r.status_code == 200
        assert quote("产品评审_20260101.txt") in r.headers["Content-Disposition"]
    finally:
        _drop_recording(rid)


def test_subtitle_filename_readable(client, tmp_path):
    rid = _seed_done_recording(tmp_path)
    try:
        r = client.get("/api/v1/recordings/%s/subtitle?fmt=srt" % rid)
        assert r.status_code == 200
        assert quote("产品评审_20260101.srt") in r.headers["Content-Disposition"]
    finally:
        _drop_recording(rid)


def test_docx_has_document_properties(client, tmp_path):
    from docx import Document

    rid = _seed_done_recording(tmp_path)
    try:
        r = client.get("/api/v1/recordings/%s/export?fmt=docx" % rid)
        assert r.status_code == 200
        assert quote("产品评审_20260101.docx") in r.headers["Content-Disposition"]
        d = Document(io.BytesIO(r.data))
        assert d.core_properties.author == "MeetScribe"
        assert "MeetScribe" in (d.core_properties.comments or "")
        assert d.core_properties.title
    finally:
        _drop_recording(rid)


def test_voiceprint_requires_existing_result(client):
    r = client.post("/api/v1/voiceprints",
                    json={"recording_id": "nope", "spk": "0", "name": "张三"})
    assert r.status_code in (400, 404)


def test_metrics_admin_only_when_auth_on(client):
    prev = config.API_KEY_TENANTS
    try:
        config.API_KEY_TENANTS = {"sk-test-1": "t1", "sk-admin-1": "*"}  # secret -> tenant
        r = client.get("/api/v1/system/metrics")
        assert r.status_code == 401
        # 普通租户：认证通过但非管理员 → 403
        r = client.get("/api/v1/system/metrics",
                       headers={"Authorization": "Bearer sk-test-1"})
        assert r.status_code == 403
        # 管理员（*）→ 200
        r = client.get("/api/v1/system/metrics",
                       headers={"Authorization": "Bearer sk-admin-1"})
        assert r.status_code == 200
        # 普通租户访问全局网关设置 → 403
        r = client.get("/api/v1/settings",
                       headers={"Authorization": "Bearer sk-test-1"})
        assert r.status_code == 403
    finally:
        config.API_KEY_TENANTS = prev


def test_auth_anonymous_when_disabled(client):
    assert not config.API_KEY_TENANTS
    r = client.get("/api/v1/system")
    assert r.status_code == 200
