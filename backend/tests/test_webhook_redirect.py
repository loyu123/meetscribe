"""S1：webhook 重定向 SSRF 防护——手动跟随一次并对 Location 复检。"""
import store
import worker


class _Resp:
    def __init__(self, status, location=None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}


def _capture(monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append({"url": url, "kw": kw})
        return _Resp(200)

    monkeypatch.setattr(worker.requests, "post", fake_post)
    return calls


def test_no_redirect_followed_by_default(monkeypatch, db):
    """普通 200：只发一次请求，且 allow_redirects=False。"""
    calls = _capture(monkeypatch)
    worker._notify("http://example.com/cb", {"x": 1}, "j1")
    assert len(calls) == 1
    assert calls[0]["kw"]["allow_redirects"] is False


def test_redirect_to_private_blocked(monkeypatch, db):
    """302 → 内网：不得发起第二次请求，并写 webhook_blocked 事件。"""
    calls = _capture(monkeypatch)

    def fake_post(url, **kw):
        calls.append({"url": url, "kw": kw})
        if url == "http://example.com/cb":
            return _Resp(302, "http://127.0.0.1:9200/steal")
        return _Resp(200)

    monkeypatch.setattr(worker.requests, "post", fake_post)
    worker._notify("http://example.com/cb", {"x": 1}, "j-ssrf")
    assert [c["url"] for c in calls] == ["http://example.com/cb"]  # 未跟随
    kinds = [e["kind"] for e in store.job_events("j-ssrf")]
    assert "webhook_blocked" in kinds


def test_redirect_to_public_followed_once(monkeypatch, db):
    """302 → 公网：允许跟随一次，且第二次请求同样 allow_redirects=False。"""
    def fake_post(url, **kw):
        calls.append({"url": url, "kw": kw})
        if url == "http://example.com/cb":
            return _Resp(302, "https://example.com/cb2")
        return _Resp(200)

    calls = []
    monkeypatch.setattr(worker.requests, "post", fake_post)
    worker._notify("http://example.com/cb", {"x": 1}, "j-ok")
    assert [c["url"] for c in calls] == ["http://example.com/cb", "https://example.com/cb2"]
    assert calls[1]["kw"]["allow_redirects"] is False  # 第二跳也不自动跟随
    kinds = [e["kind"] for e in store.job_events("j-ok")]
    assert "webhook_redirect" in kinds and "webhook_ok" in kinds


def test_redirect_chain_not_followed(monkeypatch, db):
    """第二跳再 302：不再跟随（只允许一跳）。"""
    def fake_post(url, **kw):
        calls.append({"url": url, "kw": kw})
        if url == "http://example.com/cb":
            return _Resp(302, "https://example.com/b")
        return _Resp(302, "https://example.com/c")

    calls = []
    monkeypatch.setattr(worker.requests, "post", fake_post)
    worker._notify("http://example.com/cb", {"x": 1}, "j-chain")
    assert len(calls) == 2  # 首跳 + 手动一跳，第二跳的 302 被忽略


def test_invalid_first_url_blocked(monkeypatch, db):
    """首跳 URL 本身非法/私网：连请求都不发。"""
    calls = _capture(monkeypatch)
    worker._notify("http://10.0.0.5/cb", {"x": 1}, "j2")
    assert calls == []
    kinds = [e["kind"] for e in store.job_events("j2")]
    assert "webhook_blocked" in kinds
