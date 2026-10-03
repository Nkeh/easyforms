import gzip
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.backup_storage import LocalBackupStore
from core.management.commands import restore as restore_command

pytestmark = pytest.mark.django_db


def test_restore_requires_key_and_database_url():
    with pytest.raises(CommandError, match="--key.*--database-url"):
        call_command("restore", stdout=StringIO(), stderr=StringIO())


def test_restore_raises_when_key_not_found(settings, tmp_path):
    settings.BACKUP_STORAGE = "local"
    settings.BACKUP_LOCAL_DIR = str(tmp_path)

    with pytest.raises(CommandError, match="no backup found"):
        call_command(
            "restore",
            "--key",
            "backups/2026/09/30/missing.dump.gz",
            "--database-url",
            "postgres://user:pass@localhost:5432/scratch",
            stdout=StringIO(),
        )


def test_restore_downloads_gunzips_and_calls_pg_restore(monkeypatch, settings, tmp_path):
    settings.BACKUP_STORAGE = "local"
    settings.BACKUP_LOCAL_DIR = str(tmp_path)

    key = "backups/2026/09/30/20260930T000000Z.dump.gz"
    store = LocalBackupStore(root=tmp_path)
    src = tmp_path / "src.dump"
    src.write_bytes(b"dump-bytes")
    gz_src = tmp_path / "src.dump.gz"
    with open(src, "rb") as f_in, gzip.open(gz_src, "wb") as f_out:
        f_out.write(f_in.read())
    store.put(key, gz_src)

    calls = []

    def _fake_pg_restore(database_url, dump_path):
        calls.append((database_url, dump_path.read_bytes()))

    monkeypatch.setattr(restore_command, "run_pg_restore", _fake_pg_restore)

    out = StringIO()
    call_command(
        "restore",
        "--key",
        key,
        "--database-url",
        "postgres://user:pass@localhost:5432/scratch",
        stdout=out,
    )

    assert len(calls) == 1
    target_database_url, dump_bytes = calls[0]
    assert target_database_url == "postgres://user:pass@localhost:5432/scratch"
    assert dump_bytes == b"dump-bytes"
    assert key in out.getvalue()
