from django.contrib import admin

from spam.models import ModelVersion


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "is_active", "artifact_key", "created_at")
    list_filter = ("is_active",)
    search_fields = ("version",)
