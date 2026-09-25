import pytest

from accounts.models import Account
from billing.models import UsageEvent

pytestmark = pytest.mark.django_db


def test_usage_event_quantity_defaults_to_one():
    account = Account.objects.create(name="Acme Inc")

    event = UsageEvent.objects.create(account=account, kind="submission")

    assert event.quantity == 1
