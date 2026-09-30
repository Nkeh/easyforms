import gzip
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.backup_storage import get_backup_store

logger = logging.getLogger("core")


class Command(BaseCommand):
    help = (
        "Download a backup by --key and pg_restore it into --database-url. "
        "--database-url is required with no default (deliberately NOT "
        "settings.DATABASE_URL) so a restore can never accidentally target "
        "the live database by omission."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--key", required=True, help="Backup store key, e.g. backups/2026/09/30/..."
        )
        parser.add_argument("--database-url", required=True, help="Target database to restore into")

    def handle(self, *args, **options):
        key = options["key"]
        database_url = options["database_url"]

        store = get_backup_store()
        if not store.exists(key):
            raise CommandError(f"no backup found at key={key!r}")

        with tempfile.TemporaryDirectory() as tmp:
            gz_path = Path(tmp) / "backup.dump.gz"
            dump_path = Path(tmp) / "backup.dump"

            store.get(key, gz_path)
            gunzip_file(gz_path, dump_path)
            run_pg_restore(database_url, dump_path)

        logger.info("restore key=%s", key)
        self.stdout.write(self.style.SUCCESS(f"Restored {key}."))


def gunzip_file(src_path: Path, dest_path: Path) -> None:
    with gzip.open(src_path, "rb") as src, open(dest_path, "wb") as dest:
        shutil.copyfileobj(src, dest)


def run_pg_restore(database_url: str, dump_path: Path) -> None:
    result = subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            f"--dbname={database_url}",
            str(dump_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CommandError(f"pg_restore failed (exit {result.returncode}): {result.stderr.strip()}")
