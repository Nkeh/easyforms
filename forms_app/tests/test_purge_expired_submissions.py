from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Account
from billing.models import UsageEvent
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _make_form(**kwargs):
    account = kwargs.pop("account", None) or Account.objects.create(name="Acme Inc")
    return Form.objects.create(account=account, name="Contact form", **kwargs)


def _make_submission(form_obj, age_days, **kwargs):
    kwargs.setdefault("payload", {})
    kwargs.setdefault("status", Submission.Status.HAM)
    kwargs.setdefault("original_status", kwargs["status"])
    kwargs.setdefault("source_ip_hash", "a" * 64)
    submission = Submission.objects.create(form=form_obj, **kwargs)
    Submission.objects.filter(pk=submission.pk).update(
        created_at=timezone.now() - timedelta(days=age_days)
    )
    return submission


def test_deletes_only_rows_past_effective_retention():
    form_obj = _make_form()  # free plan default: 30 days
    expired = _make_submission(form_obj, age_days=31)
    fresh = _make_submission(form_obj, age_days=1)

    call_command("purge_expired_submissions")

    assert not Submission.objects.filter(pk=expired.pk).exists()
    assert Submission.objects.filter(pk=fresh.pk).exists()


def test_respects_form_level_retention_override():
    form_obj = _make_form(retention_days=7)
    expired = _make_submission(form_obj, age_days=8)
    fresh = _make_submission(form_obj, age_days=6)

    call_command("purge_expired_submissions")

    assert not Submission.objects.filter(pk=expired.pk).exists()
    assert Submission.objects.filter(pk=fresh.pk).exists()


def test_different_forms_use_their_own_retention():
    tight_form = _make_form(retention_days=7)
    loose_form = _make_form(retention_days=90)
    tight_expired = _make_submission(tight_form, age_days=10)
    loose_fresh = _make_submission(loose_form, age_days=10)

    call_command("purge_expired_submissions")

    assert not Submission.objects.filter(pk=tight_expired.pk).exists()
    assert Submission.objects.filter(pk=loose_fresh.pk).exists()


def test_keeps_usage_events():
    form_obj = _make_form()
    expired = _make_submission(form_obj, age_days=31)
    UsageEvent.objects.create(account=form_obj.account, kind="submission", quantity=1)
    count_before = UsageEvent.objects.count()

    call_command("purge_expired_submissions")

    assert not Submission.objects.filter(pk=expired.pk).exists()
    assert UsageEvent.objects.count() == count_before


def test_dry_run_deletes_nothing_but_reports_count():
    form_obj = _make_form()
    expired = _make_submission(form_obj, age_days=31)

    out = StringIO()
    call_command("purge_expired_submissions", "--dry-run", stdout=out)

    assert Submission.objects.filter(pk=expired.pk).exists()
    assert "Would delete 1" in out.getvalue()


def test_real_run_reports_count():
    form_obj = _make_form()
    _make_submission(form_obj, age_days=31)
    _make_submission(form_obj, age_days=31)

    out = StringIO()
    call_command("purge_expired_submissions", stdout=out)

    assert "Deleted 2" in out.getvalue()


def test_batches_expired_deletes_with_small_batch_size():
    form_obj = _make_form()
    for _ in range(5):
        _make_submission(form_obj, age_days=31)

    with CaptureQueriesContext(connection) as queries:
        call_command("purge_expired_submissions", "--batch-size", "2")

    savepoints = [q for q in queries if q["sql"].strip().upper().startswith("SAVEPOINT")]
    assert len(savepoints) >= 3
    assert Submission.objects.filter(form=form_obj).count() == 0


def test_never_touches_content_in_output():
    form_obj = _make_form()
    _make_submission(form_obj, age_days=31, payload={"secret": "do-not-leak-me-12345"})

    out = StringIO()
    call_command("purge_expired_submissions", stdout=out)

    assert "do-not-leak-me-12345" not in out.getvalue()
