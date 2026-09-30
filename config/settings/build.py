"""collectstatic-only settings, used solely at Docker image build time.

`prod.py` fail-fasts (ImproperlyConfigured) if its required secrets/URLs are
missing or still carry their insecure dev-default values, so it can't be
imported with no `.env` present — which is exactly the situation during
`docker build` (no real secrets exist yet, and shouldn't be baked into the
image). These placeholders satisfy the fail-fast checks without being
dev-default lookalikes; nothing here is ever used to actually run the app,
only to let `manage.py collectstatic` load `prod.py`'s STORAGES/WhiteNoise
config and build the hashed static manifest.
"""

import os

os.environ.setdefault("SECRET_KEY", "build-time-placeholder-not-used-at-runtime")
os.environ.setdefault("IP_HASH_SECRET", "build-time-placeholder-not-used-at-runtime")
os.environ.setdefault("DATABASE_URL", "postgres://build:build@build-placeholder:5432/build")
os.environ.setdefault("REDIS_URL", "redis://build-placeholder:6379/0")
os.environ.setdefault("PUBLIC_BASE_URL", "https://build-placeholder.invalid")
os.environ.setdefault("ALLOWED_HOSTS", "build-placeholder.invalid")
os.environ.setdefault("ADMIN_URL", "admin/")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "https://build-placeholder.invalid")

from .prod import *  # noqa: F401,F403,E402
