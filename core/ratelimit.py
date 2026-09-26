import logging
from dataclasses import dataclass

import redis
from django.conf import settings

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
        _client = redis.Redis.from_url(settings.REDIS_URL)
        _script = _client.register_script(_LUA_HIT)
    return _script


@dataclass
class RateResult:
    allowed: bool
    retry_after: int | None


def hit(bucket: str, key: str, limit: int, window_seconds: int) -> RateResult:
    """Fixed-window rate limit: at most `limit` hits per `window_seconds` for
    this bucket+key. Fails open (allows) if Redis is unreachable (NFR-3)."""
    redis_key = f"easyforms:rl:{bucket}:{key}"
    try:
        count, ttl = _get_script()(keys=[redis_key], args=[window_seconds])
    except redis.RedisError:
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
