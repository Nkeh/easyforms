import redis
from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError
from django.http import JsonResponse

from core import bounded_call


def healthz(request):
    db_ok = _check_db()
    redis_ok = _check_redis()
    healthy = db_ok and redis_ok
    payload = {
        "status": "ok" if healthy else "down",
        "db": "ok" if db_ok else "down",
        "redis": "ok" if redis_ok else "down",
    }
    return JsonResponse(payload, status=200 if healthy else 503)


def _check_db() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except OperationalError:
        return False


def _check_redis() -> bool:
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
            socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
        )
        return bool(bounded_call.run_bounded(client.ping, timeout=settings.REDIS_TIMEOUT_SECONDS))
    except (redis.RedisError, TimeoutError):
        return False
