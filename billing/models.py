from django.db import models

from accounts.models import Account


class UsageEvent(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="usage_events")
    kind = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["account", "kind", "created_at"]),
        ]

    def __str__(self):
        return f"{self.account_id} {self.kind} x{self.quantity}"
