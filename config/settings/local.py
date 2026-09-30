from .base import *  # noqa: F401,F403
from .base import env  # noqa: E402

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Dev-only default; prod.py requires this to be set explicitly (no default).
ADMIN_URL = env("ADMIN_URL", default="admin/")
