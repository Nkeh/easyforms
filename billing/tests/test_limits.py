from datetime import datetime

import pytest
from django.utils import timezone

from accounts.models import Account
from billing.limits import check_limit, has_feature
from billing.models import UsageEvent
from forms_app.models import Form

pytestmark = pytest.mark.django_db


def _make_account(**kwargs):
    kwargs.setdefault("name", "Acme Inc")
    return Account.objects.create(**kwargs)


def test_forms_limit_counts_only_active_forms():
    account = _make_account()
    Form.objects.create(account=account, name="Active 1")
    Form.objects.create(account=account, name="Active 2")
    Form.objects.create(account=account, name="Inactive", is_active=False)

    result = check_limit(account, "forms")

    assert result.used == 2
    assert result.limit == 3
    assert result.allowed is True


def test_forms_limit_denies_at_limit():
    account = _make_account()
    for i in range(3):
        Form.objects.create(account=account, name=f"Form {i}")

    result = check_limit(account, "forms")

    assert result.used == 3
    assert result.limit == 3
    assert result.allowed is False


def test_submissions_limit_sums_current_month_quantity_only():
    account = _make_account()
    for _ in range(5):
        UsageEvent.objects.create(account=account, kind="submission", quantity=1)

    old_event = UsageEvent.objects.create(account=account, kind="submission", quantity=1)
    last_month = timezone.make_aware(datetime(2020, 1, 1))
    UsageEvent.objects.filter(pk=old_event.pk).update(created_at=last_month)

    UsageEvent.objects.create(account=account, kind="other", quantity=1)

    result = check_limit(account, "submissions")

    assert result.used == 5
    assert result.limit == 250
    assert result.allowed is True


def test_unknown_plan_falls_back_to_free_and_logs_warning(caplog):
    account = _make_account(plan="nonexistent")

    with caplog.at_level("WARNING", logger="billing"):
        result = check_limit(account, "forms")

    assert result.limit == 3
    assert "unknown plan" in caplog.text


def test_has_feature_reads_plan_flag():
    account = _make_account()

    assert has_feature(account, "webhooks") is False
    assert has_feature(account, "not_a_real_feature") is False
