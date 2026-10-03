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

**Update (2026-10-02) — live verification completed, review items closed.**
The original session below could not get Docker stable enough to run
anything live. A follow-up session (plan:
`C:\Users\USER\.claude\plans\read-claude-md-and-docs-progress-day-13a-dapper-melody.md`)
closed out a 3-item review of this work and then actually ran everything —
dev stack, Playwright regression, and a full local `docker-compose.prod.yml`
walkthrough including signup → form → submission → notification, the
scheduler, and backup/restore. See "Review fixes" and "Live verification
results" below for what was found and fixed. The rest of this document is
the original (as-written, not-yet-run) summary.

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

## Review fixes (follow-up session, 2026-10-02)

A review of the work above raised three items:

1. **`Form.effective_retention_days` + `None` — already correct, no change
   needed.** The property (`forms_app/models.py`) already has an explicit
   `if self.retention_days is None: return cap` branch (landed in commit
   `f647d0e`, the Day-12 retention-cap fix referenced above) — more correct
   than the `retention_days or cap` phrasing the review item suggested,
   since that form would also wrongly fall back to the cap for an explicit
   `retention_days=0`. `test_effective_retention_days_falls_back_to_plan_when_unset`
   already creates a form with no `retention_days` (`None`) and asserts the
   cap is returned, so no new test was needed either.
2. **HSTS subdomains/preload now default off, env-driven.**
   `config/settings/prod.py` hardcoded `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`
   and `SECURE_HSTS_PRELOAD = True`; both now read from env
   (`env.bool(..., default=False)`). Added both vars to
   `.env.production.example` (defaulted `False`) and a new "HSTS" section in
   `docs/runbook.md` explaining why preload in particular is opt-in (it's
   submitted to browser vendors' preload lists and is effectively
   irreversible) rather than a prod default.
3. **Dockerfile base images pinned to an explicit Debian release.** All
   three `FROM` lines (`debian:bookworm-slim` ×2, `python:3.12-slim`) didn't
   pin a Debian release — the exact thing that already broke the
   `postgresql-client-16` install once this session (see "Fixes made this
   session" below: Debian's "current stable" moved under `python:3.12-slim`
   mid-project). Pinned to `python:3.12-slim-trixie` (final stage) and
   `debian:trixie-slim` (the two build-only stages), all tracking the same
   release consistently. The `VERSION_CODENAME`-keyed PGDG apt-source logic
   is left as-is — it still works, now deterministically resolving to
   `trixie`, and stays robust if a future pin bump changes the codename.

## Live verification results (follow-up session, 2026-10-02)

**A. Dev stack — `docker compose build` / `up` / `migrate` / `pytest` / `ruff` / `makemigrations --check`.**
All built and ran cleanly. First full pytest run surfaced one real bug (see
below); after fixing it, **474/474 tests pass** (474 collected, up from 455
passed on Day 12 — no decrease, +19 net as expected). `ruff check` and
`ruff format --check` both clean (172 files formatted). `makemigrations
--check --dry-run` → "No changes detected". (Note: `docker compose run`'s
captured output twice dropped pytest's own trailing `N passed in Ys` summary
line on a fast container exit — worked around by counting `.`/`F` characters
in the printed progress bar, which summed to exactly 474 each time.)

Real bug found and fixed: `core/tests/test_restore_command.py::test_restore_requires_key_and_database_url`
asserted `pytest.raises(SystemExit)` for a `call_command("restore")` missing
its required `--key`/`--database-url` args. Django's `call_command` never
raises `SystemExit` for a missing required arg — `CommandParser.error()`
raises `CommandError` instead whenever `called_from_command_line` is False
(exactly the `call_command` path), which is also the established pattern
used by every other required-arg test in this codebase (e.g.
`spam/tests/test_commands.py`). This test had never actually been run
before this session. Fixed the assertion to `pytest.raises(CommandError,
match=...)`.

**B. Playwright regression (screenshots + interaction checks) against the dev stack.**
Seeded demo data (`var/seed_demo.py`), ran both scripts via
`mcr.microsoft.com/playwright/python:v1.47.0-jammy` against the dev stack.
Note: that image ships Playwright's browsers but not the `playwright` pip
package itself — `pip install playwright==1.47.0` once per container run
before invoking the script. All 25 expected screenshots generated; spot
checks (dashboard, submissions list, submission detail, mobile drawer) all
render correctly and match the intended design. All 7 interaction checks
passed (focus-visible on every tab stop on two pages, HTMX filter swap,
copy-button feedback, label-flip + undo toast, `prefers-reduced-motion`
collapsing transitions to ~0s). Cleaned up with `var/purge_demo.py`
afterward.

**C. Prod stack, locally, with a prod-like `.env` (`DOMAIN=localhost`,
`EMAIL_PROVIDER=console`, `BACKUP_STORAGE=local`, `ARTIFACT_STORAGE=local`,
`SECURE_HSTS_SECONDS=0`, freshly generated secrets).** Run as its own
isolated Compose project (`-p easyforms-prodtest`) — **important finding**:
the default project name is derived from the directory, which is the same
for `docker-compose.yml` and `docker-compose.prod.yml`, so running the prod
file unscoped recreated the *dev* stack's `db`/`redis` containers (same
service names, same named volumes). No data was lost (named volumes survive
container recreation and Postgres doesn't rerun init scripts against an
already-initialized data directory), but it's a real trap — always pass
`-p <distinct-name>` for a local prod-stack test.

