import logging

logger = logging.getLogger("billing")

PLANS = {
    "free": {
        "max_forms": 3,
        "max_submissions_per_month": 250,
        "retention_days": 30,
        "features": {
            "webhooks": False,
            "digest": False,
            "remove_branding": False,
        },
    },
}

DEFAULT_PLAN = "free"

# Candidate retention lengths an owner can pick for a form, filtered down to
# whatever their plan's own retention_days allows (NFR-6).
RETENTION_DAY_CHOICES = [7, 14, 30, 60, 90]


def get_plan(account):
    plan = PLANS.get(account.plan)
    if plan is None:
        logger.warning(
            "unknown plan %r for account %s; falling back to %s",
            account.plan,
            account.id,
            DEFAULT_PLAN,
        )
        plan = PLANS[DEFAULT_PLAN]
    return plan


def retention_days_for(account) -> int:
    return get_plan(account)["retention_days"]


def retention_choices_for(account) -> list[int]:
    cap = retention_days_for(account)
    return [days for days in RETENTION_DAY_CHOICES if days <= cap]
