import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from spam import training
from spam.models import ModelVersion
from spam.storage import LocalArtifactStore
from spam.training import (
    GateFailedError,
    SpamDatasetError,
    download_dataset,
    load_dataset,
    select_threshold,
    train_and_save,
)

pytestmark = pytest.mark.django_db

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_TSV = FIXTURES_DIR / "sms_fixture.tsv"
FIXTURE_ZIP = FIXTURES_DIR / "sms_fixture.zip"


def _fixture_rows():
    return load_dataset(FIXTURE_TSV)


def test_load_dataset_parses_tab_separated_rows():
    rows = load_dataset(FIXTURE_TSV)
    assert len(rows) == 39
    assert rows[0] == ("ham", "Are you free for lunch tomorrow around noon?")
    assert rows[-1][0] == "spam"


def test_download_dataset_reuses_existing_file_without_network(tmp_path, monkeypatch):
    existing = tmp_path / "SMSSpamCollection"
    existing.write_text("ham\thello\n")

    def _boom(*args, **kwargs):
        raise AssertionError("urlopen should not be called when the file already exists")

    monkeypatch.setattr(training.urllib.request, "urlopen", _boom)

    result = download_dataset(tmp_path)
    assert result == existing


def test_download_dataset_checksum_mismatch_raises(tmp_path, monkeypatch):
    file_url = FIXTURE_ZIP.resolve().as_uri()
    monkeypatch.setattr(training, "DATASET_URL", file_url)
    monkeypatch.setattr(training, "DATASET_SHA256", "0" * 64)

    with pytest.raises(SpamDatasetError):
        download_dataset(tmp_path)

    assert not (tmp_path / "SMSSpamCollection").exists()


def test_download_dataset_checksum_match_extracts_file(tmp_path, monkeypatch):
    file_url = FIXTURE_ZIP.resolve().as_uri()
    real_sha256 = hashlib.sha256(FIXTURE_ZIP.read_bytes()).hexdigest()
    monkeypatch.setattr(training, "DATASET_URL", file_url)
    monkeypatch.setattr(training, "DATASET_SHA256", real_sha256)

    result = download_dataset(tmp_path)

    assert result.exists()
    with zipfile.ZipFile(FIXTURE_ZIP) as zf:
        expected = zf.read("SMSSpamCollection")
    assert result.read_bytes() == expected


def test_select_threshold_picks_lowest_threshold_meeting_precision_floor():
    y_true = [0, 0, 0, 1, 1, 1, 1, 1]
    probs = [0.05, 0.2, 0.35, 0.4, 0.6, 0.7, 0.85, 0.95]

    threshold, used_fallback = select_threshold(y_true, probs, min_precision=0.98)

    assert used_fallback is False
    # everything at/above this threshold should be pure-spam in this handcrafted example
    predicted_spam = [p >= threshold for p in probs]
    predicted_labels = [y for y, is_spam in zip(y_true, predicted_spam, strict=True) if is_spam]
    assert predicted_labels and all(label == 1 for label in predicted_labels)


def test_select_threshold_falls_back_when_floor_unreachable():
    # Highest-scoring sample is a negative, so even the strictest possible
    # threshold (predict spam only for the single top score) has precision 0,
    # and no other threshold does better than 0.5 -- min_precision=0.999 is
    # unreachable regardless of tie-breaking details.
    y_true = [1, 0, 1, 0]
    probs = [0.4, 0.5, 0.6, 0.7]

    threshold, used_fallback = select_threshold(y_true, probs, min_precision=0.999)

    assert used_fallback is True
    assert threshold == 0.9


def test_train_and_save_on_fixture_produces_model_version(tmp_path):
    store = LocalArtifactStore(root=tmp_path)

    result = train_and_save(_fixture_rows(), store=store)

    assert result.model_version is not None
    assert result.model_version.is_active is False
    assert 0.0 <= result.threshold <= 1.0
    assert len(result.sha256) == 64
    assert (tmp_path / result.model_version.artifact_key).exists()


def test_train_and_save_dry_run_stores_nothing(tmp_path):
    class ExplodingStore(LocalArtifactStore):
        def put(self, key, path):
            raise AssertionError("put should never be called in dry-run mode")

    result = train_and_save(_fixture_rows(), dry_run=True, store=ExplodingStore(root=tmp_path))

    assert result.model_version is None
    assert result.sha256 is None
    assert ModelVersion.objects.count() == 0


def test_train_and_save_activate_from_zero_active_rows(tmp_path):
    store = LocalArtifactStore(root=tmp_path)

    # force=True: this is testing single-active-row activation mechanics, not
    # gate/model quality -- a model trained on the tiny 39-row SMS-only
    # fixture has no realistic chance of passing the form_sanity gate against
    # the 60-message realistic-contact-form fixture.
    result = train_and_save(_fixture_rows(), activate=True, force=True, store=store)

    assert result.model_version.is_active is True
    assert ModelVersion.objects.filter(is_active=True).count() == 1


def test_train_and_save_activate_from_one_preexisting_active_row(tmp_path):
    old = ModelVersion.objects.create(version="v0", artifact_key="old.joblib", is_active=True)
    store = LocalArtifactStore(root=tmp_path)

    result = train_and_save(_fixture_rows(), activate=True, force=True, store=store)

    old.refresh_from_db()
    assert old.is_active is False
    assert result.model_version.is_active is True
    assert ModelVersion.objects.filter(is_active=True).count() == 1


