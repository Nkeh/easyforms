# Standalone Tailwind CLI (no Node). Version pinned; SHA-256 pinned via
# TOFU (Tailwind doesn't publish per-binary checksums) — computed once from
# a verified download, hardcoded here so a tampered/changed binary fails the
# build loudly instead of being trusted silently.
FROM debian:bookworm-slim AS tailwind-cli
ARG TAILWIND_VERSION=3.4.17
ARG TAILWIND_SHA256=7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -sLo /usr/local/bin/tailwindcss \
       "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && echo "${TAILWIND_SHA256}  /usr/local/bin/tailwindcss" | sha256sum -c - \
    && chmod +x /usr/local/bin/tailwindcss \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["tailwindcss"]

# One-shot minified build for the final image. Content-scans every app's
# templates (docker-compose's `tailwind` service targets the tailwind-cli
# stage above instead, bind-mounted, for --watch during local dev).
FROM tailwind-cli AS tailwind-build
WORKDIR /app
COPY tailwind.config.js ./
COPY static_src/ ./static_src/
COPY templates/ ./templates/
COPY accounts/templates/ ./accounts/templates/
COPY forms_app/templates/ ./forms_app/templates/
COPY dashboard/templates/ ./dashboard/templates/
COPY ingest/templates/ ./ingest/templates/
RUN tailwindcss -c tailwind.config.js -i static_src/css/input.css -o static/css/app.css --minify

# Scheduler binary (Day 13a). supercronic only publishes a SHA1SUM in its
# release notes (no dedicated checksums file), so the download is verified
# against that upstream-published SHA1 first, and the resulting SHA256 below
# was computed once from that verified download and hardcoded — same TOFU
# rationale as the Tailwind stage above, but starting from a real upstream
# checksum instead of a bare download.
FROM debian:bookworm-slim AS supercronic
ARG SUPERCRONIC_VERSION=v0.2.49
ARG SUPERCRONIC_SHA1=e63c11a9726b775a6a11801e81af4f3fb926aa68
ARG SUPERCRONIC_SHA256=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -sLo /usr/local/bin/supercronic \
       "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && echo "${SUPERCRONIC_SHA1}  /usr/local/bin/supercronic" | sha1sum -c - \
    && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
    && chmod +x /usr/local/bin/supercronic \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# postgresql-client-16 (matches the `db` service's postgres:16 image — the
# base image's own postgresql-client package tracks whatever Postgres was
# current for its Debian release, a version-skew risk for pg_dump/pg_restore)
# from the official PGDG apt repo, keyed off the base image's own Debian
# codename (VERSION_CODENAME) rather than a hardcoded one — python:3.12-slim
# tracks Debian's current stable, which has moved across the life of this
# project. curl is also for the web healthcheck; procps for pgrep in the
# worker/scheduler healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg procps \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=supercronic /usr/local/bin/supercronic /usr/local/bin/supercronic
COPY --chmod=644 deploy/crontab /etc/easyforms/crontab

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
COPY --from=tailwind-build /app/static/css/app.css ./static/css/app.css
RUN uv sync --frozen

# collectstatic needs prod.py's WhiteNoise STORAGES config to build the
# hashed manifest, but prod.py fail-fasts without real secrets — build.py
# supplies build-only placeholders for exactly that (see its docstring).
RUN DJANGO_SETTINGS_MODULE=config.settings.build python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /var/lib/easyforms/artifacts /var/lib/easyforms/data /var/lib/easyforms/backups \
    && chown -R appuser:appuser /app /var/lib/easyforms
USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "-c", "gunicorn.conf.py"]
