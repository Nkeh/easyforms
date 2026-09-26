import pytest
import redis
from django.conf import settings


@pytest.fixture(autouse=True)
def _flush_rate_limit_keys():
    client = redis.Redis.from_url(settings.REDIS_URL)
    _flush(client)
    yield
    _flush(client)


def _flush(client):
    keys = list(client.scan_iter(match="easyforms:rl:*"))
    if keys:
        client.delete(*keys)
