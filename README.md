# easyforms

Hosted form backend with ML spam filtering. Static/JAMstack sites `POST` forms
to `/f/{token}`; the backend validates, spam-scores, stores, and emails the
form owner.

- Requirements source of truth: [`docs/SRS.md`](docs/SRS.md) (FR-x.x / NFR-x
  IDs referenced throughout the codebase and this doc).
- Contributor workflow, non-negotiable rules, app layout: [`CLAUDE.md`](CLAUDE.md).
- Production operations runbook (deploy, rollback, restore, secret rotation):
  [`docs/runbook.md`](docs/runbook.md).

## Stack

Python 3.12 · Django 5.x · PostgreSQL 16 · Redis + RQ (django-rq) · Django
templates + Tailwind + HTMX · scikit-learn spam model (artifacts in Cloudflare
R2 via boto3) · email via Postmark/Resend/SendGrid (django-anymail) · Sentry.
Dependencies managed with `uv` (`pyproject.toml` / `uv.lock`); linted/formatted
with `ruff`; tested with `pytest-django`.

## Dev stack services

| Service    | What it runs                                              | Host port(s)        |
|------------|------------------------------------------------------------|----------------------|
| `web`      | `python manage.py runserver` (Django, `settings.local`)    | `8000`               |
| `worker`   | `python manage.py rqworker emails default` (RQ worker)     | —                    |
| `mailpit`  | Catches outgoing dev email — SMTP + a web UI to read it     | `1025` (SMTP), `8025` (UI) |
| `tailwind` | Tailwind CLI, watches `static_src/css/input.css` → `static/css/app.css` | — |
| `db`       | PostgreSQL 16                                               | `5432`               |
| `redis`    | Redis 7                                                     | —                    |

`web` and `worker` share two named volumes: `artifacts` (spam model artifacts)
and `training_data` (spam training corpus cache).

## Prerequisites

- Docker and Docker Compose (v2 `docker compose` CLI).
- `make` — optional. It's a thin wrapper around `docker compose` commands (see
  the [`Makefile`](Makefile)). **On Windows, `make` usually isn't installed by
  default**; every `make <target>` below has its raw `docker compose`
  equivalent shown alongside it, so PowerShell users can skip `make`
  entirely.

## Quickstart (first-time local setup)

```
cp .env.example .env
```

```
make up                      # == docker compose up --build
```

Leave that running (first run also builds the image), and in a second
terminal, once `db`/`redis` report healthy:

```
make migrate                 # == docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
make test                    # == docker compose run --rm web pytest
make lint                    # == docker compose run --rm web sh -c "ruff check . && ruff format --check ."
```

Then:

