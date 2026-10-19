"""租户级限流 / 配额（FR-08，opt-in）。

仅在配置了 ASR_API_KEYS（多租户模式）时生效；未配置则不限制，行为完全不变。
提供两类控制：
  1) 并发：同一租户同时处理的任务数不超过 max_concurrent；
  2) 日配额：同一租户当日累计处理的音频时长（秒）不超过 daily_seconds。

状态保存在进程内存（单进程部署足够）；若多进程部署需改为共享存储（如 Redis）。
"""
import threading
import time

import config

_lock = threading.Lock()
_active = {}   # tenant -> 当前正在处理的任务数
_daily = {}    # tenant -> [date_str, 已用秒数]


def _today():
    return time.strftime("%Y-%m-%d")


def limits_for(tenant):
    """返回某租户的限额配置；多租户模式未开启 / 管理员或共享租户返回 None（不限）。"""
    if not config.API_KEY_TENANTS:
        return None
    if tenant in ("", None):
        return None  # 管理员/未分配租户不设限，避免自限
    return config.TENANT_LIMITS.get(tenant) or config.TENANT_LIMITS.get("*")


def can_enqueue(tenant, duration_s):
    """上传时校验当日时长配额。返回 (ok, 原因)。"""
    lim = limits_for(tenant)
    if not lim or not lim.get("daily_seconds"):
        return True, ""
    with _lock:
        d = _daily.setdefault(tenant, [_today(), 0])
        if d[0] != _today():
            d[0] = _today(); d[1] = 0
        if d[1] + duration_s > lim["daily_seconds"]:
            return False, "今日处理时长配额已用尽（已用 %d/%d 秒）" % (int(d[1]), int(lim["daily_seconds"]))
    return True, ""


def add_usage(tenant, duration_s):
    """任务完成（含失败）后累计当日已用时长。"""
    lim = limits_for(tenant)
    if not lim or not lim.get("daily_seconds"):
        return
    if duration_s <= 0:
        return
    with _lock:
        d = _daily.setdefault(tenant, [_today(), 0])
        if d[0] != _today():
            d[0] = _today(); d[1] = 0
        d[1] += duration_s


def can_process(tenant):
    """worker 领取任务前校验并发上限。"""
    lim = limits_for(tenant)
    if not lim or not lim.get("max_concurrent"):
        return True
    with _lock:
        return _active.get(tenant, 0) < int(lim["max_concurrent"])


def try_begin(tenant):
    """原子地「检查并占用」一个并发名额，防止多 worker 同时通过检查超卖上限。"""
    lim = limits_for(tenant)
    with _lock:
        if lim and lim.get("max_concurrent"):
            if _active.get(tenant, 0) >= int(lim["max_concurrent"]):
                return False
        _active[tenant] = _active.get(tenant, 0) + 1
        return True


def begin_process(tenant):
    with _lock:
        _active[tenant] = _active.get(tenant, 0) + 1


def end_process(tenant):
    with _lock:
        _active[tenant] = max(0, _active.get(tenant, 0) - 1)
