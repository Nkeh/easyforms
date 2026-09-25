from django.contrib import admin

from billing.models import UsageEvent


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    list_display = ("account", "kind", "quantity", "created_at")
    list_filter = ("kind",)
    search_fields = ("account__name",)
