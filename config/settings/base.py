from pathlib import Path

import environ

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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis / RQ (async email + webhooks; the ingest path itself never blocks on these)
REDIS_URL = env("REDIS_URL")

RQ_QUEUES = {
    "default": {
        "URL": REDIS_URL,
    },
}

# Shared with RQ's Redis instance; KEY_PREFIX keeps our keys distinct from rq:* keys.
# Used for the resend-verification-email throttle (must be shared across gunicorn
# workers, so LocMemCache would not do).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "easyforms",
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
