import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from spam import training as training_module
from spam.models import ModelVersion

pytestmark = pytest.mark.django_db

FIXTURE_TSV = Path(__file__).parent / "fixtures" / "sms_fixture.tsv"

_FAILING_GATE_RESULT = {
    "fp_count": 5,
    "fn_count": 0,
    "fp_rate": 0.17,
    "spam_recall": 0.0,
    "passed": False,
    "fp_indices": [0, 1, 2, 3, 4],
    "fn_indices": [],
    "n_ham": 30,
    "n_spam": 30,
    "rows": [],
}


@pytest.fixture(autouse=True)
def _no_network_download(monkeypatch):
    monkeypatch.setattr(
        "spam.management.commands.train_spam_model.download_dataset",
        lambda dest_dir: FIXTURE_TSV,
    )
    monkeypatch.setattr(
        "spam.management.commands.train_spam_model.download_email_corpus",
        lambda data_dir: ([], "spamassassin"),
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
    # --force: a model trained on the tiny 39-row SMS-only fixture has no
    # realistic chance of passing the form_sanity gate; this test is only
    # about the --activate flag's wiring, not gate/model quality.
    call_command("train_spam_model", "--activate", "--force", stdout=out)

    assert ModelVersion.objects.filter(is_active=True).count() == 1
    assert "Saved ModelVersion" in out.getvalue()


def test_train_spam_model_combines_sms_and_email_rows(monkeypatch):
    monkeypatch.setattr(
        "spam.management.commands.train_spam_model.download_email_corpus",
        lambda data_dir: (
            [("ham", "email ham text"), ("spam", "email spam text")],
            "spamassassin",
        ),
    )

    out = StringIO()
    call_command("train_spam_model", "--dry-run", stdout=out)

    metrics_json = "\n".join(out.getvalue().splitlines()[:-1])
    metrics = json.loads(metrics_json)

    assert metrics["n_rows"] == 39 + 2
    assert metrics["sources"]["sms"] == {"ham": 25, "spam": 14}
    assert metrics["sources"]["email"] == {"ham": 1, "spam": 1, "source": "spamassassin"}


def test_train_spam_model_activate_refused_when_gate_fails(monkeypatch):
    monkeypatch.setattr("spam.training.evaluate_form_sanity", lambda *a, **k: _FAILING_GATE_RESULT)

    with pytest.raises(CommandError):
        call_command("train_spam_model", "--activate")


def test_train_spam_model_force_overrides_gate_failure(monkeypatch):
    monkeypatch.setattr("spam.training.evaluate_form_sanity", lambda *a, **k: _FAILING_GATE_RESULT)

    out = StringIO()
    call_command("train_spam_model", "--activate", "--force", stdout=out)

    assert ModelVersion.objects.filter(is_active=True).count() == 1


def test_train_spam_model_gate_flags_are_configurable(monkeypatch):
    captured = {}
    real_train_and_save = training_module.train_and_save

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return real_train_and_save(*args, **kwargs)

    monkeypatch.setattr("spam.management.commands.train_spam_model.train_and_save", spy)

    call_command(
        "train_spam_model", "--dry-run", "--gate-max-fp", "3", "--gate-min-spam-recall", "0.5"
    )

    assert captured["gate_max_fp"] == 3
    assert captured["gate_min_spam_recall"] == 0.5


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
