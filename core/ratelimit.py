import logging
from dataclasses import dataclass

import redis
from django.conf import settings

from core import bounded_call, circuit_breaker

logger = logging.getLogger("core")

_LUA_HIT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

_client = None
_script = None


def _get_script():
    global _client, _script
    if _script is None:
        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
            socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
        )
        _script = _client.register_script(_LUA_HIT)
    return _script


@dataclass
class RateResult:
    allowed: bool
    retry_after: int | None


def hit(bucket: str, key: str, limit: int, window_seconds: int) -> RateResult:
    """Fixed-window rate limit: at most `limit` hits per `window_seconds` for
    this bucket+key. Fails open (allows) if Redis is unreachable (NFR-3), and
    skips Redis entirely while the shared circuit breaker is open."""
    if circuit_breaker.is_open():
        return RateResult(allowed=True, retry_after=None)

    redis_key = f"easyforms:rl:{bucket}:{key}"
    try:
        count, ttl = bounded_call.run_bounded(
            lambda: _get_script()(keys=[redis_key], args=[window_seconds]),
            timeout=settings.REDIS_TIMEOUT_SECONDS,
        )
    except (redis.RedisError, TimeoutError):
        circuit_breaker.trip()
        logger.warning("rate limiter unavailable (bucket=%s); failing open", bucket)
        return RateResult(allowed=True, retry_after=None)

    if count <= limit:
        return RateResult(allowed=True, retry_after=None)
    return RateResult(allowed=False, retry_after=max(int(ttl), 1))


def combine(*results: RateResult) -> RateResult:
    """Merge results from multiple windows/dimensions checked for one request."""
    denied = [r for r in results if not r.allowed]
    if not denied:
        return RateResult(allowed=True, retry_after=None)
    return RateResult(allowed=False, retry_after=max(r.retry_after or 1 for r in denied))
