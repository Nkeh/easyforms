import pytest
import redis
from django.conf import settings


@pytest.fixture(autouse=True)
def _synchronous_rq_queues(settings):
    """Day 10: run RQ jobs in-process so mail.outbox / DB assertions can run
    right after django_rq.get_queue(...).enqueue(...), with no real worker
    needed. Two settings, both required:

    - RQ_QUEUES[...]["ASYNC"] = False makes the job function call happen
      synchronously instead of being handed to a worker.
    - RQ["COMMIT_MODE"] = "auto" disables django-rq's own default
      ("on_db_commit"), which otherwise wraps *every* enqueue_call in its own
      internal transaction.on_commit(...) whenever called inside an atomic
      block. pytest-django wraps each @pytest.mark.django_db test in one
      such block for the whole test, so with the default commit mode that
      internal on_commit would never fire on rollback — independent of
      ASYNC. This only affects django-rq's own deferral; our own explicit
      transaction.on_commit(...) calls (ingest/views.py) still defer
      normally and need django_capture_on_commit_callbacks to fire in tests.

    Overriding via the settings fixture (rather than baking these into any
    settings module) keeps local/docker dev on real async, on-commit-safe
    queues while tests get synchronous, immediate execution regardless of
    which DJANGO_SETTINGS_MODULE the process started with (docker-compose
    hardcodes config.settings.local for the same container `pytest` runs in).
    """
    settings.RQ_QUEUES = {name: {**cfg, "ASYNC": False} for name, cfg in settings.RQ_QUEUES.items()}
    settings.RQ = {"COMMIT_MODE": "auto"}


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """The breaker is process-global module state (core.circuit_breaker),
    so without a reset a trip() in one test would leak into the next and
    make unrelated Redis calls skip silently."""
    from core import circuit_breaker

    circuit_breaker.reset()
    yield
    circuit_breaker.reset()


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
