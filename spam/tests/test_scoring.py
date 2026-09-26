import logging
import time
import uuid
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from django.utils import timezone

import spam.training as training_module
from spam.models import ModelVersion
from spam.scoring import Scorer, _parse_ts
from spam.storage import LocalArtifactStore
from spam.training import load_dataset, train_and_save

FIXTURE_TSV = Path(__file__).parent / "fixtures" / "sms_fixture.tsv"


class _StubPipeline:
    def __init__(self, spam_prob):
        self.spam_prob = spam_prob
        self.calls = 0

    def predict_proba(self, texts):
        self.calls += 1
        return np.array([[1 - self.spam_prob, self.spam_prob] for _ in texts])


def _stub_model_version(threshold=0.5):
    return ModelVersion(
        id=uuid.uuid4(), version="stub", artifact_key="stub.joblib", threshold=threshold
    )


def _ready_scorer(pipeline, model_version):
    scorer = Scorer()
    scorer._pipeline = pipeline
    scorer._model_version = model_version
    scorer._last_checked = time.monotonic()
    return scorer


# --- _parse_ts ---------------------------------------------------------


def test_parse_ts_rejects_bool():
    assert _parse_ts(True) is None
    assert _parse_ts(False) is None


def test_parse_ts_accepts_int_and_float():
    assert _parse_ts(12345) == 12345.0
    assert _parse_ts(12345.6) == 12345.6


def test_parse_ts_accepts_numeric_string():
    assert _parse_ts("12345") == 12345.0


def test_parse_ts_rejects_garbage_and_missing():
    assert _parse_ts("not-a-number") is None
    assert _parse_ts(None) is None
    assert _parse_ts([1, 2, 3]) is None


# --- honeypot ------------------------------------------------------------


def test_honeypot_triggers_spam_regardless_of_model():
    stub = _StubPipeline(spam_prob=0.01)
    scorer = _ready_scorer(stub, _stub_model_version())
    now = timezone.now()

    verdict = scorer.score({"message": "hi"}, {"_honeypot": "  filled  "}, now)

    assert verdict.status == "spam"
    assert verdict.signals == ["honeypot"]
    assert verdict.spam_score is None
    assert verdict.model_version is None
    assert stub.calls == 0


def test_empty_honeypot_does_not_trigger():
    stub = _StubPipeline(spam_prob=0.01)
    scorer = _ready_scorer(stub, _stub_model_version())
    now = timezone.now()

    verdict = scorer.score({"message": "hi"}, {"_honeypot": "   "}, now)

    assert "honeypot" not in verdict.signals
    assert stub.calls == 1


def test_non_string_honeypot_value_is_ignored():
    stub = _StubPipeline(spam_prob=0.01)
    scorer = _ready_scorer(stub, _stub_model_version())
    now = timezone.now()

    verdict = scorer.score({"message": "hi"}, {"_honeypot": 123}, now)

    assert verdict.status == "ham"
    assert "honeypot" not in verdict.signals
    assert stub.calls == 1


# --- _ts / fast_submit -----------------------------------------------------


def test_fast_ts_lowers_effective_threshold_and_flips_borderline_score():
    stub = _StubPipeline(spam_prob=0.3)
    scorer = _ready_scorer(stub, _stub_model_version(threshold=0.5))
    now = timezone.now()

    without_fast = scorer.score({"message": "hi"}, {}, now)
    assert without_fast.status == "ham"

    ts_ms = int((now.timestamp() - 1) * 1000)  # 1 second ago
    with_fast = scorer.score({"message": "hi"}, {"_ts": ts_ms}, now)
    assert with_fast.status == "spam"
    assert "fast_submit" in with_fast.signals
    assert "model" in with_fast.signals


def test_missing_or_garbage_ts_has_no_effect():
    stub = _StubPipeline(spam_prob=0.3)
    scorer = _ready_scorer(stub, _stub_model_version(threshold=0.5))
    now = timezone.now()

    v_missing = scorer.score({"message": "hi"}, {}, now)
    v_garbage = scorer.score({"message": "hi"}, {"_ts": "garbage"}, now)

    assert "fast_submit" not in v_missing.signals
    assert "fast_submit" not in v_garbage.signals
    assert v_missing.status == "ham"
    assert v_garbage.status == "ham"


def test_small_future_skew_not_flagged():
    stub = _StubPipeline(spam_prob=0.1)
    scorer = _ready_scorer(stub, _stub_model_version(threshold=0.5))
    now = timezone.now()

    ts_ms = int((now.timestamp() + 10) * 1000)  # 10s ahead — clock skew, tolerated
    verdict = scorer.score({"message": "hi"}, {"_ts": ts_ms}, now)

    assert "fast_submit" not in verdict.signals


