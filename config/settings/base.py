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
