import time

import pytest

from core import bounded_call


def test_run_bounded_returns_the_result_when_fast_enough():
    result = bounded_call.run_bounded(lambda: 21 * 2, timeout=1)

    assert result == 42


def test_run_bounded_raises_timeout_error_when_too_slow():
    def _slow():
        time.sleep(0.5)
        return "too late"

    with pytest.raises(TimeoutError):
        bounded_call.run_bounded(_slow, timeout=0.05)


def test_run_bounded_reraises_the_callables_own_exception():
    def _raise():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        bounded_call.run_bounded(_raise, timeout=1)
