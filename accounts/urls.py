from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from accounts import views
from accounts.forms import EmailAuthenticationForm, TransactionalPasswordResetForm

app_name = "accounts"

urlpatterns = [
    path("signup", views.signup, name="signup"),
    path(
        "login",
        views.RateLimitedLoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=EmailAuthenticationForm,
        ),
        name="login",
    ),
    path("logout", auth_views.LogoutView.as_view(), name="logout"),
    path("verify/<str:token>", views.verify_email, name="verify"),
    path("resend-verification", views.resend_verification, name="resend_verification"),
    path("settings", views.settings_view, name="settings"),
    path(
        "reset",
        views.RateLimitedPasswordResetView.as_view(
            form_class=TransactionalPasswordResetForm,
            subject_template_name="notifications/email/password_reset_subject.txt",
            template_name="accounts/password_reset_form.html",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "reset/done",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/complete",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
