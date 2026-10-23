"""SSRF 防护（A2）单元测试：不依赖网络（公网用例 monkeypatch getaddrinfo）。"""
import socket

import pytest

import netguard


def test_blocks_local_and_private():
    for url in [
        "http://127.0.0.1:9000/cb",
        "http://localhost/cb",
        "http://10.1.2.3/cb",
        "http://192.168.1.5/cb",
        "http://172.16.0.9/cb",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/cb",
        "http://0.0.0.0/cb",
    ]:
        ok, reason = netguard.webhook_url_allowed(url)
        assert not ok, url
        assert reason


def test_blocks_non_http_schemes():
    for url in ["ftp://example.com/cb", "file:///etc/passwd", "gopher://x"]:
        ok, _ = netguard.webhook_url_allowed(url)
        assert not ok


def test_blocks_invalid_url():
    ok, _ = netguard.webhook_url_allowed("not a url")
    assert not ok


def test_allows_public_ip(monkeypatch):
    class _Info(tuple):
        pass

    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port: [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))])
    ok, reason = netguard.webhook_url_allowed("http://example.com/cb")
    assert ok, reason


def test_allow_private_flag(monkeypatch):
    import config
    monkeypatch.setattr(config, "WEBHOOK_ALLOW_PRIVATE", True)
    ok, _ = netguard.webhook_url_allowed("http://10.0.0.1/cb")
    assert ok


def test_whitelisted_host_skips_resolution(monkeypatch):
    import config
    monkeypatch.setattr(config, "WEBHOOK_ALLOW_PRIVATE", False)
    monkeypatch.setattr(config, "WEBHOOK_ALLOWED_HOSTS", ["internal.lan"])
    # 即使解析到私网地址，白名单主机仍放行（不发起解析）
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port: pytest.fail("should not resolve whitelisted host"))
    ok, _ = netguard.webhook_url_allowed("http://internal.lan:9999/cb")
    assert ok
