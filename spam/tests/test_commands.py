import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from spam.models import ModelVersion

pytestmark = pytest.mark.django_db

FIXTURE_TSV = Path(__file__).parent / "fixtures" / "sms_fixture.tsv"


@pytest.fixture(autouse=True)
def _no_network_download(monkeypatch):
    monkeypatch.setattr(
        "spam.management.commands.train_spam_model.download_dataset",
        lambda dest_dir: FIXTURE_TSV,
    )


@pytest.fixture(autouse=True)
def _local_artifact_dir(settings, tmp_path):
    settings.ARTIFACT_STORAGE = "local"
    settings.MODEL_ARTIFACT_DIR = str(tmp_path / "artifacts")


def test_train_spam_model_dry_run_via_call_command():
    out = StringIO()
    call_command("train_spam_model", "--dry-run", stdout=out)

    assert ModelVersion.objects.count() == 0
    output = out.getvalue()
    assert "Dry run" in output
    metrics_json = "\n".join(output.splitlines()[:-1])
    json.loads(metrics_json)  # must be valid JSON


def test_train_spam_model_activate_flag_via_call_command():
    out = StringIO()
    call_command("train_spam_model", "--activate", stdout=out)

    assert ModelVersion.objects.filter(is_active=True).count() == 1
    assert "Saved ModelVersion" in out.getvalue()


def test_activate_spam_model_switches_active_row():
    ModelVersion.objects.create(version="v1", artifact_key="models/v1.pkl", is_active=True)
    v2 = ModelVersion.objects.create(version="v2", artifact_key="models/v2.pkl", is_active=False)

    out = StringIO()
    call_command("activate_spam_model", "v2", stdout=out)

    v2.refresh_from_db()
    assert v2.is_active is True
    assert ModelVersion.objects.filter(is_active=True).count() == 1


def test_activate_spam_model_unknown_version_raises_command_error():
    with pytest.raises(CommandError):
        call_command("activate_spam_model", "does-not-exist")
