"""Database backup storage (Day 13a). Deliberately not shared with
spam/storage.py's ArtifactStore — same put/get/exists shape, but backups use
their own BACKUP_* credential set (per the task: distinct from the
model-artifact creds), so this stays its own small, independently configured
class rather than a generalized abstraction touching already-tested Day 8
code for an unrelated feature.
"""

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class BackupStore(ABC):
    @abstractmethod
    def put(self, key: str, path: Path) -> None: ...

    @abstractmethod
    def get(self, key: str, dest_path: Path) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalBackupStore(BackupStore):
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, key: str, path: Path) -> None:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)

    def get(self, key: str, dest_path: Path) -> None:
        src = (self.root / key).resolve()
        dest = Path(dest_path).resolve()
        if src == dest:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()


class S3BackupStore(BackupStore):
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region_name: str = "auto",
    ):
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
        )

    def put(self, key: str, path: Path) -> None:
        with open(path, "rb") as f:
            body = f.read()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body)

    def get(self, key: str, dest_path: Path) -> None:
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        dest_path.write_bytes(response["Body"].read())

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey"):
                return False
            raise
        return True


def get_backup_store() -> BackupStore:
    backend = settings.BACKUP_STORAGE
    if backend == "local":
        return LocalBackupStore(root=Path(settings.BACKUP_LOCAL_DIR))
    if backend == "s3":
        return S3BackupStore(
            bucket=settings.BACKUP_BUCKET,
            endpoint_url=f"https://{settings.BACKUP_R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            access_key=settings.BACKUP_R2_ACCESS_KEY_ID,
            secret_key=settings.BACKUP_R2_SECRET_ACCESS_KEY,
        )
    raise ImproperlyConfigured(f"unknown BACKUP_STORAGE backend: {backend!r}")
