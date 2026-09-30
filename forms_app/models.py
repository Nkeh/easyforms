import secrets
import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from accounts.models import Account
from billing.plans import retention_days_for


def generate_token() -> str:
    return secrets.token_urlsafe(16)


class Form(models.Model):
    class SpamAction(models.TextChoices):
        FLAG = "flag", "Flag"
        DROP = "drop", "Drop"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="forms")
    name = models.CharField(max_length=255)
    token = models.CharField(max_length=32, unique=True, editable=False, default=generate_token)
    allowed_origins = ArrayField(models.TextField(), default=list, blank=True)
    redirect_url = models.URLField(null=True, blank=True)
    spam_action = models.CharField(
        max_length=10, choices=SpamAction.choices, default=SpamAction.FLAG
    )
    # null = fall back to the plan default (NFR-6)
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def endpoint_url(self) -> str:
        return f"{settings.PUBLIC_BASE_URL}/f/{self.token}"

    @property
    def effective_retention_days(self) -> int:
        cap = retention_days_for(self.account)
        if self.retention_days is None:
            return cap
        return min(self.retention_days, cap)


class Submission(models.Model):
    class Status(models.TextChoices):
        HAM = "ham", "Ham"
        SPAM = "spam", "Spam"

    class NotificationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="submissions")
    payload = models.JSONField()
    # null = scored by heuristics only, no model probability available (rule 10)
    spam_score = models.FloatField(null=True, blank=True)
    # heuristic signal names that fired ("honeypot", "fast_submit", "model");
    # populated even in heuristics-only mode (fast_submit is observability-only there)
    spam_signals = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    # the system's decision at ingest time; never changed after creation
    # (FR-4.4 feedback loop needs the pre-correction label preserved)
    original_status = models.CharField(max_length=10, choices=Status.choices)
    # corrected = status != original_status, maintained on every label flip
    corrected = models.BooleanField(default=False)
    corrected_at = models.DateTimeField(null=True, blank=True)
    source_ip_hash = models.CharField(max_length=64)
    model_version = models.ForeignKey(
        "spam.ModelVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )
    # skipped = spam, or ham with no verified account user at store time
    # (FR-1.2) — a skip is permanent, never picked up later.
    notification_status = models.CharField(
        max_length=10,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
    )
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["form", "-created_at"]),
            models.Index(fields=["form", "status", "-created_at"]),
            models.Index(fields=["notification_status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.form_id} ({self.status})"
