from pathlib import Path
from urllib.parse import urlparse

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django_rq",
    "anymail",
    "core",
    "accounts",
    "billing",
    "forms_app",
    "ingest",
    "spam",
    "notifications",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL"),
}

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="EasyForms <noreply@easyforms.example>")

# Email transport (Day 10, FR-5). EMAIL_PROVIDER selects EMAIL_BACKEND:
# "console"/"smtp" use Django's own backends (dev talks to the mailpit
# service in docker-compose over smtp); "postmark"/"resend"/"sendgrid" use
# django-anymail's HTTP-API backends in prod. Validated at boot, like
# SPAM_MODEL_MODE below, so a typo fails the process once loudly rather than
# at first send.
EMAIL_PROVIDER = env("EMAIL_PROVIDER", default="console")
_EMAIL_BACKENDS = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
    "postmark": "anymail.backends.postmark.EmailBackend",
    "resend": "anymail.backends.resend.EmailBackend",
    "sendgrid": "anymail.backends.sendgrid.EmailBackend",
}
if EMAIL_PROVIDER not in _EMAIL_BACKENDS:
    raise ImproperlyConfigured(
        f"EMAIL_PROVIDER must be one of {sorted(_EMAIL_BACKENDS)}, got {EMAIL_PROVIDER!r}"
    )
EMAIL_BACKEND = _EMAIL_BACKENDS[EMAIL_PROVIDER]

# Only read when EMAIL_PROVIDER=smtp (mailpit in dev; a real relay in prod).
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)

# django-anymail API keys. Only the one matching EMAIL_PROVIDER is ever read;
# dummy/empty values are harmless for the other two providers.
ANYMAIL = {
    "POSTMARK_SERVER_TOKEN": env("POSTMARK_SERVER_TOKEN", default=""),
    "RESEND_API_KEY": env("RESEND_API_KEY", default=""),
    "SENDGRID_API_KEY": env("SENDGRID_API_KEY", default=""),
}

# Base URL used to build public endpoint links (e.g. Form.endpoint_url); never
# derived from the request host so links stay stable regardless of Host header.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8000")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis / RQ (async email + webhooks; the ingest path itself never blocks on these)
REDIS_URL = env("REDIS_URL")

# Bounds how long any single Redis call (connect or read/write) can block a
# request. Every Redis client in the app (core.ratelimit, the RQ connection,
# the cache backend, /healthz) is configured with this, so a real Redis
# outage fails fast instead of hanging the ingest path for many seconds
# (NFR-1). core.circuit_breaker then stops most requests from even
# attempting a connection during a sustained outage — see REDIS_BREAKER_SECONDS.
REDIS_TIMEOUT_SECONDS = env.float("REDIS_TIMEOUT_SECONDS", default=0.3)

# Once any Redis call fails, core.circuit_breaker opens for this long: the
# rate limiter fails open and the notification enqueue path leaves the
# submission pending, both without attempting Redis at all, until it closes
# again and the next call re-probes.
REDIS_BREAKER_SECONDS = env.float("REDIS_BREAKER_SECONDS", default=5)

# django-rq's "URL" connection style (redis_cls.from_url(...)) doesn't
# forward extra client kwargs, so REDIS_TIMEOUT_SECONDS is applied via the
# HOST/PORT/REDIS_CLIENT_KWARGS style instead — same Redis instance, just a
# config shape django-rq will actually pass socket timeouts through on.
_redis_url_parts = urlparse(REDIS_URL)
_REDIS_CONNECTION_CONFIG = {
    "HOST": _redis_url_parts.hostname,
    "PORT": _redis_url_parts.port or 6379,
    "DB": int((_redis_url_parts.path or "/0").lstrip("/") or 0),
    "PASSWORD": _redis_url_parts.password,
    "REDIS_CLIENT_KWARGS": {
        "socket_connect_timeout": REDIS_TIMEOUT_SECONDS,
        "socket_timeout": REDIS_TIMEOUT_SECONDS,
    },
}

RQ_QUEUES = {
    "default": dict(_REDIS_CONNECTION_CONFIG),
    "emails": dict(_REDIS_CONNECTION_CONFIG),
}

# Shared with RQ's Redis instance; KEY_PREFIX keeps our keys distinct from rq:* keys.
# Used for the resend-verification-email throttle (must be shared across gunicorn
# workers, so LocMemCache would not do).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "easyforms",
        "OPTIONS": {
            "socket_connect_timeout": REDIS_TIMEOUT_SECONDS,
            "socket_timeout": REDIS_TIMEOUT_SECONDS,
        },
    }
}

# HMAC key for hashing submitter IPs before storage (CLAUDE.md rule 5)
IP_HASH_SECRET = env("IP_HASH_SECRET")

# Number of trusted reverse-proxy hops in front of the app. 0 = trust
# REMOTE_ADDR directly; N > 0 = take the Nth address from the right of
# X-Forwarded-For (client-supplied entries beyond that are never trusted).
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)

# Logging (NFR-10). stdout, stdlib-only, key=value formatter. Never logs
# payload or IP — enforced by convention at each app's log call sites
# (see ingest.views._log), not by this config.
LOG_LEVEL = env("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "keyvalue": {
            "format": "level=%(levelname)s logger=%(name)s message=%(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "keyvalue",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        name: {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False}
        for name in (
            "django",
            "core",
            "accounts",
            "billing",
            "forms_app",
            "ingest",
            "spam",
            "notifications",
            "dashboard",
        )
    },
}

