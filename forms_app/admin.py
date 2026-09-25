from django.contrib import admin

from forms_app.models import Form, Submission


@admin.register(Form)
class FormAdmin(admin.ModelAdmin):
    list_display = ("name", "account", "token", "spam_action", "is_active", "created_at")
    list_filter = ("spam_action", "is_active")
    search_fields = ("name", "account__name")
    readonly_fields = ("token", "endpoint_path", "created_at", "updated_at")
    fields = (
        "account",
        "name",
        "token",
        "endpoint_path",
        "allowed_origins",
        "redirect_url",
        "spam_action",
        "retention_days",
        "is_active",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Endpoint path")
    def endpoint_path(self, obj):
        return f"/f/{obj.token}"


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("form", "status", "spam_score", "corrected", "created_at")
    list_filter = ("status", "corrected")
    search_fields = ("source_ip_hash", "form__name")
