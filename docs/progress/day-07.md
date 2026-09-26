# Day 7 — Rate limiting, plan limits, metering

## Files changed

- **`core/ratelimit.py`** (new) — `hit(bucket, key, limit, window_seconds) -> RateResult(allowed, retry_after)`. Fixed-window limiter backed by a single Redis key per bucket+key, prefixed `easyforms:rl:`. Atomic INCR+EXPIRE+TTL via a registered Lua script (avoids the race a bare pipeline would have between "first hit sets the TTL" and "read the TTL back"). Fails open (`allowed=True`) and logs a warning if Redis raises (NFR-3). `combine(*results)` merges multiple dimensions/windows checked for one request, keeping the max `retry_after` among denials.
- **`billing/plans.py`** (new) — `PLANS = {"free": {...}}`, `DEFAULT_PLAN`.
- **`billing/limits.py`** (new) — `LimitResult(allowed, used, limit)`, `check_limit(account, kind)` for `kind in {"forms", "submissions"}`, `has_feature(account, name)`. Unknown plan falls back to `free` and logs a warning. `allowed = used < limit` (not `<=`) so the check reads as "may I add one more," which is what makes the 250th-accepted/251st-rejected boundary work.
- **`ingest/rate_limit.py`** (new) — `check_ip_limit(ip_hash)`, `check_token_limit(token)`; each combines a per-minute and a per-hour `core.ratelimit.hit()` call.
- **`ingest/views.py`** — check order is now method → size → **IP rate limit (POST only)** → form lookup → **token rate limit (POST only)** → origin → OPTIONS → parse → **plan/quota check (ham only)** → store. Both rate-limit checks are gated on `request.method == "POST"`, so CORS preflight (`OPTIONS`) requests still run the size/form-lookup/origin checks but never call `hit()` — they don't consume IP or token budget. Store step wraps `Submission.objects.create` + `UsageEvent.objects.create` in one `transaction.atomic()` block. The 405 → `Allow: POST, OPTIONS` header was already in place from Day 6; untouched.
- **`ingest/responses.py`** — added `rate_limited` and `quota_exceeded` to `_MESSAGES` (the latter says nothing about plan/account specifics).
- **`accounts/rate_limit.py`** (new) — `check_login_limit(ip_hash, email)`, `check_signup_limit(ip_hash)`, `check_reset_limit(ip_hash, email)`.
- **`accounts/views.py`** — `signup` checks `check_signup_limit` before validating the form; new `RateLimitedLoginView`/`RateLimitedPasswordResetView` (thin `post()` overrides on Django's built-in CBVs) check the limiter before calling `super().post()`; `_too_many_requests()` helper renders the new 429 template. `settings_view` now passes `forms_limit`/`submissions_limit` via `check_limit`.
- **`accounts/urls.py`** — `login` and `reset` now point at `RateLimitedLoginView`/`RateLimitedPasswordResetView` instead of the bare Django CBVs; same kwargs.
- **`templates/rate_limited.html`** (new) — shared 429 page for the accounts flows (extends `base.html`).
- **`accounts/templates/accounts/settings.html`** — replaced the "Usage figures are coming Day 7" placeholder with Active forms and Submissions-this-month `<dt>`/`<dd>` pairs.
- **`forms_app/views.py`** — `form_create` replaces the `TODO(Day 7)` with `check_limit(account, "forms")`, adding a form-level (non-field) error over limit; `form_activate` gets the same check (not previously TODO'd, but reactivating increases the active count the same way creating does).
- **`forms_app/templates/forms_app/form_new.html`** — now renders `form.non_field_errors` (previously silently dropped).
- **`dashboard/views.py`** / **`dashboard/templates/dashboard/home.html`** — dashboard now shows `{used} / {limit} forms used` and hides the create link (showing the limit message instead) once at the cap.
- **`config/settings/base.py`** / **`.env.example`** — `INGEST_RATE_LIMIT_{IP,TOKEN}_PER_{MINUTE,HOUR}` and `AUTH_RATE_LIMIT_{LOGIN_IP,LOGIN_EMAIL,SIGNUP_IP,RESET_IP,RESET_EMAIL}_PER_{MINUTE,HOUR}`, all `env.int` with the defaults from the task.
- **`conftest.py`** (new, repo root) — autouse fixture flushing the `easyforms:rl:*` Redis keyspace before and after every test.
- Tests: `core/tests/test_ratelimit.py`, `billing/tests/test_limits.py`, `ingest/tests/test_rate_limit.py` (new); extended `forms_app/tests/test_views.py`, `dashboard/tests/test_views.py`, `accounts/tests/test_views.py`, `accounts/tests/test_password_reset.py`.

No model or migration changes (`makemigrations --check --dry-run` confirms).

## FRs / NFRs covered

- **FR-7.1** — per-IP-hash and per-form-token rate limits on `/f/{token}` (10/min + 100/hour IP; 60/min + 1000/hour token), `429 rate_limited` with `Retry-After`. Only counted on `POST`; CORS preflight (`OPTIONS`) requests don't consume budget.
- **FR-7.2** — `check_limit(account, "submissions")` runs before storing; over limit → `429 quota_exceeded` (message carries no account/plan details), nothing stored.
- **FR-7.3** — a `UsageEvent(kind="submission")` row is created in the same transaction as each stored `Submission`.
- **FR-1.4 / FR-6.4** — `/settings` and `/dashboard` show active-forms and current-month-submissions usage against the plan limit.
- **NFR-3** — the limiter fails open (allows, logs a warning) if Redis errors.
- **SRS §11** ("rate-limit auth endpoints against credential stuffing") — login (10/min per IP, 5/min per lowercased submitted email), signup (5/hour per IP), password-reset request (5/hour per IP, 3/hour per email) all return a 429 page with `Retry-After` on breach. The reset-request check runs before Django's `PasswordResetForm` looks up the email, so the known-vs-unknown-email response stays identical even under rate limiting.

## How to verify manually

```
docker compose up
```
1. Create a form, then `curl -X POST http://localhost:8000/f/{token} -d name=Jane` eleven times quickly → the 11th (default 10/min) returns `429 {"error": "rate_limited"}` with a `Retry-After` header. Interleaving `curl -X OPTIONS` preflights doesn't change the count — they aren't rate-limited.
2. Seed 250 `UsageEvent(kind="submission")` rows for a form's account, then POST once more → `429 quota_exceeded`; `Submission` count doesn't move.
3. Log in, visit `/settings` → "Active forms" and "Submissions this month" show real used/limit numbers; `/dashboard` shows the same forms count and hides "+ New form" once at 3 active forms.
4. Try creating a 4th form or reactivating a deactivated one while already at 3 active → blocked with "You've reached your plan's limit of 3 active forms."
5. Hit `/login` with the wrong password repeatedly (or `/signup`, `/reset`) past the configured cap → 429 page with `Retry-After`.

All five were exercised live against the running `docker compose` stack during this task (see Test results below); the account/form/user rows created for that were cleaned up afterward.

## Test results

- `docker compose run --rm web pytest` → **207 passed**.
- `docker compose run --rm web ruff check .` → all checks passed.
- `docker compose run --rm web ruff format --check .` → all files formatted.
- `docker compose run --rm web python manage.py makemigrations --check --dry-run` → no changes detected.
- Live smoke test against the running stack: IP rate limit tripped at the expected count with a `Retry-After` header present; quota boundary produced `quota_exceeded` at exactly the 250-event mark; `/settings` and `/dashboard` reflected real usage numbers for a real account/form/user.

## Deviations from the plan

One correction after initial review: the plan originally let `OPTIONS` preflight requests pass through the same IP/token `hit()` calls as `POST` ("simplest reading of the given check order"). That was wrong in practice — a browser can send many preflights per actual submission, so counting them would let CORS traffic alone exhaust a form's or IP's budget and start blocking real submissions. Both rate-limit checks in `ingest/views.py` are now gated on `request.method == "POST"`; preflights still run the size/form-lookup/origin checks unchanged, they just never call `hit()`. Added `test_preflight_then_post_consumes_one_unit_of_ip_and_token_budget` and `test_many_preflights_do_not_block_a_subsequent_post` to `ingest/tests/test_rate_limit.py` to lock this in.

## Follow-ups (out of scope for Day 7)

- Spam scoring (Day 9) will insert a scoring step between `parse_body` and the submissions quota check, and will change which submissions count as ham (currently all submissions are ham, since no scorer exists yet).
- Notifications/worker wiring — Day 10.
- Paid-tier limits, Stripe — out of scope for v1 per CLAUDE.md rule 13.

## Suggested commits

1. `chore(config): add ingest and auth rate-limit settings (FR-7.1, SRS §11)`
   — `config/settings/base.py`, `.env.example`. (Adds env-overridable settings only; nothing references them yet, so the existing suite is unaffected.)
2. `feat(core): add Redis fixed-window rate limiter`
   — `core/ratelimit.py`, `core/tests/test_ratelimit.py`, `conftest.py` (autouse fixture flushing `easyforms:rl:*` before/after each test — belongs alongside the module it isolates).
3. `feat(billing): add PLANS config and check_limit/has_feature (FR-7.2, §10)`
   — `billing/plans.py`, `billing/limits.py`, `billing/tests/test_limits.py`.
4. `feat(ingest): rate-limit and meter submissions (FR-7.1, FR-7.2, FR-7.3)`
   — `ingest/rate_limit.py`, `ingest/views.py`, `ingest/responses.py`, `ingest/tests/test_rate_limit.py`. (IP/token limits apply to `POST` only; CORS preflight doesn't consume budget.)
5. `feat(accounts): show plan usage in settings and rate-limit auth endpoints (FR-1.4, SRS §11)`
   — `accounts/rate_limit.py`, `accounts/views.py`, `accounts/urls.py`, `accounts/templates/accounts/settings.html`, `templates/rate_limited.html`, `accounts/tests/test_views.py`, `accounts/tests/test_password_reset.py`.
6. `feat(forms_app,dashboard): enforce active-forms plan limit and show usage (FR-6.4)`
   — `forms_app/views.py`, `forms_app/templates/forms_app/form_new.html`, `forms_app/tests/test_views.py`, `dashboard/views.py`, `dashboard/templates/dashboard/home.html`, `dashboard/tests/test_views.py`.
7. `docs(progress): add Day 7 summary`
   — `docs/progress/day-07.md`.
