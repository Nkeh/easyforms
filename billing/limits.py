from dataclasses import dataclass

from django.db.models import Sum
from django.utils import timezone

from billing.models import UsageEvent
from billing.plans import get_plan


@dataclass
class LimitResult:
    allowed: bool
    used: int
    limit: int


def _plan_config(account):
    return get_plan(account)


def _submissions_this_month(account) -> int:
    start_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = UsageEvent.objects.filter(
        account=account, kind="submission", created_at__gte=start_of_month
    ).aggregate(total=Sum("quantity"))["total"]
    return total or 0


def check_limit(account, kind: str) -> LimitResult:
    plan = _plan_config(account)

    if kind == "forms":
        limit = plan["max_forms"]
        used = account.forms.filter(is_active=True).count()
    elif kind == "submissions":
        limit = plan["max_submissions_per_month"]
        used = _submissions_this_month(account)
    else:
        raise ValueError(f"unknown limit kind: {kind!r}")

    return LimitResult(allowed=used < limit, used=used, limit=limit)


def has_feature(account, name: str) -> bool:
    return _plan_config(account)["features"].get(name, False)