def test_large_future_skew_flagged():
    stub = _StubPipeline(spam_prob=0.1)
    scorer = _ready_scorer(stub, _stub_model_version(threshold=0.5))
    now = timezone.now()

    ts_ms = int((now.timestamp() + 90) * 1000)  # 90s ahead — manipulated clock
    verdict = scorer.score({"message": "hi"}, {"_ts": ts_ms}, now)

    assert "fast_submit" in verdict.signals


def test_fast_submit_recorded_but_inert_in_heuristics_only_mode():
    scorer = Scorer()
    scorer._last_checked = time.monotonic()  # no pipeline, but skip DB refresh
    now = timezone.now()

    ts_ms = int((now.timestamp() - 1) * 1000)
    verdict = scorer.score({"message": "hi"}, {"_ts": ts_ms}, now)

    assert verdict.status == "ham"
    assert "fast_submit" in verdict.signals
    assert verdict.spam_score is None
    assert verdict.model_version is None


# --- heuristics-only / failure handling (DB-backed) -------------------------


@pytest.mark.django_db
def test_heuristics_only_when_no_active_model_logs_once(caplog):
    scorer = Scorer()
    now = timezone.now()

    with caplog.at_level(logging.ERROR, logger="spam"):
        for _ in range(5):
            verdict = scorer.score({"message": "hi"}, {}, now)
            assert verdict.status == "ham"
            assert verdict.spam_score is None
            assert verdict.model_version is None

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1


@pytest.mark.django_db
def test_heuristics_only_when_load_raises_logs_once(monkeypatch, caplog):
    ModelVersion.objects.create(version="v1", artifact_key="models/v1.joblib", is_active=True)

    def _raise(mv):
        raise RuntimeError("boom")

    monkeypatch.setattr("spam.scoring.load_model_version", _raise)
    scorer = Scorer()
    now = timezone.now()

    with caplog.at_level(logging.ERROR, logger="spam"):
        for _ in range(3):
            verdict = scorer.score({"message": "hi"}, {}, now)
            assert verdict.status == "ham"
            assert verdict.model_version is None

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1


@pytest.mark.django_db
def test_reload_failure_keeps_serving_last_good_version(monkeypatch, caplog):
    old_pipeline = _StubPipeline(spam_prob=0.1)
    old_mv = _stub_model_version()  # unsaved — stands in for "already loaded"
    # A real, different, active row — forces _refresh to attempt a reload.
    ModelVersion.objects.create(version="v2", artifact_key="models/v2.joblib", is_active=True)

    scorer = _ready_scorer(old_pipeline, old_mv)
    scorer._last_checked = None  # force a refresh attempt

    def _raise(mv):
        raise RuntimeError("bad artifact")

    monkeypatch.setattr("spam.scoring.load_model_version", _raise)
    now = timezone.now()

    with caplog.at_level(logging.WARNING, logger="spam"):
        verdict = scorer.score({"message": "hi"}, {}, now)

    assert scorer._model_version is old_mv
    assert scorer._pipeline is old_pipeline
    assert verdict.model_version is old_mv
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1


@pytest.mark.django_db
def test_scorer_picks_up_newly_activated_version_after_refresh_interval(
    tmp_path, settings, monkeypatch
):
    store = LocalArtifactStore(root=tmp_path / "backing")
    settings.ARTIFACT_STORAGE = "local"
    settings.MODEL_ARTIFACT_DIR = str(store.root)

    rows = load_dataset(FIXTURE_TSV)
    # train_and_save's version tag has second resolution (timezone.now()); two
    # calls within the same wall-clock second would collide on the unique
    # `version` column, so pin distinct timestamps for the two trainings.
    base_time = timezone.now()
    monkeypatch.setattr(training_module.timezone, "now", lambda: base_time)
    v1 = train_and_save(rows, activate=True, store=store).model_version

    scorer = Scorer()
    now = timezone.now()
    scorer.score({"message": "hello there"}, {}, now)
    assert scorer._model_version.id == v1.id

    monkeypatch.setattr(training_module.timezone, "now", lambda: base_time + timedelta(seconds=5))
    v2 = train_and_save(rows, activate=True, store=store).model_version
    assert v1.id != v2.id

    # Interval not yet elapsed: still serving v1.
    scorer.score({"message": "hello there"}, {}, now)
    assert scorer._model_version.id == v1.id

    # Simulate the interval elapsing.
    scorer._last_checked = time.monotonic() - settings.SPAM_MODEL_REFRESH_SECONDS - 1
    scorer.score({"message": "hello there"}, {}, now)
    assert scorer._model_version.id == v2.id
