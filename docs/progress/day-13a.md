# Day 13a — Production readiness (provider-agnostic, verified locally)

## Summary

Makes the codebase built on Days 1–12 safe to actually run in production
(SRS §12), with no real cloud deploy yet: `config/settings/prod.py` fails
loudly (`ImproperlyConfigured`) instead of booting with a dev-insecure
default; static files are served by WhiteNoise with a hashed, long-cache
manifest built at image-build time; styled 404/500 pages render even with no
DB/request context; Sentry is wired with a `before_send` scrubber that
never lets a submission payload leave the process (CLAUDE.md rule 4);
`send_pending_notifications`/`purge_expired_submissions`/`spam_report`/
`backup` are now actually scheduled via a `supercronic` service; and a real
`pg_dump`/`pg_restore` backup/restore path exists with its own credential
set. Also includes one Day-12 review fix: `Form.effective_retention_days`
now re-caps against the account's *current* plan, so a plan downgrade can't
leave a form's retention above the new cap.

Full plan this was built from:
`C:\Users\USER\.claude\plans\happy-whistling-badger.md`.

**Important caveat — live verification incomplete this session.** Docker
Desktop's engine was unstable for most of this session (wouldn't start, then
came back with its containerd storage stuck read-only, blocking *new*
container creation while already-running containers kept working). I
verified everything possible without new containers (see "Test results"
below), including a full dev-image build via `docker compose build` (which
succeeded), but could not run `manage.py migrate`, the full `pytest` suite,
or bring up `docker-compose.prod.yml` end-to-end. The exact commands to
finish that pass are in "How to verify manually" — please run them once
Docker is stable and let me know what comes back.

## Files changed

**0. Retention cap fix (Day-12 review)**
- `forms_app/models.py` — `Form.effective_retention_days` now returns
  `min(self.retention_days, cap)` instead of `self.retention_days or cap`,
  so an explicit per-form value set on a higher-tier plan gets re-capped
  after a downgrade instead of staying stale-and-too-high.
- `forms_app/tests/test_models.py` — new
  `test_effective_retention_days_recaps_after_plan_downgrade` (monkeypatches
  `billing.plans.PLANS` with a temporary higher-cap "pro" tier, sets
  `retention_days=90` on that plan, downgrades the account to "free", and
  asserts the effective value drops to 30).

**1. `config/settings/prod.py` — fail-fast, deploy-hardened**
- `SECRET_KEY`/`IP_HASH_SECRET`/`DATABASE_URL`/`REDIS_URL`/`PUBLIC_BASE_URL`
  each raise `ImproperlyConfigured` if they still equal their
  `.env.example` dev-insecure value; `ALLOWED_HOSTS` raises if empty or
  `["*"]`.
- `ADMIN_URL` moved out of `config/urls.py`'s hardcoded `"admin/"` into
  `settings.ADMIN_URL` — `config/settings/local.py` defaults it to
  `"admin/"`, `prod.py` requires it set with no default.
- `CSRF_TRUSTED_ORIGINS` required (Caddy terminates TLS; Django's CSRF
  origin check needs the public `https://` origin listed here).
