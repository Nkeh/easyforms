from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import Account, User


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "plan", "created_at")
    search_fields = ("name",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "account", "is_staff", "is_verified", "is_active")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Account", {"fields": ("account", "is_verified")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "account", "password1", "password2"),
            },
        ),
    )
    search_fields = ("email",)
    filter_horizontal = ("groups", "user_permissions")
