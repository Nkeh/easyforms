import gzip
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.backup_storage import get_backup_store

logger = logging.getLogger("core")


class Command(BaseCommand):
    help = (
        "pg_dump the database (custom format), gzip it, and upload it to the "
        "configured backup store under backups/YYYY/MM/DD/<timestamp>.dump.gz. "
        "Scheduled daily via deploy/crontab (Day 13a)."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        key = f"backups/{now:%Y/%m/%d}/{now:%Y%m%dT%H%M%SZ}.dump.gz"

        with tempfile.TemporaryDirectory() as tmp:
            dump_path = Path(tmp) / "backup.dump"
            gz_path = Path(tmp) / "backup.dump.gz"

            run_pg_dump(settings.DATABASE_URL, dump_path)
            gzip_file(dump_path, gz_path)

            size = gz_path.stat().st_size
            get_backup_store().put(key, gz_path)

        logger.info("backup key=%s bytes=%d", key, size)
        self.stdout.write(self.style.SUCCESS(f"Backed up to {key} ({size} bytes)."))


def run_pg_dump(database_url: str, dest_path: Path) -> None:
    result = subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(dest_path), database_url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CommandError(f"pg_dump failed (exit {result.returncode}): {result.stderr.strip()}")


def gzip_file(src_path: Path, dest_path: Path) -> None:
    with open(src_path, "rb") as src, gzip.open(dest_path, "wb") as dest:
        shutil.copyfileobj(src, dest)
