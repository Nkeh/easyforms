from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from accounts.models import Account
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _make_form():
    account = Account.objects.create(name="Acme Inc")
    return Form.objects.create(account=account, name="Contact form")


def _make_submission(form_obj, **kwargs):
    kwargs.setdefault("payload", {"secret": "do-not-leak-me-12345"})
    kwargs.setdefault("status", Submission.Status.HAM)
    kwargs.setdefault("original_status", kwargs["status"])
    kwargs.setdefault("source_ip_hash", "a" * 64)
    return Submission.objects.create(form=form_obj, **kwargs)


def test_prints_overall_and_shadow_sections():
    form_obj = _make_form()
    _make_submission(form_obj, status=Submission.Status.HAM)
    _make_submission(form_obj, status=Submission.Status.SPAM)

    out = StringIO()
    call_command("spam_report", stdout=out)
    output = out.getvalue()

    assert "Spam report" in output
    assert "Overall:" in output
    assert "Shadow evidence" in output
    assert "No alert threshold crossed." in output


def test_days_argument_is_respected():
    form_obj = _make_form()
    old = _make_submission(form_obj)
    Submission.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))

    out = StringIO()
    call_command("spam_report", "--days", "7", stdout=out)

    assert "submissions scored: 0" in out.getvalue()


@override_settings(SPAM_FP_ALERT_RATE=0.1, SPAM_ALERT_MIN_ROWS=2)
def test_prints_alert_warning_when_threshold_crossed():
    form_obj = _make_form()
    for _ in range(2):
        s = _make_submission(form_obj, status=Submission.Status.SPAM)
        s.status = Submission.Status.HAM
        s.corrected = True
        s.save(update_fields=["status", "corrected"])

    out = StringIO()
    call_command("spam_report", stdout=out)

    assert "ALERT" in out.getvalue()


def test_output_never_contains_payload_content():
    form_obj = _make_form()
    _make_submission(form_obj, payload={"secret": "do-not-leak-me-12345"})

    out = StringIO()
    call_command("spam_report", stdout=out)

    assert "do-not-leak-me-12345" not in out.getvalue()
