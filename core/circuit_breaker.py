import logging
import threading
import time

from django.conf import settings

logger = logging.getLogger("core")

_lock = threading.Lock()
_open_until = 0.0


class CircuitOpenError(Exception):
    """Raised by a call site that skipped Redis entirely because the
    breaker is open (see trip())."""


def is_open() -> bool:
    return time.monotonic() < _open_until


def trip() -> None:
    """Open the breaker for settings.REDIS_BREAKER_SECONDS, so callers skip
    Redis entirely until it closes. Safe to call repeatedly (e.g. once per
    failing request) — only logs on the closed->open transition, never once
    per request, since callers are expected to check is_open() first and
    skip the Redis call (and this function) entirely while already open.
    """
    global _open_until
    with _lock:
        was_open = is_open()
        _open_until = time.monotonic() + settings.REDIS_BREAKER_SECONDS
        if not was_open:
            logger.warning(
                "redis circuit breaker tripped; skipping Redis calls for %.1fs",
                settings.REDIS_BREAKER_SECONDS,
            )


def reset() -> None:
    """Test-only: force the breaker closed immediately."""
    global _open_until
    with _lock:
        _open_until = 0.0
