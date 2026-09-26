from django.conf import settings

from core.ratelimit import RateResult, combine, hit


def check_login_limit(ip_hash: str, email: str) -> RateResult:
    return combine(
        hit("auth_login_ip", ip_hash, settings.AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE, 60),
        hit("auth_login_email", email, settings.AUTH_RATE_LIMIT_LOGIN_EMAIL_PER_MINUTE, 60),
    )


def check_signup_limit(ip_hash: str) -> RateResult:
    return hit("auth_signup_ip", ip_hash, settings.AUTH_RATE_LIMIT_SIGNUP_IP_PER_HOUR, 3600)


def check_reset_limit(ip_hash: str, email: str) -> RateResult:
    return combine(
        hit("auth_reset_ip", ip_hash, settings.AUTH_RATE_LIMIT_RESET_IP_PER_HOUR, 3600),
        hit("auth_reset_email", email, settings.AUTH_RATE_LIMIT_RESET_EMAIL_PER_HOUR, 3600),
    )
