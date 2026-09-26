import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from spam.storage import LocalArtifactStore
from spam.training import load_dataset, train_and_save

pytestmark = pytest.mark.django_db

FIXTURE_TSV = Path(__file__).parent / "fixtures" / "sms_fixture.tsv"
FORM_SANITY_JSON = Path(__file__).parent.parent / "fixtures" / "form_sanity.json"


@pytest.fixture
def trained_version(tmp_path, settings):
    settings.ARTIFACT_STORAGE = "local"
    settings.MODEL_ARTIFACT_DIR = str(tmp_path / "artifacts")
    store = LocalArtifactStore(root=tmp_path / "artifacts")
    result = train_and_save(load_dataset(FIXTURE_TSV), activate=True, store=store)
    return result.model_version


def test_eval_uses_active_model_by_default(trained_version):
    out = StringIO()
    call_command("eval_spam_model", stdout=out)
    output = out.getvalue()

    assert f"model version={trained_version.version}" in output
    assert "false positives" in output
    assert "false negatives" in output


def test_eval_accepts_explicit_version(trained_version):
    out = StringIO()
    call_command("eval_spam_model", "--model-version", trained_version.version, stdout=out)

    assert f"model version={trained_version.version}" in out.getvalue()


def test_eval_raises_when_no_model_available():
    with pytest.raises(CommandError):
        call_command("eval_spam_model")


def test_eval_raises_for_unknown_version(trained_version):
    with pytest.raises(CommandError):
        call_command("eval_spam_model", "--model-version", "does-not-exist")


def test_eval_prints_one_line_per_fixture_entry(trained_version):
    out = StringIO()
    call_command("eval_spam_model", stdout=out)

    lines = [line for line in out.getvalue().splitlines() if line.startswith("[")]
    entries = json.loads(FORM_SANITY_JSON.read_text())
    assert len(lines) == len(entries)
