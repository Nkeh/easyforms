import io

import pytest
from botocore.stub import Stubber
from django.core.exceptions import ImproperlyConfigured

from core.backup_storage import LocalBackupStore, S3BackupStore, get_backup_store


def test_local_store_put_get_exists_round_trip(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src_file = src_dir / "backup.dump.gz"
    src_file.write_bytes(b"hello backup")

    store = LocalBackupStore(root=tmp_path / "store")
    store.put("backups/2026/09/30/20260930T000000Z.dump.gz", src_file)

    assert store.exists("backups/2026/09/30/20260930T000000Z.dump.gz") is True

    dest = tmp_path / "dest" / "downloaded.dump.gz"
    store.get("backups/2026/09/30/20260930T000000Z.dump.gz", dest)
    assert dest.read_bytes() == b"hello backup"


def test_local_store_exists_false_for_missing_key(tmp_path):
    store = LocalBackupStore(root=tmp_path)
    assert store.exists("backups/does/not/exist.dump.gz") is False


def _s3_store():
    return S3BackupStore(
        bucket="easyforms-backups-test",
        endpoint_url="https://example.r2.cloudflarestorage.com",
        access_key="test-key",
        secret_key="test-secret",
    )


def test_s3_store_put_uses_put_object(tmp_path):
    store = _s3_store()
    stubber = Stubber(store.client)
    src_file = tmp_path / "backup.dump.gz"
    src_file.write_bytes(b"backup-bytes")

    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": "easyforms-backups-test",
            "Key": "backups/2026/09/30/x.dump.gz",
            "Body": b"backup-bytes",
        },
    )
    with stubber:
        store.put("backups/2026/09/30/x.dump.gz", src_file)


def test_s3_store_get_uses_get_object(tmp_path):
    store = _s3_store()
    stubber = Stubber(store.client)

    stubber.add_response(
        "get_object",
        {"Body": io.BytesIO(b"downloaded-bytes")},
        {"Bucket": "easyforms-backups-test", "Key": "backups/2026/09/30/x.dump.gz"},
    )
    dest = tmp_path / "dest.dump.gz"
    with stubber:
        store.get("backups/2026/09/30/x.dump.gz", dest)

    assert dest.read_bytes() == b"downloaded-bytes"


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
        assert store.exists("backups/missing.dump.gz") is False


def test_get_backup_store_dispatches_on_setting(settings):
    settings.BACKUP_STORAGE = "local"
    settings.BACKUP_LOCAL_DIR = "/tmp/backups"
    assert isinstance(get_backup_store(), LocalBackupStore)

    settings.BACKUP_STORAGE = "s3"
    settings.BACKUP_R2_ACCOUNT_ID = "acct"
    settings.BACKUP_R2_ACCESS_KEY_ID = "key"
    settings.BACKUP_R2_SECRET_ACCESS_KEY = "secret"
    settings.BACKUP_BUCKET = "bucket"
    assert isinstance(get_backup_store(), S3BackupStore)

    settings.BACKUP_STORAGE = "carrier-pigeon"
    with pytest.raises(ImproperlyConfigured):
        get_backup_store()
