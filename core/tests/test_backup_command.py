import re
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands import backup as backup_command

pytestmark = pytest.mark.django_db

SENTINEL = b"submission-payload-should-never-appear-in-output"


def _fake_pg_dump_writes(content: bytes):
    def _fake(database_url, dest_path):
        Path(dest_path).write_bytes(content)

    return _fake


def test_backup_uploads_gzipped_dump_and_reports_key_and_size(monkeypatch, settings, tmp_path):
    settings.BACKUP_STORAGE = "local"
    settings.BACKUP_LOCAL_DIR = str(tmp_path)
    monkeypatch.setattr(backup_command, "run_pg_dump", _fake_pg_dump_writes(SENTINEL))

    out = StringIO()
    call_command("backup", stdout=out)
    output = out.getvalue()

    match = re.search(
        r"Backed up to (backups/\d{4}/\d{2}/\d{2}/\d{8}T\d{6}Z\.dump\.gz) \((\d+) bytes\)", output
    )
    assert match, output
    key, size = match.group(1), int(match.group(2))

    stored = tmp_path / key
    assert stored.exists()
    assert stored.stat().st_size == size


def test_backup_output_never_contains_dump_content(monkeypatch, settings, tmp_path):
    settings.BACKUP_STORAGE = "local"
    settings.BACKUP_LOCAL_DIR = str(tmp_path)
    monkeypatch.setattr(backup_command, "run_pg_dump", _fake_pg_dump_writes(SENTINEL))

    out = StringIO()
    call_command("backup", stdout=out)

    assert SENTINEL.decode() not in out.getvalue()


def test_backup_raises_command_error_when_pg_dump_fails(monkeypatch, settings, tmp_path):
    settings.BACKUP_STORAGE = "local"
    settings.BACKUP_LOCAL_DIR = str(tmp_path)

    def _fail(database_url, dest_path):
        raise CommandError("pg_dump failed (exit 1): connection refused")

    monkeypatch.setattr(backup_command, "run_pg_dump", _fail)

    with pytest.raises(CommandError):
        call_command("backup", stdout=StringIO())