- `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, secure+HttpOnly
  session/CSRF cookies, `SECURE_HSTS_SECONDS` (env-configurable, default 1
  day) + subdomains/preload, `SECURE_CONTENT_TYPE_NOSNIFF`,
  `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY=same-origin`.
- `config/settings/base.py` — added `DATABASE_URL` as its own setting
  (alongside the existing parsed `DATABASES`) for the backup command to use
  directly with `pg_dump`.

**2. Static files — WhiteNoise**
- `pyproject.toml`/`uv.lock` — added `whitenoise`, `sentry-sdk`.
- `config/settings/prod.py` — `WhiteNoiseMiddleware` inserted after
  `SecurityMiddleware`; `STORAGES["staticfiles"]` =
  `whitenoise.storage.CompressedManifestStaticFilesStorage`; `STATIC_ROOT`.
- `config/settings/build.py` (new) — collectstatic-only settings: sets
  build-time placeholder env vars (via `os.environ.setdefault`) for every
  var `prod.py` fail-fasts on, then imports `prod.py` for its real
  `STORAGES` config. Never used to run the app, only `collectstatic`.
- `Dockerfile` — `RUN DJANGO_SETTINGS_MODULE=config.settings.build
  python manage.py collectstatic --noinput` after the app code + built
  Tailwind CSS are in place.

**3. Error pages**
- `templates/404.html`, `templates/500.html` (new) — both extend
  `base_centered.html`; confirmed safe for Django's contextless
  `handler404`/`handler500` render (no DB access, no request needed).
- `core/tests/test_error_pages.py` (new) — 404 via a real `Client()` GET
  under `DEBUG=False`; 500 by calling `django.views.defaults.server_error`
  directly with a bare `HttpRequest()` (no session/middleware attached).

**4. Sentry (NFR-10)**
- `core/sentry.py` (new) — pure `before_send(event, hint)`: drops
  `request.data`/`query_string`/`cookies` and the `Cookie`/`Authorization`
  headers; recursively scrubs any `extra` key literally named `payload`
  (defense in depth — no call site passes one today).
- `config/settings/base.py` — `SENTRY_DSN`/`SENTRY_TRACES_SAMPLE_RATE`/
  `SENTRY_ENVIRONMENT`; `sentry_sdk.init(...)` only when `SENTRY_DSN` is set,
  `send_default_pii=False`, `before_send=core.sentry.before_send`.
- `core/tests/test_sentry.py` (new) — scrubs request body/cookies/query
  string, sensitive headers (keeps others, e.g. `User-Agent`), any nested
  `extra.payload` key, and no-ops on an event with neither `request` nor
  `extra`.
- `.env.example` — `SENTRY_DSN`/`SENTRY_TRACES_SAMPLE_RATE`/
  `SENTRY_ENVIRONMENT` (blank/disabled dev defaults).

**5. Scheduler — supercronic**
- `Dockerfile` — new `supercronic` build stage, same TOFU pattern as the
  existing `tailwind-cli` stage: the download is verified against
  supercronic's own upstream-published SHA1SUM first, then the SHA256 of
  that verified binary was computed once and hardcoded (`v0.2.49`).
- `deploy/crontab` (new) — `send_pending_notifications` every 5 min,
  `purge_expired_submissions` daily 03:00 UTC, `spam_report` daily 06:00
  UTC, `backup` daily 02:00 UTC.
- `docker-compose.prod.yml`'s `scheduler` service runs
  `supercronic /etc/easyforms/crontab` off the same image as `web`.

**6. Backups**
- `config/settings/base.py` — `BACKUP_STORAGE`/`BACKUP_LOCAL_DIR`/
  `BACKUP_R2_ACCOUNT_ID`/`BACKUP_R2_ACCESS_KEY_ID`/
  `BACKUP_R2_SECRET_ACCESS_KEY`/`BACKUP_BUCKET` — a credential set distinct
  from `ARTIFACT_STORAGE`'s `R2_*` (model artifacts), per the task.
- `core/backup_storage.py` (new) — `LocalBackupStore`/`S3BackupStore` +
  `get_backup_store()`, same put/get/exists shape as `spam/storage.py`'s
  `ArtifactStore` but deliberately not shared with it (independent
  credentials, and avoids touching that already-tested Day 8 module).
- `core/management/commands/backup.py` (new) — `pg_dump --format=custom`
  via `settings.DATABASE_URL`, gzip, upload to
  `backups/YYYY/MM/DD/<timestamp>.dump.gz`; logs key + byte size only.
- `core/management/commands/restore.py` (new) — required `--key` and
  required `--database-url` (deliberately **no** default of the live
  `DATABASE_URL`, so a restore can never accidentally target production by
  omission); downloads, gunzips, `pg_restore --clean --if-exists --no-owner`.
- `Dockerfile` — installs `postgresql-client-16` from the official PGDG apt
  repo (keyed off the base image's own `VERSION_CODENAME` rather than a
  hardcoded Debian release — see "Fixes made this session"), plus
  `curl`/`procps` for the compose healthchecks.
- `core/tests/test_backup_storage.py` (new, 6 tests) — Local via `tmp_path`,
  S3 via `botocore.stub.Stubber`, same style as `spam/tests/test_storage.py`.
- `core/tests/test_backup_command.py` (new, 3 tests) — `run_pg_dump`
  monkeypatched to write a sentinel dump file; asserts the reported key
  format/size, that stdout never contains the dump content, and that a
  `pg_dump` failure raises `CommandError`.
- `core/tests/test_restore_command.py` (new, 3 tests) — missing
  `--key`/`--database-url` → `SystemExit`; unknown key → `CommandError`;
  a real gzip round-trip through `LocalBackupStore` with `run_pg_restore`
  monkeypatched, asserting it received the right target URL and dump bytes.

**7. `docker-compose.prod.yml` (new)**
- `web` (gunicorn, `WEB_CONCURRENCY` env — `gunicorn.conf.py` now reads
  `workers = int(os.environ.get("WEB_CONCURRENCY", "2"))`), `worker`
  (`rqworker emails default`), `scheduler` (item 5), `db`, `redis`, `caddy`.
  No `tailwind`/`mailpit`, no bind mounts. `TRUSTED_PROXY_COUNT=1` on `web`.
  `restart: unless-stopped` everywhere.
- Healthchecks: `web` → `curl -f http://localhost:8000/healthz`; `worker`/
  `scheduler` → `pgrep -f rqworker` / `pgrep supercronic`; `db`/`redis` →
  the existing `pg_isready`/`redis-cli ping`; `caddy` → `caddy version`
  (the official `caddy:2` image ships no curl/wget to hit `/healthz`
  through the proxy with, so this only proves the process itself is alive —
  `depends_on: web: condition: service_healthy` already gates Caddy's
  startup on web's real health).
- `deploy/Caddyfile` (new) — `{$DOMAIN} { reverse_proxy web:8000 }`; Caddy
  auto-uses its internal CA for a non-public `DOMAIN` (e.g. `localhost`)
  and real ACME for a public one, no branching needed.
- Migrations are explicitly **not** run by any service's `command` —
  documented as the separate release step in the runbook.

**8. `docs/runbook.md` + `.env.production.example` (new)**
- Runbook: first deploy, routine deploy, rollback, restore from backup
  (with the "verify into a fresh DB first" safety step), rotate secrets,
  activate a new spam model, read `spam_report`, and the R2 lifecycle-rule
  note (documented only, not implemented in code, per the task).
- `.env.production.example`: every var from `.env.example` plus every new
  one (`ADMIN_URL`, `CSRF_TRUSTED_ORIGINS`, `SECURE_HSTS_SECONDS`, `DOMAIN`,
  `WEB_CONCURRENCY`, `TRUSTED_PROXY_COUNT=1`, `SENTRY_*`, `BACKUP_*`), with
  real (non-dev-default) placeholder guidance.

## FRs / NFRs covered

- **NFR-4 (security)** — fail-fast prod settings, HSTS/secure cookies/
  CSRF origins, `ADMIN_URL` off the default path.
- **NFR-6 (retention/privacy)** — the retention-cap fix; backup/restore
  path; R2 lifecycle-rule documented.
- **NFR-10 (observability)** — Sentry with a payload-safe scrubber.
- **SRS §12 (deployment/operations)** — static serving, scheduler,
  backups, `docker-compose.prod.yml`, runbook. Build-order row 13.

## How to verify manually

**Already run this session (see "Test results" below for output):**
```
uv sync --group dev
uv run ruff check . && uv run ruff format --check .
uv run pytest --collect-only -q          # 474 collected, 0 import errors
DJANGO_SETTINGS_MODULE=config.settings.build uv run python manage.py collectstatic --noinput
DJANGO_SETTINGS_MODULE=config.settings.prod <env vars> uv run python manage.py check --deploy
docker compose build web                 # succeeded
```

**Still needs a healthy Docker Desktop (blocked this session — see the
caveat above):**
```
docker compose run --rm web python manage.py migrate
docker compose run --rm web pytest -q
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm web python manage.py check --deploy
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml run --rm web python manage.py migrate
```
Then, with a prod-like `.env` and `DOMAIN=localhost`: load `https://localhost`
(Caddy's internal CA), confirm static (CSS/fonts) has long cache headers,
submit a form end-to-end with `EMAIL_PROVIDER=console`; force a 404 and
confirm the styled page; change `ADMIN_URL` and confirm the old `/admin/`
404s; tail `scheduler` logs for a `send_pending_notifications` run; run
`manage.py backup`, restore into a scratch DB, compare row counts.

## Test results

**Ran this session:**
```
uv run ruff check .                 # All checks passed!
uv run ruff format --check .        # 171 files already formatted
uv run pytest --collect-only -q     # 474 tests collected, 0 errors
```
**Test count: 474 collected, up from 455 passed on Day 12 (+19).** New:
`core/tests/test_error_pages.py` 2, `test_sentry.py` 4,
`test_backup_storage.py` 6, `test_backup_command.py` 3,
`test_restore_command.py` 3, plus 1 in `forms_app/tests/test_models.py`
(the retention-downgrade-cap test). **Not yet executed** (needs a real
Postgres/Redis; the project's `conftest.py` has an autouse fixture that
flushes real Redis rate-limit keys before/after *every* test, so this
isn't limited to `@pytest.mark.django_db` tests) — blocked on Docker
Desktop this session, see the caveat above.

**`manage.py check --deploy` against `config.settings.prod`** (run locally
via `uv run`, with env vars standing in for a real `.env`): passed clean
(`System check identified no issues (0 silenced)`). Also individually
confirmed each fail-fast branch actually raises
`django.core.exceptions.ImproperlyConfigured`:
`SECRET_KEY`/dev-default, empty `ALLOWED_HOSTS`, missing `ADMIN_URL`,
missing `CSRF_TRUSTED_ORIGINS`.

**`collectstatic` against `config.settings.build`** (run locally via
`uv run`, no Docker needed — this command touches no DB/Redis): 134 static
files copied, 400 post-processed; spot-checked `static/css/app.css` →
`app.<hash>.css` + `.gz` sibling, and the JSON manifest maps unhashed names
to hashed ones correctly.

**`core.sentry.before_send`** (called directly, not via pytest): a
synthetic event with `request.data/query_string/cookies/headers.Cookie` and
a nested `extra.nested.payload` came back with all of those stripped/
scrubbed and everything else (URL, `User-Agent`, sibling `extra` keys)
untouched.

**`core.backup_storage.LocalBackupStore`** (called directly): put → exists
→ get round-tripped a byte string correctly.

**`django.views.defaults.server_error`** (called directly with a bare
`HttpRequest()`, `DEBUG=False`): returned 500 with the expected page copy,
confirming no DB/request-context access is needed.

**`docker compose build web`**: succeeded after one real fix (see below).

## Fixes made this session

- **Real bug — `postgresql-client-16` failed to install via the
  hardcoded `bookworm-pgdg` apt source.** `python:3.12-slim` now tracks
  Debian 13 (trixie), not bookworm (Debian's "current stable" moved during
  this project's life) — `apt-get install postgresql-client-16` failed with
  an unresolvable `libldap-2.5-0` dependency because PGDG's `bookworm-pgdg`
  repo's `libpq5` build doesn't match trixie's own libraries. Fixed by
  reading `VERSION_CODENAME` from `/etc/os-release` at build time instead of
  hardcoding a release name, so the correct PGDG repo (`trixie-pgdg`, today)
  is always selected regardless of which Debian release the base image is
  currently on. Reproduced and confirmed fixed via standalone
  `docker run python:3.12-slim sh -c ...` before touching the real
  Dockerfile.
- **Forgot `STATIC_ROOT`** in the first pass of `config/settings/prod.py` —
  `collectstatic` failed immediately with `ImproperlyConfigured: ... set
  the STATIC_ROOT setting`. Added `STATIC_ROOT = BASE_DIR / "staticfiles"`
  (already in `.gitignore`, confirming this was the intended path all
  along).
- **Ruff F405 on `BASE_DIR`** in `prod.py` (used from the `from .base
  import *` star-import without an explicit name) — fixed by adding it to
  the explicit `from .base import ALLOWED_HOSTS, BASE_DIR, MIDDLEWARE, env`
  line already used for the other settings prod.py re-reads.

## Deviations from the plan

- **Live Docker verification not completed this session** — see the
  caveat at the top. Everything else in the approved plan was implemented
  as written.
- Caddy's healthcheck uses `caddy version` (process-alive only) rather than
  actually hitting `/healthz` through the proxy, since the official
  `caddy:2` image has no `curl`/`wget` to do that with — flagged as a
  judgment call in the plan, confirmed by inspecting the image's package
  set isn't feasible without a working container run, so documented as a
  known limitation instead of guessed at.

## Follow-ups (not done today)

- Run the still-pending Docker verification pass above once Docker Desktop
  is stable, and report back the real `pytest` pass/fail count plus the
  live `docker-compose.prod.yml` walkthrough.
- R2 lifecycle rule (30-day backup expiry) is a Cloudflare dashboard
  config task, not code — documented in the runbook, not automated.
- Day 14: deliverability (SPF/DKIM/DMARC), docs, buffer.

## Suggested commits

Ordered so each passes tests standalone (as far as this session could
verify — see the caveat); no file split across commits.

1. `fix(forms_app): recap effective_retention_days after a plan downgrade`
```
git add forms_app/models.py forms_app/tests/test_models.py
git commit -m "fix(forms_app): recap effective_retention_days after a plan downgrade"
```

2. `feat(config): prod settings — fail-fast secrets, WhiteNoise static, error pages, Sentry (NFR-4, NFR-10)`
```
git add config/settings/base.py config/settings/local.py config/settings/prod.py config/settings/build.py config/urls.py core/sentry.py core/tests/test_sentry.py core/tests/test_error_pages.py templates/404.html templates/500.html pyproject.toml uv.lock .env.example
git commit -m "feat(config): prod settings - fail-fast secrets, WhiteNoise static, error pages, Sentry (NFR-4, NFR-10)"
```

3. `feat(core): database backup/restore commands with a dedicated R2 credential set (NFR-6)`
```
git add core/backup_storage.py core/management/ core/tests/test_backup_storage.py core/tests/test_backup_command.py core/tests/test_restore_command.py
git commit -m "feat(core): database backup/restore commands with a dedicated R2 credential set (NFR-6)"
```

4. `feat(deploy): production Docker Compose stack, scheduler, Caddy, runbook (SRS section 12)`
```
git add Dockerfile gunicorn.conf.py docker-compose.prod.yml deploy/ .env.production.example docs/runbook.md
git commit -m "feat(deploy): production Docker Compose stack, scheduler, Caddy, runbook (SRS section 12)"
```

5. `docs(progress): Day 13a summary`
```
git add docs/progress/day-13a.md
git commit -m "docs(progress): Day 13a summary"
```

Then:
```
git status   # expected: clean
```