# Ingest request-size limits (FR-3.2, FR-3.6). Requests exceeding any of
# these are rejected with 413 payload_too_large before being stored.
INGEST_MAX_BODY_BYTES = env.int("INGEST_MAX_BODY_BYTES", default=65536)
INGEST_MAX_FIELDS = env.int("INGEST_MAX_FIELDS", default=50)
INGEST_MAX_FIELD_CHARS = env.int("INGEST_MAX_FIELD_CHARS", default=10000)
INGEST_MAX_KEY_CHARS = env.int("INGEST_MAX_KEY_CHARS", default=100)

# Keep Django's own body-size/field-count ceilings aligned with the ingest
# limits above so its form/multipart parser (request.POST/.FILES) enforces
# the same ceiling instead of a different, unformatted one. This does NOT
# protect the JSON path — Django only checks these inside POST/FILES parsing,
# never on raw request.body — ingest.parsing._cap_body covers JSON instead.
DATA_UPLOAD_MAX_MEMORY_SIZE = INGEST_MAX_BODY_BYTES
DATA_UPLOAD_MAX_NUMBER_FIELDS = INGEST_MAX_FIELDS

# Ingest rate limits (FR-7.1). Fixed windows, checked via core.ratelimit.hit().
INGEST_RATE_LIMIT_IP_PER_MINUTE = env.int("INGEST_RATE_LIMIT_IP_PER_MINUTE", default=10)
INGEST_RATE_LIMIT_IP_PER_HOUR = env.int("INGEST_RATE_LIMIT_IP_PER_HOUR", default=100)
INGEST_RATE_LIMIT_TOKEN_PER_MINUTE = env.int("INGEST_RATE_LIMIT_TOKEN_PER_MINUTE", default=60)
INGEST_RATE_LIMIT_TOKEN_PER_HOUR = env.int("INGEST_RATE_LIMIT_TOKEN_PER_HOUR", default=1000)

# Auth rate limits (SRS section 11 — credential-stuffing protection).
AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE = env.int("AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE", default=10)
AUTH_RATE_LIMIT_LOGIN_EMAIL_PER_MINUTE = env.int(
    "AUTH_RATE_LIMIT_LOGIN_EMAIL_PER_MINUTE", default=5
)
AUTH_RATE_LIMIT_SIGNUP_IP_PER_HOUR = env.int("AUTH_RATE_LIMIT_SIGNUP_IP_PER_HOUR", default=5)
AUTH_RATE_LIMIT_RESET_IP_PER_HOUR = env.int("AUTH_RATE_LIMIT_RESET_IP_PER_HOUR", default=5)
AUTH_RATE_LIMIT_RESET_EMAIL_PER_HOUR = env.int("AUTH_RATE_LIMIT_RESET_EMAIL_PER_HOUR", default=3)

# Model artifact storage (Day 8 — SRS section 7). 'local' for dev/CI; 's3'
# talks to Cloudflare R2 via boto3's S3-compatible API. MODEL_ARTIFACT_DIR
# doubles as the local load-time cache regardless of backend (CLAUDE.md rule
# 10 — model boot must not require R2 reachability). Lives outside /app (and
# so outside the docker-compose bind mount) so the Dockerfile can create and
# chown it for appuser before a fresh named volume is first mounted there.
ARTIFACT_STORAGE = env("ARTIFACT_STORAGE", default="local")
MODEL_ARTIFACT_DIR = env("MODEL_ARTIFACT_DIR", default="/var/lib/easyforms/artifacts")
R2_ACCOUNT_ID = env("R2_ACCOUNT_ID", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
R2_BUCKET = env("R2_BUCKET", default="")

# Cache dir for the training corpus downloaded by `train_spam_model` (Day 8).
# Same rationale as MODEL_ARTIFACT_DIR: outside /app so the Dockerfile can
# pre-create and chown it for appuser.
SPAM_DATASET_DIR = env("SPAM_DATASET_DIR", default="/var/lib/easyforms/data")

# Spam scoring (Day 9, SRS FR-4). SPAM_MODEL_REFRESH_SECONDS bounds how stale the
# in-process scorer's active ModelVersion can be. The other two tune the _ts
# heuristic (CLAUDE.md rule 9 — soft/spoofable, never a hard signal on its own).
SPAM_MODEL_REFRESH_SECONDS = env.int("SPAM_MODEL_REFRESH_SECONDS", default=60)
SPAM_MIN_SUBMIT_SECONDS = env.float("SPAM_MIN_SUBMIT_SECONDS", default=3)
SPAM_FAST_SUBMIT_MARGIN = env.float("SPAM_FAST_SUBMIT_MARGIN", default=0.25)

# Day 9b — "auto" enforces the active model only if its stored
# metrics["form_sanity"]["passed"] is true (see spam/gate.py), otherwise
# shadows it (scores/logs without blocking real ham); "enforce"/"shadow"
# force one behavior regardless of gate state. Validated at boot (not per
# request) so a typo'd env var fails the whole process once, loudly, rather
# than every submission.
SPAM_MODEL_MODE = env("SPAM_MODEL_MODE", default="auto")
if SPAM_MODEL_MODE not in {"auto", "enforce", "shadow"}:
    raise ImproperlyConfigured(
        f"SPAM_MODEL_MODE must be one of auto/enforce/shadow, got {SPAM_MODEL_MODE!r}"
    )
