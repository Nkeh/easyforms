import pytest

from accounts.models import Account
from billing.plans import get_plan, retention_choices_for, retention_days_for

pytestmark = pytest.mark.django_db


def _make_account(**kwargs):
    kwargs.setdefault("name", "Acme Inc")
    return Account.objects.create(**kwargs)


def test_get_plan_returns_free_plan_dict():
    account = _make_account()

    plan = get_plan(account)

    assert plan["retention_days"] == 30


def test_get_plan_falls_back_to_default_for_unknown_plan(caplog):
    account = _make_account(plan="nonexistent")

    with caplog.at_level("WARNING", logger="billing"):
        plan = get_plan(account)

    assert plan["retention_days"] == 30
    assert "unknown plan" in caplog.text


def test_retention_days_for_reads_plan_value():
    account = _make_account()

    assert retention_days_for(account) == 30


def test_retention_choices_for_caps_at_plan_value():
    account = _make_account()

    choices = retention_choices_for(account)

    assert choices == [7, 14, 30]
    assert max(choices) <= retention_days_for(account)
