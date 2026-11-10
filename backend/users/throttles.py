"""固定窗口限流（Django cache 实现，不依赖外部服务）。

- 登录：按来源 IP，settings.LOGIN_RATE_LIMIT 次/窗口；
- 绑定：按登录用户，settings.BINDING_RATE_LIMIT 次/窗口；
- 超限抛 DRF Throttled(429)，DRF 会附带 Retry-After 响应头；
- settings.RATE_LIMIT_ENABLED=False（测试/显式关闭）时直接放行。
"""
import time

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import Throttled

CACHE_PREFIX = "rate-limit"


def _client_ip(request):
    return request.META.get("REMOTE_ADDR") or "unknown"


def _fixed_window(scope, identity, limit):
    if not settings.RATE_LIMIT_ENABLED:
        return
    window = settings.RATE_LIMIT_WINDOW_SECONDS
    now = time.time()
    bucket = int(now // window)
    key = f"{CACHE_PREFIX}:{scope}:{identity}:{bucket}"
    timeout = window + 1
    # cache.add 原子创建窗口计数键；键已存在则 incr 原子自增，避免 get+set 并发少计。
    if cache.add(key, 1, timeout=timeout):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            # 键在 add 与 incr 之间过期/被清理：重新原子建键后再自增。
            if cache.add(key, 1, timeout=timeout):
                count = 1
            else:
                count = cache.incr(key)
    if count > limit:
        retry_after = max(1, int(window - now % window))
        raise Throttled(wait=retry_after, detail=f"请求过于频繁，请 {retry_after} 秒后重试")


def enforce_login_rate_limit(request):
    _fixed_window("login-ip", _client_ip(request), settings.LOGIN_RATE_LIMIT)


def enforce_binding_rate_limit(request):
    user = getattr(request, "user", None)
    identity = user.pk if user is not None and user.is_authenticated else "anonymous"
    _fixed_window("binding-user", identity, settings.BINDING_RATE_LIMIT)
