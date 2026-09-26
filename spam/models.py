import uuid

from django.db import models, transaction


class ModelVersionManager(models.Manager):
    def activate(self, model_version: "ModelVersion") -> None:
        with transaction.atomic():
            ModelVersion.objects.exclude(pk=model_version.pk).filter(is_active=True).update(
                is_active=False
            )
            model_version.is_active = True
            model_version.save(update_fields=["is_active"])


class ModelVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.CharField(max_length=100, unique=True)
    artifact_key = models.CharField(max_length=255)
    metrics = models.JSONField(default=dict, blank=True)
    threshold = models.FloatField(null=True, blank=True, default=None)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    sklearn_version = models.CharField(max_length=32, blank=True, default="")
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ModelVersionManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="unique_active_model_version",
            ),
        ]

    def __str__(self):
        return self.version