- App health check: <http://localhost:8000/healthz>
- Admin site: <http://localhost:8000/admin/> (log in with the superuser you
  just created — admin path defaults to `admin/` locally; see
  [Environment variables](#environment-variables-local-dev))
- Dev email inbox (mailpit UI): <http://localhost:8025>

No external accounts (R2, a real email provider) are required for this
default setup — see [Local setup variants](#local-setup-variants) below for
how to opt into those.

## Day-to-day dev commands

| Task                          | `make` target        | Raw `docker compose` equivalent                                              |
|--------------------------------|-----------------------|---------------------------------------------------------------------------------|
| Start the full stack           | `make up`             | `docker compose up --build`                                                     |
| Stop the stack                 | `make down`           | `docker compose down`                                                            |
| Run the test suite             | `make test`           | `docker compose run --rm web pytest`                                            |
| Lint + format-check             | `make lint`           | `docker compose run --rm web sh -c "ruff check . && ruff format --check ."`     |
| Auto-format                    | `make fmt`            | `docker compose run --rm web ruff format .`                                     |
| Apply migrations                | `make migrate`        | `docker compose run --rm web python manage.py migrate`                         |
| Create migrations               | `make makemigrations` | `docker compose run --rm web python manage.py makemigrations`                  |
| Django shell                    | `make shell`          | `docker compose run --rm web python manage.py shell`                            |

Commands that don't have a `make` target:

```
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web pytest path/to/test_file.py::TestClass::test_name   # a single test
docker compose logs -f worker                                                   # tail the RQ worker
docker compose run --rm web python manage.py <any management command>
```

The `tailwind` service already watches `static_src/css/input.css` and rebuilds
`static/css/app.css` on save — no manual build step needed while `make up` is
running.

## Environment variables (local dev)

[`.env.example`](.env.example) is the single source of truth for local env
vars — every variable is commented in place with what it's for and why its
default is what it is. `cp .env.example .env` and (for the default setup
below) you don't need to change anything. The groups, briefly:

- **Django core** — `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`
- **Database** — `POSTGRES_*`, `DATABASE_URL`
- **Redis / RQ** — `REDIS_URL` plus timeout/circuit-breaker tuning
- **Privacy** — `IP_HASH_SECRET`, the HMAC key used to hash submitter IPs
  (raw IPs are never stored — rule 5 in `CLAUDE.md`)
- **Email** — `EMAIL_PROVIDER` (`smtp` locally, talks to `mailpit`) plus
  SMTP settings and the three anymail provider API keys (only the active
  provider's key is read)
- **Ingest & auth rate limits** — request-size ceilings and per-IP/per-token/
  per-email rate limit windows
- **Spam model & artifact storage** — `ARTIFACT_STORAGE` (`local` vs `s3`/R2),
  model refresh/timing-heuristic tuning, `SPAM_MODEL_MODE`
- **Backups** — `BACKUP_STORAGE` (`local` vs `s3`/R2), using a credential set
  deliberately separate from the artifact storage one
- **Sentry** — `SENTRY_DSN` (blank disables it entirely, the local default)

**Never commit a real secret.** `.env` is git-ignored; `.env.example` and
`.env.production.example` hold placeholder/dummy values only (rule 12 in
`CLAUDE.md`). If you add a new env var, add it to `.env.example` too.

## Local setup variants

The default `cp .env.example .env` setup needs zero external accounts. A few
things can be swapped in for testing closer to production:

- **Real R2 storage instead of local volumes** — set `ARTIFACT_STORAGE=s3`
  (model artifacts) and/or `BACKUP_STORAGE=s3` (backups) in `.env` and fill in
  the matching `R2_*` / `BACKUP_R2_*` credentials and bucket name for a
  scratch bucket. Same code path as production, just pointed at a bucket you
  don't mind breaking.
- **A real email provider instead of mailpit** — set `EMAIL_PROVIDER` to
  `postmark`, `resend`, or `sendgrid` and fill in the matching API key
  (`POSTMARK_SERVER_TOKEN` / `RESEND_API_KEY` / `SENDGRID_API_KEY`). Useful for
  checking actual deliverability instead of reading mail out of mailpit.
- **Bootstrapping the spam model locally** — ingest scores submissions
  `spam_score = null` (heuristics only) until a `ModelVersion` is trained and
  activated. Run:
  ```
  docker compose run --rm web python manage.py train_spam_model --activate
  ```
  (or `train_spam_model` + `eval_spam_model <version>` +
  `activate_spam_model <version>` as separate steps — see
  [`docs/runbook.md`](docs/runbook.md) for the production version of this
  flow). Without this, a fresh clone's spam scoring stays heuristics-only,
  which is fine for most dev work but worth knowing about.
- **One-off management commands** — run any Django management command the
  same way: `docker compose run --rm web python manage.py <command>`.

## Testing & linting

```
make test   # == docker compose run --rm web pytest
make lint   # == docker compose run --rm web sh -c "ruff check . && ruff format --check ."
make fmt    # == docker compose run --rm web ruff format .
```

Config lives in `pyproject.toml` if you want IDE integration: pytest uses
`DJANGO_SETTINGS_MODULE=config.settings.local` and discovers `test_*.py` /
`tests.py`; ruff targets py312 at line-length 100 with `migrations/` excluded.

## Production

Production runs via [`docker-compose.prod.yml`](docker-compose.prod.yml): a
gunicorn `web` service, an RQ `worker`, a `scheduler` (supercronic running
`deploy/crontab` — notifications, submission purging, spam reporting, nightly
backups), `db`, `redis`, and a `caddy` reverse proxy handling TLS. All of
`web`/`worker`/`scheduler` build from the same multi-stage `Dockerfile` used
locally.

**This section documents what's safe to put in a repo** — variable names,
purposes, and non-secret defaults, matching what's already committed in
[`.env.production.example`](.env.production.example). It does not and should
not contain real secret values; those only ever exist in a server-side `.env`
that is never committed (rule 12 in `CLAUDE.md`). `.env.production.example`'s
comments include the exact `secrets.token_urlsafe(...)` commands for
generating `SECRET_KEY`, `POSTGRES_PASSWORD`, and `IP_HASH_SECRET`.

For step-by-step procedures — first deploy, routine deploy, rollback, backup
restore drills, secret rotation — see [`docs/runbook.md`](docs/runbook.md).
For requirement-level rationale, see section 12 of [`docs/SRS.md`](docs/SRS.md).

### Production environment variables

| Group | Variables | Purpose |
|---|---|---|
| Django / security | `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `ADMIN_URL`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `SECURE_SSL_REDIRECT` | Core Django config, CSRF origin checking (Caddy terminates TLS), an unguessable admin path, HSTS rollout |
| Database | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL` | PostgreSQL connection |
| Redis / RQ | `REDIS_URL`, `REDIS_TIMEOUT_SECONDS`, `REDIS_BREAKER_SECONDS` | Queue + rate-limit backing store, with a circuit breaker so a Redis outage fails fast (NFR-1) |
| Privacy | `IP_HASH_SECRET` | HMAC key for hashing submitter IPs — raw IPs are never stored (rule 5) |
| Email | `DEFAULT_FROM_EMAIL`, `EMAIL_PROVIDER`, `POSTMARK_SERVER_TOKEN` / `RESEND_API_KEY` / `SENDGRID_API_KEY` | Outbound notification email via a real provider — never `console`/`smtp` in production |
| Ingest limits | `INGEST_MAX_BODY_BYTES`, `INGEST_MAX_FIELDS`, `INGEST_MAX_FIELD_CHARS`, `INGEST_MAX_KEY_CHARS`, `INGEST_RATE_LIMIT_*` | Request-size ceilings (FR-3.2/3.6) and per-IP/per-token rate limits (FR-7.1) |
| Auth limits | `AUTH_RATE_LIMIT_*` | Credential-stuffing protection on login/signup/reset |
| Spam model & artifacts | `ARTIFACT_STORAGE`, `MODEL_ARTIFACT_DIR`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `SPAM_DATASET_DIR`, `SPAM_MODEL_REFRESH_SECONDS`, `SPAM_MIN_SUBMIT_SECONDS`, `SPAM_FAST_SUBMIT_MARGIN`, `SPAM_MODEL_MODE`, `SPAM_FP_ALERT_RATE`, `SPAM_ALERT_MIN_ROWS` | Model artifact storage (R2 in prod) and spam-scoring tuning/monitoring |
| Backups | `BACKUP_STORAGE`, `BACKUP_LOCAL_DIR`, `BACKUP_R2_ACCOUNT_ID`, `BACKUP_R2_ACCESS_KEY_ID`, `BACKUP_R2_SECRET_ACCESS_KEY`, `BACKUP_BUCKET` | Nightly DB backup storage, using an R2 credential set deliberately separate from the artifact one — a leaked artifact token can't also read/write backups |
| Deploy/runtime | `PUBLIC_BASE_URL`, `TRUSTED_PROXY_COUNT`, `DOMAIN`, `WEB_CONCURRENCY`, `LOG_LEVEL` | Form endpoint URL generation, proxy trust depth, Caddy's ACME domain, gunicorn worker count, log verbosity |
| Sentry | `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_ENVIRONMENT` | Error tracking (NFR-10); blank DSN disables it entirely |

### Production safety behaviors worth knowing

- `config/settings/prod.py` **fails fast at boot** (`ImproperlyConfigured`) if
  `SECRET_KEY`, `IP_HASH_SECRET`, `DATABASE_URL`, `REDIS_URL`, or
  `PUBLIC_BASE_URL` still equal their `.env.example` dev-insecure values, or
  if `ALLOWED_HOSTS` is empty/`["*"]`.
- `ADMIN_URL` and `CSRF_TRUSTED_ORIGINS` have **no default** in production —
  they must be set explicitly.
- `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` default to
  `False`. `PRELOAD` in particular is submitted to browser vendors' preload
  lists and is effectively irreversible — only enable it deliberately, on a
  domain you own every subdomain of.
- Database restores must **never** target the live `DATABASE_URL` directly —
  `manage.py restore` has no default target and requires an explicit
  `--database-url`, by design. See the restore drill in `docs/runbook.md`.
