import logging

from core import circuit_breaker


def test_starts_closed():
    assert circuit_breaker.is_open() is False


def test_trip_opens_the_breaker():
    circuit_breaker.trip()

    assert circuit_breaker.is_open() is True


def test_breaker_closes_after_the_interval(monkeypatch, settings):
    settings.REDIS_BREAKER_SECONDS = 5
    fake_now = [1000.0]
    monkeypatch.setattr(circuit_breaker.time, "monotonic", lambda: fake_now[0])

    circuit_breaker.trip()
    assert circuit_breaker.is_open() is True

    fake_now[0] += 5.1
    assert circuit_breaker.is_open() is False


def test_trip_logs_once_per_open_transition(caplog):
    with caplog.at_level(logging.WARNING, logger="core"):
        circuit_breaker.trip()
        circuit_breaker.trip()
        circuit_breaker.trip()

    trip_logs = [r for r in caplog.records if "circuit breaker tripped" in r.message]
    assert len(trip_logs) == 1


def test_trip_logs_again_after_closing_and_retripping(monkeypatch, settings, caplog):
    settings.REDIS_BREAKER_SECONDS = 5
    fake_now = [1000.0]
    monkeypatch.setattr(circuit_breaker.time, "monotonic", lambda: fake_now[0])

    with caplog.at_level(logging.WARNING, logger="core"):
        circuit_breaker.trip()
        fake_now[0] += 5.1
        circuit_breaker.trip()

    trip_logs = [r for r in caplog.records if "circuit breaker tripped" in r.message]
    assert len(trip_logs) == 2


def test_reset_closes_the_breaker():
    circuit_breaker.trip()
    assert circuit_breaker.is_open() is True

    circuit_breaker.reset()

    assert circuit_breaker.is_open() is False
