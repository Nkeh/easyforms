import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from spam import training
from spam.models import ModelVersion
from spam.storage import LocalArtifactStore
from spam.training import (
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

    result = train_and_save(_fixture_rows(), activate=True, store=store)

    assert result.model_version.is_active is True
    assert ModelVersion.objects.filter(is_active=True).count() == 1


def test_train_and_save_activate_from_one_preexisting_active_row(tmp_path):
    old = ModelVersion.objects.create(version="v0", artifact_key="old.joblib", is_active=True)
    store = LocalArtifactStore(root=tmp_path)

    result = train_and_save(_fixture_rows(), activate=True, store=store)

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
