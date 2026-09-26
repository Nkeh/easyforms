import io

import pytest
from botocore.stub import Stubber
from django.core.exceptions import ImproperlyConfigured

from spam.storage import LocalArtifactStore, S3ArtifactStore, get_artifact_store


def test_local_store_put_get_exists_round_trip(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src_file = src_dir / "model.joblib"
    src_file.write_bytes(b"hello model")

    store = LocalArtifactStore(root=tmp_path / "store")
    store.put("spam/models/v1.joblib", src_file)

    assert store.exists("spam/models/v1.joblib") is True

    dest = tmp_path / "dest" / "downloaded.joblib"
    store.get("spam/models/v1.joblib", dest)
    assert dest.read_bytes() == b"hello model"


def test_local_store_exists_false_for_missing_key(tmp_path):
    store = LocalArtifactStore(root=tmp_path)
    assert store.exists("does/not/exist.joblib") is False


def test_local_store_get_same_path_is_noop(tmp_path):
    store = LocalArtifactStore(root=tmp_path)
    key = "spam/models/v1.joblib"
    src_file = tmp_path / key
    src_file.parent.mkdir(parents=True)
    src_file.write_bytes(b"content")

    store.get(key, src_file)
    assert src_file.read_bytes() == b"content"


def _s3_store():
    return S3ArtifactStore(
        bucket="easyforms-test",
        endpoint_url="https://example.r2.cloudflarestorage.com",
        access_key="test-key",
        secret_key="test-secret",
    )


def test_s3_store_put_uses_put_object(tmp_path):
    store = _s3_store()
    stubber = Stubber(store.client)
    src_file = tmp_path / "model.joblib"
    src_file.write_bytes(b"artifact-bytes")

    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "easyforms-test", "Key": "spam/models/v1.joblib", "Body": b"artifact-bytes"},
    )
    with stubber:
        store.put("spam/models/v1.joblib", src_file)


def test_s3_store_get_uses_get_object(tmp_path):
    store = _s3_store()
    stubber = Stubber(store.client)

    stubber.add_response(
        "get_object",
        {"Body": io.BytesIO(b"downloaded-bytes")},
        {"Bucket": "easyforms-test", "Key": "spam/models/v1.joblib"},
    )
    dest = tmp_path / "dest.joblib"
    with stubber:
        store.get("spam/models/v1.joblib", dest)

    assert dest.read_bytes() == b"downloaded-bytes"


def test_s3_store_exists_true():
    store = _s3_store()
    stubber = Stubber(store.client)
    stubber.add_response(
        "head_object", {}, {"Bucket": "easyforms-test", "Key": "spam/models/v1.joblib"}
    )
    with stubber:
        assert store.exists("spam/models/v1.joblib") is True


def test_s3_store_exists_false_for_missing_key():
    store = _s3_store()
    stubber = Stubber(store.client)
    stubber.add_client_error(
        "head_object",
        service_error_code="404",
        service_message="Not Found",
        http_status_code=404,
    )
    with stubber:
        assert store.exists("spam/models/missing.joblib") is False


def test_get_artifact_store_dispatches_on_setting(settings):
    settings.ARTIFACT_STORAGE = "local"
    settings.MODEL_ARTIFACT_DIR = "/tmp/artifacts"
    assert isinstance(get_artifact_store(), LocalArtifactStore)

    settings.ARTIFACT_STORAGE = "s3"
    settings.R2_ACCOUNT_ID = "acct"
    settings.R2_ACCESS_KEY_ID = "key"
    settings.R2_SECRET_ACCESS_KEY = "secret"
    settings.R2_BUCKET = "bucket"
    assert isinstance(get_artifact_store(), S3ArtifactStore)

    settings.ARTIFACT_STORAGE = "carrier-pigeon"
    with pytest.raises(ImproperlyConfigured):
        get_artifact_store()
