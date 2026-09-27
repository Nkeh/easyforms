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

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
COPY --from=tailwind-build /app/static/css/app.css ./static/css/app.css
RUN uv sync --frozen

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /var/lib/easyforms/artifacts /var/lib/easyforms/data \
    && chown -R appuser:appuser /app /var/lib/easyforms
USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "-c", "gunicorn.conf.py"]
