# Easyforms — Project Guide for Claude Code

Hosted form backend with ML spam filtering. Static/JAMstack sites POST forms to
`/f/{token}`; we validate, spam-score, store, and email the owner.
This project also establishes the shared foundation (auth, storage, worker,
plan/limits, metering) reused by later projects — keep it clean, not clever.

**Source of truth:** `docs/SRS.md`. Reference requirement IDs (FR-x.x, NFR-x)
in plans, commits, and tests. If the SRS and this file conflict, this file wins
(it contains post-review decisions). If something is ambiguous, ask — don't guess.

## Stack
- Python 3.12, Django 5.x, PostgreSQL 16, Redis + RQ (django-rq)
- Django templates + Tailwind + HTMX (no SPA, no DRF unless agreed)
- scikit-learn (TF-IDF + linear model), artifacts in Cloudflare R2 (boto3, S3 API)
- Email: provider TBD by Day 10 (Postmark / Resend / SendGrid) behind one interface
- Stripe: import stubbed, never called
- Docker Compose services: `web` (gunicorn), `worker` (rqworker), `db`, `redis`
- Config via django-environ only. Tooling: uv, ruff, pytest-django

## App layout
```
config/            settings/{base,local,prod}.py, urls, wsgi
accounts/          Account, custom User (email login), auth flows
billing/           plans.py (PLANS dict), limits.py (check_limit), UsageEvent
forms_app/         Form model, CRUD, snippet display
ingest/            public /f/{token} endpoint, CORS, validation, rate limiting
spam/              ModelVersion, feature extraction, scoring, training script
notifications/     RQ jobs, email sending
dashboard/         owner-facing views, submissions list, CSV export
core/              healthz, shared utils (ip hashing, logging)
```

## Non-negotiable rules
1. **Custom user model** `accounts.User` (email as USERNAME_FIELD, citext unique,
   FK to Account) exists from the very first migration.
2. **UUID primary keys** everywhere except `UsageEvent` (bigint).
3. **Ingest path stays fast** (NFR-1, p95 < 300 ms): no outbound network calls
   in the request besides Postgres/Redis. Email/webhooks only via RQ.
4. **Never log submission payloads.** Sentry `before_send` must scrub them.
5. **Never store raw IPs.** Use `core.utils.hash_ip()` = HMAC-SHA256 with
   `IP_HASH_SECRET`.
6. **All limit checks** go through `billing.limits.check_limit(account, kind)`.
   Limits and feature flags live only in `billing/plans.py`.
7. **Only ham is metered** and counts toward plan limits. Spam is controlled by
   rate limiting, not quota.
8. **`_redirect`** is honored only if its origin is in the form's
   `allowed_origins`; otherwise use `redirect_url`, else hosted `/thanks` page.
9. **`_ts` timing** is a soft feature (client-supplied, spoofable). Honeypot is
   the only hard heuristic.
10. **Spam model boot** must not depend on R2 being reachable: use a local cached
    artifact; if none, score with heuristics only (`spam_score = null`).
11. **Default spam action is `flag`**; every label is reversible by the owner.
12. **No secrets in the repo.** Every new env var gets added to `.env.example`.
13. **Out of scope for v1** — do not build: file uploads, webhooks/integrations,
    teams, retraining UI, payments.

## Commands
```
docker compose up --build          # full stack
docker compose run --rm web pytest # tests
docker compose run --rm web ruff check . && ruff format --check .
docker compose run --rm web python manage.py makemigrations / migrate
```
(Replace with Makefile targets once Day 1 creates them.)

## How to work
- **Plan first.** For each task, propose a plan (files, models, tests, open
  questions) and wait for approval before writing code.
- **Scope discipline.** Build only the current day's task. Note ideas for later
  under "Follow-ups" in your summary instead of implementing them.
- **Tests are part of done.** Every FR touched gets pytest coverage. Run the
  full suite and ruff before declaring a task complete.
- **Dependencies:** state why before adding any new package.
- **Migrations:** never edit an applied migration; create a new one.
- **Git: do not run git commands that change state** (no add, commit, push,
  checkout, reset, stash). The user commits manually in a separate terminal.
  Read-only commands (git status, git diff, git log) are fine.
- **At the end of each task**, propose one or more conventional commit messages
  (e.g. `feat(ingest): accept JSON and form-encoded POSTs (FR-3.1)`) and list
  which files belong in each commit.
- **End every task with a summary** (also written to docs/progress/day-NN.md):
  files changed, FRs covered, how to verify manually, test results, deviations,
  follow-ups, and a copy-paste commit block.
- **Test count:** report the total collected test count and compare it with
  the previous day's summary. Explain any decrease explicitly.
- **Commit block format:** give exact, copy-paste-ready commands, one
  `git add <explicit paths>` + `git commit -m "<conventional message>"` pair
  per commit, in order, followed by `git status` (expected: clean). Never use
  `git add -A` or `git add .`. Every commit must pass tests on its own, no file
  may appear in two commits, and prefer 2–4 cohesive commits per day over
  fine-grained splits. The day's docs/progress file goes in the last commit.
- **Commit suggestions must be ordered so every commit passes tests on its own,
  and a single file must never be split across commits.** When in doubt, suggest
  one commit per day.
- **Save each day's end-of-task summary** to docs/progress/day-NN.md (include it
  in the last suggested commit).
- **Tests must include a GET of the edit page for an existing object** whenever
  a form edits stored data (catches initial-value rendering bugs).
- **Local prod-stack tests always use a separate project name:**
  `docker compose -f docker-compose.prod.yml -p easyforms-prodtest ...`
  (the dev and prod files share service and volume names).

## Progress
- [x] Day 1 — Compose skeleton, settings, custom user stub, healthz, tooling
- [ ] Day 2 — Data model + migrations + admin
- [ ] Day 3 — Auth flows
- [ ] Day 4 — Form CRUD + token + snippet
- [ ] Day 5 — Ingest endpoint: validate, store, CORS
- [ ] Day 6 — Redirect vs JSON, size limits, error codes
- [ ] Day 7 — Rate limiting, check_limit, UsageEvent
- [ ] Day 8 — Bootstrap spam model → R2
- [ ] Day 9 — Inline scoring + heuristics
- [ ] Day 10 — Worker + notification emails
- [ ] Day 11 — Dashboard list/filter/detail/CSV
- [ ] Day 12 — Label correction + monitoring counters
- [ ] Day 13 — Deploy VPS + PaaS, TLS, backups
- [ ] Day 14 — Deliverability, docs, buffer