Real bug found and fixed: the `scheduler` service crash-looped on
`open /etc/easyforms/crontab: permission denied`. `COPY --chmod=644
deploy/crontab /etc/easyforms/crontab` applies that `chmod` to the
auto-created `/etc/easyforms` *directory* as well as the file, leaving the
directory untraversable by `appuser` (the image's non-root user). Fixed by
adding `RUN mkdir -p /etc/easyforms` (as root, default `755`) immediately
before the `COPY`.

With that fixed, all 6 services (`db`, `redis`, `web`, `worker`,
`scheduler`, `caddy`) reported `healthy`. Verified, with real commands
against the running stack:
- `check --deploy`: clean (one expected `W004` warning for `SECURE_HSTS_SECONDS=0`,
  intentional for this localhost test).
- `https://localhost` loads over Caddy's internal CA with the expected
  security headers (`Strict-Transport-Security` absent since
  `SECURE_HSTS_SECONDS=0`; `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, etc. present).
- Static CSS/font responses are served under hashed filenames
  (`app.c74807199c9d.css`, `...woff2`) with
  `Cache-Control: max-age=315360000, public, immutable`.
- An unknown path renders the styled `404.html` (`<title>Page not found —
  Easyforms</title>`); the old `/admin/` 404s once `ADMIN_URL` is a custom
  path, and the custom path itself redirects to its own login.
- Signed up via real HTTP POSTs, created a form, submitted to its `/f/token`
  endpoint: first submission (pre-email-verification) was correctly
  `notification_status=skipped` per FR-1.2 ("ham with no verified account
  user at store time" — not a bug); verified the account via the console-
  logged verify link, submitted again, and that one shows
  `notification_status=sent` with the worker's log showing the RQ job
  completing and the console-backend email containing the submitted fields.
- `scheduler` logs a real cron tick (`*/5 * * * *`) at `:10:00` running
  `send_pending_notifications` and succeeding ("Enqueued 0 pending
  submission notification(s)" — correct, both test submissions were already
  processed immediately via RQ).
- `manage.py backup` → `manage.py restore --database-url <scratch db>` →
  row counts matched exactly (`forms`, `submissions`, `users` all equal)
  between the live DB and the restored scratch DB.
- `core.sentry.before_send` exercised on a **real SDK-built event** (not a
  hand-typed dict): a genuine `ValueError` raised inside a real Django view,
  captured via `sentry_sdk`'s own `event_from_exception` +
  `DjangoRequestExtractor` (the same functions the SDK's own Django
  integration uses), routed through `before_send` exactly as configured in
  `sentry_sdk.init(...)`. Confirmed `request.data` (the submitted payload)
  and `request.cookies` (the session cookie) were stripped before reaching
  the transport. **Finding worth keeping in mind:** this `sentry-sdk`
  version (2.71.0) attaches `request.data` by default *regardless of
  `send_default_pii`* — only `cookies` is gated by that flag. So
  `before_send`'s stripping of `request.data` isn't just "defense in depth"
  per its own docstring; given the app's actual `send_default_pii=False`
  config, it is the thing actually preventing a captured exception from
  leaking a submission payload (CLAUDE.md rule 4). No code change made here
  (the existing scrubber already covers it) — noted for awareness.

**D. Teardown.** `docker compose -f docker-compose.prod.yml -p
easyforms-prodtest down -v` removed all prod-test containers/volumes/network
cleanly. Restored the real dev `.env` (backed up before the prod-test swap,
since both compose files read the same `.env` filename). Dev stack's
`db`/`redis` needed one more recreate (env values reverting), but the named
`pgdata` volume was untouched throughout, so `migrate` reported "No
migrations to apply" (correct — already applied) and a final full `pytest
-q` run confirmed dev stack fully healthy at **474/474 passing**.

## How to verify manually

See "Live verification results" above for the commands actually run and
their output. For a fresh run: `docker compose build && docker compose up
-d && docker compose run --rm web python manage.py migrate && docker
compose run --rm web pytest -q`; for the prod stack, always scope it with
`-p <distinct-project-name>` to avoid colliding with the dev stack's
same-named containers/volumes (see step C above).

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
(the retention-downgrade-cap test). **Now executed — see "Live verification
results" above: 474/474 pass** (one real test bug found and fixed along the
way, in `test_restore_command.py`).

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

- **Live Docker verification not completed in the original session** — fully
  closed out in the 2026-10-02 follow-up session, see "Live verification
  results" above.
- Caddy's healthcheck uses `caddy version` (process-alive only) rather than
  actually hitting `/healthz` through the proxy, since the official
  `caddy:2` image has no `curl`/`wget` to do that with — flagged as a
  judgment call in the plan; confirmed live in the follow-up session that
  `depends_on: web: condition: service_healthy` does gate Caddy's startup on
  web's real health, so this is an accepted, documented limitation rather
  than a gap.

## Follow-ups (not done today)

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

### Follow-up session (2026-10-02) — review fixes + live verification

1. `fix(config): default HSTS subdomains/preload off, pin Dockerfile base image, fix crontab permissions (NFR-4)`
```
git add config/settings/prod.py .env.production.example docs/runbook.md Dockerfile
git commit -m "fix(config): default HSTS subdomains/preload off, pin Dockerfile base image, fix crontab permissions (NFR-4)"
```

2. `fix(core): correct restore command's required-args test to expect CommandError`
```
git add core/tests/test_restore_command.py
git commit -m "fix(core): correct restore command's required-args test to expect CommandError"
```

3. `docs(progress): Day 13a review fixes and live verification results`
```
git add docs/progress/day-13a.md
git commit -m "docs(progress): Day 13a review fixes and live verification results"
```

Then:
```
git status   # expected: clean
```
