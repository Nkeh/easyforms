from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, BASE_DIR, MIDDLEWARE, env  # noqa: E402

DEBUG = False

# Fail fast (rather than boot with a silently insecure config) if any of
# these still carry the exact insecure value shipped in .env.example. The
# underlying env(...) calls in base.py already raise ImproperlyConfigured if
# SECRET_KEY/IP_HASH_SECRET/DATABASE_URL/REDIS_URL are missing outright (no
# default there); PUBLIC_BASE_URL has a dev default so needs its own check.
_DEV_DEFAULTS = {
    "SECRET_KEY": "dev-insecure-secret-key-change-me",
    "IP_HASH_SECRET": "dev-insecure-ip-hash-secret-change-me",
    "DATABASE_URL": "postgres://easyforms:easyforms@db:5432/easyforms",
    "REDIS_URL": "redis://redis:6379/0",
    "PUBLIC_BASE_URL": "http://localhost:8000",
}
for _var_name, _dev_value in _DEV_DEFAULTS.items():
    if env(_var_name) == _dev_value:
        raise ImproperlyConfigured(
            f"{_var_name} is still set to its insecure dev default; set a real value in production"
        )

if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["*"]:
    raise ImproperlyConfigured("ALLOWED_HOSTS must list specific hostnames in production")

# No dev default here (unlike local.py) — an operator must choose explicitly.
ADMIN_URL = env("ADMIN_URL")

# Needed because Caddy terminates TLS in front of the app: Django's CSRF
# origin check compares the request's Origin/Referer against this list.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")
if not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS must be set in production")

MIDDLEWARE = [MIDDLEWARE[0], "whitenoise.middleware.WhiteNoiseMiddleware", *MIDDLEWARE[1:]]

# Only needed once `collectstatic` is actually run (dev's runserver serves
# straight from STATICFILES_DIRS and never touches this).
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Caddy is the one reverse proxy in front of the app (TRUSTED_PROXY_COUNT=1).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True

# Start conservative (1 day) — raise via env once DNS/redirect behavior is
# confirmed safe; HSTS is hard to fully undo for clients that already cached it.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24)
# Default off — subdomains/preload are hard-to-reverse opt-ins (see
# docs/runbook.md), only set deliberately on a domain the operator owns.
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
