import logging

import redis
from django.conf import settings

from core import ratelimit


def _clear(bucket, key):
    client = redis.Redis.from_url(settings.REDIS_URL)
    client.delete(f"easyforms:rl:{bucket}:{key}")


def test_hit_allows_up_to_limit_then_blocks():
    bucket, key = "test_limit", "k1"
    _clear(bucket, key)

    for _ in range(3):
        result = ratelimit.hit(bucket, key, limit=3, window_seconds=60)
        assert result.allowed is True

    result = ratelimit.hit(bucket, key, limit=3, window_seconds=60)
    assert result.allowed is False
    assert result.retry_after is not None
    assert result.retry_after > 0


def test_window_expiry_resets_via_key_manipulation():
    bucket, key = "test_expiry", "k1"
    _clear(bucket, key)

    for _ in range(2):
        assert ratelimit.hit(bucket, key, limit=2, window_seconds=60).allowed is True
    assert ratelimit.hit(bucket, key, limit=2, window_seconds=60).allowed is False

    # Simulate the fixed window rolling over without sleeping.
    _clear(bucket, key)

    assert ratelimit.hit(bucket, key, limit=2, window_seconds=60).allowed is True


def test_fail_open_when_redis_errors(monkeypatch, caplog):
    def _raise(*args, **kwargs):
        raise redis.ConnectionError("boom")

    monkeypatch.setattr(ratelimit, "_get_script", lambda: _raise)

    with caplog.at_level(logging.WARNING, logger="core"):
        result = ratelimit.hit("test_fail_open", "k1", limit=1, window_seconds=60)

    assert result.allowed is True
    assert result.retry_after is None
    assert "rate limiter unavailable" in caplog.text


def test_combine_allows_when_all_allowed():
    a = ratelimit.RateResult(allowed=True, retry_after=None)
    b = ratelimit.RateResult(allowed=True, retry_after=None)

    result = ratelimit.combine(a, b)

    assert result.allowed is True
    assert result.retry_after is None


def test_combine_denies_and_picks_max_retry_after_when_any_denied():
    a = ratelimit.RateResult(allowed=True, retry_after=None)
    b = ratelimit.RateResult(allowed=False, retry_after=5)
    c = ratelimit.RateResult(allowed=False, retry_after=30)

    result = ratelimit.combine(a, b, c)

    assert result.allowed is False
    assert result.retry_after == 30
