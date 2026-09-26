import secrets
import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from accounts.models import Account


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


class Submission(models.Model):
    class Status(models.TextChoices):
        HAM = "ham", "Ham"
        SPAM = "spam", "Spam"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="submissions")
    payload = models.JSONField()
    # null = scored by heuristics only, no model probability available (rule 10)
    spam_score = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    corrected = models.BooleanField(default=False)
    source_ip_hash = models.CharField(max_length=64)
    model_version = models.ForeignKey(
        "spam.ModelVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["form", "-created_at"]),
            models.Index(fields=["form", "status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.form_id} ({self.status})"
