from pathlib import Path

import pytest

from spam.loading import SpamModelLoadError, load_model_version
from spam.storage import LocalArtifactStore
from spam.training import load_dataset, train_and_save

pytestmark = pytest.mark.django_db

FIXTURE_TSV = Path(__file__).parent / "fixtures" / "sms_fixture.tsv"


def _trained_model_version(tmp_path):
    store = LocalArtifactStore(root=tmp_path / "backing")
    result = train_and_save(load_dataset(FIXTURE_TSV), store=store)
    return result.model_version, store


def test_load_model_version_happy_path(tmp_path, settings):
    mv, store = _trained_model_version(tmp_path)
    settings.ARTIFACT_STORAGE = "local"
    settings.MODEL_ARTIFACT_DIR = str(store.root)

    pipeline = load_model_version(mv)

    assert hasattr(pipeline, "predict_proba")
    probs = pipeline.predict_proba(["free prize call now"])
    assert probs.shape[1] == 2


def test_load_model_version_rejects_tampered_artifact(tmp_path, settings, monkeypatch):
    mv, store = _trained_model_version(tmp_path)
    settings.ARTIFACT_STORAGE = "local"
    settings.MODEL_ARTIFACT_DIR = str(store.root)

    artifact_path = store.root / mv.artifact_key
    data = bytearray(artifact_path.read_bytes())
    data[0] ^= 0xFF
    artifact_path.write_bytes(bytes(data))

    def _boom(*args, **kwargs):
        raise AssertionError("joblib.load should never be called on a tampered artifact")

    monkeypatch.setattr("spam.loading.load", _boom)

    with pytest.raises(SpamModelLoadError):
        load_model_version(mv)


def test_load_model_version_rejects_sklearn_version_mismatch(tmp_path, settings):
    mv, store = _trained_model_version(tmp_path)
    settings.ARTIFACT_STORAGE = "local"
    settings.MODEL_ARTIFACT_DIR = str(store.root)

    mv.sklearn_version = "0.1"
    mv.save(update_fields=["sklearn_version"])

    with pytest.raises(SpamModelLoadError):
        load_model_version(mv)


def test_load_model_version_downloads_when_cache_missing(tmp_path, settings, monkeypatch):
    mv, store = _trained_model_version(tmp_path)
    # Cache dir is distinct from the backing store's root, so the artifact
    # isn't already sitting at the cache path -- load_model_version must call
    # the store's get() to populate it.
    settings.MODEL_ARTIFACT_DIR = str(tmp_path / "cache")
    monkeypatch.setattr("spam.loading.get_artifact_store", lambda: store)

    pipeline = load_model_version(mv)

    assert (tmp_path / "cache" / mv.artifact_key).exists()
    assert hasattr(pipeline, "predict_proba")
