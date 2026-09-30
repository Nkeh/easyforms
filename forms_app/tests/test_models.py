import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings

from accounts.models import Account
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _make_form(**kwargs):
    account = kwargs.pop("account", None) or Account.objects.create(name="Acme Inc")
    return Form.objects.create(account=account, name="Contact form", **kwargs)


def test_token_is_auto_generated_and_non_empty():
    form = _make_form()

    assert form.token
    assert len(form.token) > 10


def test_token_is_unique_across_forms():
    account = Account.objects.create(name="Acme Inc")
    form_a = _make_form(account=account)
    form_b = _make_form(account=account)

    assert form_a.token != form_b.token


def test_duplicate_token_raises_integrity_error():
    account = Account.objects.create(name="Acme Inc")
    form = _make_form(account=account)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Form.objects.create(account=account, name="Other form", token=form.token)


def test_spam_action_defaults_to_flag():
    form = _make_form()

    assert form.spam_action == Form.SpamAction.FLAG


@override_settings(PUBLIC_BASE_URL="http://example.test")
def test_endpoint_url_is_built_from_public_base_url():
    form = _make_form()

    assert form.endpoint_url == f"http://example.test/f/{form.token}"


def test_effective_retention_days_falls_back_to_plan_when_unset():
    form = _make_form()

    assert form.retention_days is None
    assert form.effective_retention_days == 30


def test_effective_retention_days_uses_form_override():
    form = _make_form(retention_days=7)

    assert form.effective_retention_days == 7


def test_effective_retention_days_recaps_after_plan_downgrade(monkeypatch):
    import billing.plans

    pro_plan = {**billing.plans.PLANS["free"], "retention_days": 90}
    monkeypatch.setitem(billing.plans.PLANS, "pro", pro_plan)
    account = Account.objects.create(name="Acme Inc", plan="pro")
    form = _make_form(account=account, retention_days=90)
    assert form.effective_retention_days == 90

    account.plan = "free"
    account.save(update_fields=["plan"])
    form.refresh_from_db()

    assert form.effective_retention_days == 30


def test_deleting_account_cascades_to_forms_and_submissions():
    account = Account.objects.create(name="Acme Inc")
    form = _make_form(account=account)
    submission = Submission.objects.create(
        form=form,
        payload={"name": "Jane"},
        status=Submission.Status.HAM,
        original_status=Submission.Status.HAM,
        source_ip_hash="a" * 64,
    )

    account.delete()

    assert not Form.objects.filter(pk=form.pk).exists()
    assert not Submission.objects.filter(pk=submission.pk).exists()