def test_metrics_are_json_serializable(tmp_path):
    store = LocalArtifactStore(root=tmp_path)
    result = train_and_save(_fixture_rows(), store=store)

    json.dumps(result.metrics)  # must not raise (numpy.float64 leak guard)

    mv = ModelVersion.objects.get(pk=result.model_version.pk)
    assert mv.metrics == result.metrics


# --- 70/15/15 split + threshold-selection leakage fix (Day 9b) -------------


def _fake_gate_result(passed, **overrides):
    result = {
        "fp_count": 0 if passed else 5,
        "fn_count": 0,
        "fp_rate": 0.0,
        "spam_recall": 1.0 if passed else 0.0,
        "passed": passed,
        "fp_indices": [],
        "fn_indices": [],
        "n_ham": 30,
        "n_spam": 30,
        "rows": [],
    }
    result.update(overrides)
    return result


class _SpyPipeline:
    named_steps = {"clf": SimpleNamespace(classes_=[0, 1])}

    def __init__(self):
        self.fit_calls = []
        self.predict_proba_calls = []

    def fit(self, X, y):
        self.fit_calls.append(list(X))
        return self

    def predict_proba(self, X):
        self.predict_proba_calls.append(list(X))
        return np.array([[0.9, 0.1] for _ in X])


def test_train_and_save_splits_train_val_test_with_no_index_overlap(monkeypatch):
    rows = [("ham", f"row{i} unique ham text") for i in range(40)] + [
        ("spam", f"row{i + 40} unique spam text") for i in range(40)
    ]

    spy = _SpyPipeline()
    monkeypatch.setattr(training, "build_pipeline", lambda: spy)
    monkeypatch.setattr(training, "evaluate_form_sanity", lambda *a, **k: _fake_gate_result(True))

    train_and_save(rows, dry_run=True)

    train_texts = set(spy.fit_calls[0])
    val_texts = set(spy.predict_proba_calls[0])
    test_texts = set(spy.predict_proba_calls[1])

    assert train_texts.isdisjoint(val_texts)
    assert train_texts.isdisjoint(test_texts)
    assert val_texts.isdisjoint(test_texts)
    assert train_texts | val_texts | test_texts == {text for _, text in rows}


def test_train_and_save_selects_threshold_from_validation_probs_only(monkeypatch):
    rows = [("ham", f"h{i}") for i in range(40)] + [("spam", f"s{i}") for i in range(40)]

    class _CountingPipeline:
        named_steps = {"clf": SimpleNamespace(classes_=[0, 1])}

        def __init__(self):
            self.calls = 0

        def fit(self, X, y):
            return self

        def predict_proba(self, X):
            self.calls += 1
            value = 0.11 if self.calls == 1 else 0.22
            return np.array([[1 - value, value] for _ in X])

    monkeypatch.setattr(training, "build_pipeline", lambda: _CountingPipeline())
    monkeypatch.setattr(training, "evaluate_form_sanity", lambda *a, **k: _fake_gate_result(True))

    captured = {}
    real_select_threshold = training.select_threshold

    def spy_select_threshold(y_true, probs, **kwargs):
        captured["probs"] = list(probs)
        return real_select_threshold(y_true, probs, **kwargs)

    monkeypatch.setattr(training, "select_threshold", spy_select_threshold)

    train_and_save(rows, dry_run=True)

    # call #1 (validation) returned 0.11 for everyone; call #2 (test)
    # returned 0.22 -- select_threshold must have seen call #1's output only.
    assert captured["probs"] and all(p == 0.11 for p in captured["probs"])


def test_metrics_have_n_train_n_val_n_test_summing_to_n_rows():
    result = train_and_save(_fixture_rows(), dry_run=True)
    m = result.metrics

    assert m["n_train"] + m["n_val"] + m["n_test"] == m["n_rows"]
    assert m["n_val"] > 0
    assert m["n_test"] > 0


def test_metrics_include_sources_when_provided():
    sources = {
        "sms": {"ham": 25, "spam": 14},
        "email": {"ham": 0, "spam": 0, "source": "spamassassin"},
    }

    result = train_and_save(_fixture_rows(), dry_run=True, sources=sources)

    assert result.metrics["sources"] == sources


def test_metrics_always_include_form_sanity_even_in_dry_run():
    result = train_and_save(_fixture_rows(), dry_run=True)

    assert "form_sanity" in result.metrics
    assert "passed" in result.metrics["form_sanity"]
    assert "rows" not in result.metrics["form_sanity"]  # trimmed before storing


def test_activate_refused_when_gate_fails_model_version_still_created(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "evaluate_form_sanity", lambda *a, **k: _fake_gate_result(False))
    store = LocalArtifactStore(root=tmp_path)

    with pytest.raises(GateFailedError):
        train_and_save(_fixture_rows(), activate=True, store=store)

    assert ModelVersion.objects.count() == 1
    assert ModelVersion.objects.get().is_active is False


def test_force_overrides_gate_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "evaluate_form_sanity", lambda *a, **k: _fake_gate_result(False))
    store = LocalArtifactStore(root=tmp_path)

    result = train_and_save(_fixture_rows(), activate=True, force=True, store=store)

    assert result.model_version.is_active is True
