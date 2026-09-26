from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.emails import send_verification_email
from accounts.forms import SignupForm
from accounts.models import User
from accounts.rate_limit import check_login_limit, check_reset_limit, check_signup_limit
from accounts.tokens import read_verification_token
from billing.limits import check_limit
from core.utils import hash_ip
from ingest.ip import get_client_ip

RESEND_VERIFICATION_COOLDOWN_SECONDS = 60


def _too_many_requests(request, retry_after):
    response = render(request, "rate_limited.html", status=429)
    response["Retry-After"] = str(retry_after)
    return response


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        ip_hash = hash_ip(get_client_ip(request))
        signup_limit = check_signup_limit(ip_hash)
        if not signup_limit.allowed:
            return _too_many_requests(request, signup_limit.retry_after)

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password"],
                )
        except IntegrityError:
            form.add_error("email", "This email is already registered.")
        else:
            login(request, user)
            send_verification_email(user, request)
            return redirect("dashboard:home")

    return render(request, "accounts/signup.html", {"form": form})


def verify_email(request, token):
    user_id = read_verification_token(token)
    user = User.objects.filter(pk=user_id).first() if user_id else None

    if user is None:
        return render(request, "accounts/verify_result.html", {"success": False})

    if not user.is_verified:
        user.is_verified = True
        user.save(update_fields=["is_verified"])

    return render(request, "accounts/verify_result.html", {"success": True})


@login_required
@require_POST
def resend_verification(request):
    user = request.user

    if user.is_verified:
        messages.info(request, "Your email is already verified.")
        return redirect("dashboard:home")

    cache_key = f"verify-resend:{user.id}"
    if cache.get(cache_key):
        messages.warning(
            request, "Please wait a minute before requesting another verification email."
        )
    else:
        cache.set(cache_key, True, timeout=RESEND_VERIFICATION_COOLDOWN_SECONDS)
        send_verification_email(user, request)
        messages.success(request, "Verification email sent.")

    return redirect("dashboard:home")


@login_required
def settings_view(request):
    account = request.user.account
    return render(
        request,
        "accounts/settings.html",
        {
            "account": account,
            "forms_limit": check_limit(account, "forms"),
            "submissions_limit": check_limit(account, "submissions"),
        },
    )


class RateLimitedLoginView(auth_views.LoginView):
    def post(self, request, *args, **kwargs):
        ip_hash = hash_ip(get_client_ip(request))
        email = (request.POST.get("username") or "").strip().lower()
        result = check_login_limit(ip_hash, email)
        if not result.allowed:
            return _too_many_requests(request, result.retry_after)
        return super().post(request, *args, **kwargs)


class RateLimitedPasswordResetView(auth_views.PasswordResetView):
    def post(self, request, *args, **kwargs):
        ip_hash = hash_ip(get_client_ip(request))
        email = (request.POST.get("email") or "").strip().lower()
        result = check_reset_limit(ip_hash, email)
        if not result.allowed:
            return _too_many_requests(request, result.retry_after)
        return super().post(request, *args, **kwargs)
