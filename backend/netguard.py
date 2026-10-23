"""Webhook 出站 URL 校验（阶段 A2 SSRF 防护）。

独立成轻量模块：不依赖 funasr/torch 等重型依赖，便于单元测试与复用。
规则：
  - 仅允许 http/https；
  - 主机名解析后的每个 IP 都不得为 回环/私网(RFC1918)/链路本地/保留/组播/未指定
    （覆盖 127.0.0.1、10/8、172.16/12、192.168/16、169.254.169.254 云元数据等）；
  - 逃生口（config）：
      ASR_WEBHOOK_ALLOW_PRIVATE=1          整体关闭校验（仅限可信内网自托管）；
      ASR_WEBHOOK_ALLOWED_HOSTS=a,b,c      域名白名单，精确匹配、跳过解析检查。
"""
import ipaddress
import socket
from urllib.parse import urlparse

import config


def webhook_url_allowed(url):
    """校验是否允许向 url 发起出站请求。返回 (ok, reason)。解析失败一律拒绝。"""
    if config.WEBHOOK_ALLOW_PRIVATE:
        return True, ""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, "scheme not http/https"
        host = (p.hostname or "").lower()
        if not host:
            return False, "no host"
        if host in config.WEBHOOK_ALLOWED_HOSTS:
            return True, ""
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return False, "blocked address %s" % ip
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, "invalid url: %s" % e
