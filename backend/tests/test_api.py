"""API 冒烟测试（匿名模式 + 鉴权开关）。"""
import config
import pytest


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
