# Day 10 — Worker + notification emails

## Follow-up: Redis-outage latency fix

The first live-verification pass below measured **~19 seconds** for an ingest request to return
during a Redis outage (still `200`, but far past NFR-1's sub-300ms target) — flagged as a follow-up
rather than fixed inline. Before committing, that follow-up was built and verified; this section
documents it, and the rest of the file below is otherwise unchanged from the original Day 10 pass.

### Files changed (this follow-up)

- **`config/settings/base.py`** — new `REDIS_TIMEOUT_SECONDS` (default `0.3`) and
  `REDIS_BREAKER_SECONDS` (default `5`). `RQ_QUEUES` restructured from `{"URL": REDIS_URL}` to
  `HOST`/`PORT`/`DB`/`PASSWORD` + `REDIS_CLIENT_KWARGS` (parsed from `REDIS_URL` via
  `urllib.parse.urlparse`) — django-rq's `get_redis_connection` takes a `"URL"`-keyed config
  straight to `redis_cls.from_url(url, db=...)` and **never forwards any other kwarg**, so there
  was no way to set `socket_connect_timeout`/`socket_timeout` on the RQ connection without this
  reshape (confirmed by reading `django_rq.connection_utils.get_redis_connection` directly — the
  `HOST`/`PORT` branch does pass through `REDIS_CLIENT_KWARGS`). `CACHES["default"]["OPTIONS"]`
  gained the same two timeout keys (Django's built-in `RedisCache` forwards `OPTIONS` straight to
  `ConnectionPool.from_url(...)`, confirmed by reading `django.core.cache.backends.redis`).
- **`core/circuit_breaker.py`** (new) — the shared breaker: `is_open()`, `trip()` (opens for
  `REDIS_BREAKER_SECONDS`, logs once per closed→open transition — verified in the live test that a
  20-request outage burst logged the trip exactly once), `reset()` (test-only), `CircuitOpenError`.
  Plain module-level state (`time.monotonic()` + a lock around writes) — in-process only, matching
  how gunicorn workers each hold independent state already for the spam scorer singleton; no
  cross-process coordination was asked for or needed.
- **`core/bounded_call.py`** (new) — `run_bounded(func, timeout)`: runs a zero-arg callable in a
  small `ThreadPoolExecutor` and waits at most `timeout` seconds via `future.result(timeout=...)`.
  Exists because **`socket_connect_timeout` does not bound DNS resolution** — confirmed directly:
  a raw `redis.Redis.from_url(url, socket_connect_timeout=0.3, socket_timeout=0.3).ping()` against
  a hostname that had stopped resolving (`docker compose stop redis` removes the container's
  network/DNS entry entirely) still took **~3.8s** to fail, with the traceback showing the block
  inside `socket.getaddrinfo()` — a phase that precedes, and isn't covered by, any redis-py
  client-side timeout. `run_bounded` bounds the *caller's wait*, not the underlying call (Python
  can't force-cancel a blocked thread); the abandoned thread finishes on its own once DNS times out
  and its result is discarded.
- **`core/ratelimit.py`** — `_get_script()`'s client construction gained the two timeout kwargs;
  `hit()` now checks `circuit_breaker.is_open()` first (fail-open immediately, no Redis touch) and
  wraps its Lua-script call in `bounded_call.run_bounded(..., timeout=REDIS_TIMEOUT_SECONDS)`,
  calling `circuit_breaker.trip()` on `(redis.RedisError, TimeoutError)` before failing open.
- **`core/views.py`** — `_check_redis()` (the `/healthz` check) gained `socket_timeout` (it already
  had a hardcoded `socket_connect_timeout=1`, now `REDIS_TIMEOUT_SECONDS`) and is wrapped in
  `bounded_call.run_bounded` too, for the same DNS-phase reason — not strictly asked for, but a
  healthz endpoint that can still hang ~4s during exactly the outage it's meant to report on
  seemed worth closing while touching this file anyway.
- **`notifications/tasks.py`** — `_enqueue()` (shared by both job types) checks
  `circuit_breaker.is_open()` first and calls `circuit_breaker.trip()` on `redis.RedisError`.
  **Deliberately not wrapped in `bounded_call`**, unlike the rate limiter — see Deviations below;
  this was a real bug caught by the test suite, not a design choice made up front.
- **`conftest.py`** — new autouse `_reset_circuit_breaker` fixture. The breaker is module-global
  process state, so without a per-test reset a `trip()` in one test would silently make an
  unrelated later test's Redis calls skip (a real risk given `core.ratelimit`'s existing
  `test_fail_open_when_redis_errors` test raises a `ConnectionError` on purpose).
- **`.env.example`** — `REDIS_TIMEOUT_SECONDS=0.3`, `REDIS_BREAKER_SECONDS=5`.
- **Tests** — `core/tests/test_circuit_breaker.py` (new — open/close/interval/log-once-per-trip,
  re-trip logs again after closing), `core/tests/test_bounded_call.py` (new — fast call returns,
  slow call raises `TimeoutError`, the callable's own exception still propagates),
  `core/tests/test_ratelimit.py` (+2 — trips the shared breaker on a Redis error; skips Redis
  entirely while open, asserted by making the mocked script call raise `AssertionError` if it's
  ever invoked), `notifications/tests/test_tasks.py` (+2 — same two shapes for the enqueue path),
  `ingest/tests/test_notifications_integration.py` (+1 — breaker open at enqueue time → `200`,
  stays `pending`, warning logged, and `django_rq.get_queue` is asserted never called).

### Deviations (this follow-up)

- **Wrapping the enqueue path in `bounded_call` broke two existing tests** —
  `test_ham_submission_sends_email_after_commit` and
  `test_send_pending_notifications_enqueues_only_within_window` — because the test fixture runs
  RQ jobs synchronously (`RQ_QUEUES[...]["ASYNC"] = False`), which means `.enqueue()` executes the
  *entire job body* inline as part of that call. Running that call inside `bounded_call`'s worker
  thread pool meant the job's `Submission.objects.get(...)` ran on a different thread — and
  therefore a different, thread-local Django DB connection — than the one holding the test's
  transaction, so it couldn't see the just-created row and silently no-opted (`DoesNotExist`),
  leaving `notification_status=pending` instead of `sent`. In production this can't happen
  (`ASYNC` is `True`, so `.enqueue()` only ever does a fast Redis push, never runs the job body),
  but it's a real correctness bug in *any* context where synchronous execution and thread-bounded
  timeouts combine. Fixed by reverting `_enqueue()` to a plain, unwrapped call — the ingest hot
  path is still protected because `core.ratelimit`'s bounded calls run first in the same request
  and, on a real outage, already trip the shared breaker before `_enqueue()` is ever reached (its
  own `is_open()` check then short-circuits before touching Redis at all). The one narrow residual
  gap: if an `accounts` flow (signup/password-reset) is the *first* Redis touch after the breaker
  has closed during a sustained total-DNS-loss outage, that one request could still block ~4s
  before tripping the breaker for everyone else. Judged not worth chasing further — it's outside
  the ingest path NFR-1 targets, and closing it would mean either the same thread/connection
  hazard for a rare edge case, or a heavier `transaction=True` test rewrite across multiple test
  files.
- The original Day-10 "Redis-outage latency" deviation entry (below, unedited) is now resolved —
  see Live verification for the re-measured numbers.

## Files changed

- **`pyproject.toml` / `uv.lock`** — added `django-anymail>=11.0,<12` (its `postmark`/`resend`/
  `sendgrid` backends implement the three prod-provider options; `console`/`smtp` use Django's own
  backends, so anymail is only ever exercised when one of those three is selected). `uv.lock`
  regenerated inside a throwaway `python:3.12-slim` container with `uv` installed via pip (no local
  `uv` binary on this machine), then the `web`/`worker` images rebuilt from it.
- **`config/settings/base.py`** — `"anymail"` added to `INSTALLED_APPS`; new `EMAIL_PROVIDER` env
  var (`console`/`smtp`/`postmark`/`resend`/`sendgrid`, code default `"console"`) selects
  `EMAIL_BACKEND`, validated at import time via `ImproperlyConfigured` the same way
  `SPAM_MODEL_MODE` already is; `EMAIL_HOST`/`EMAIL_PORT`/`EMAIL_HOST_USER`/
  `EMAIL_HOST_PASSWORD`/`EMAIL_USE_TLS` (read only for `smtp`) and an `ANYMAIL` dict with the three
  provider API key settings (only the active one is ever read). `RQ_QUEUES` gained an `"emails"`
  queue alongside `"default"`.
- **`config/settings/local.py`** — dropped its hardcoded `EMAIL_BACKEND = "...console..."` line;
  `base.py`'s `EMAIL_PROVIDER` (default `"console"`, overridden to `"smtp"` by `.env.example`) now
  drives it.
- **`.env.example`** — `EMAIL_PROVIDER=smtp` (local dev talks to Mailpit out of the box, per
  request) plus `EMAIL_HOST=mailpit`/`EMAIL_PORT=1025`/empty user-password/`EMAIL_USE_TLS=False`
  and dummy `POSTMARK_SERVER_TOKEN`/`RESEND_API_KEY`/`SENDGRID_API_KEY` values (CLAUDE.md rule 12).
- **`docker-compose.yml`** — new `mailpit` service (`axllent/mailpit`, ports `1025`/`8025`);
  `worker`'s command changed to `python manage.py rqworker emails default` (one worker process,
  two queues, emails first) with `mailpit` added to its `depends_on`. `web` is untouched — it never
  talks to SMTP directly, only enqueues to Redis, so NFR-1 is unaffected.
- **`notifications/email.py`** (rewrite) — `send_transactional(to, subject, template, context)`
  keeps its exact signature (every call site — `accounts/emails.py`,
  `accounts/forms.py::TransactionalPasswordResetForm.send_mail` — untouched) but now enqueues via
  `notifications.tasks.enqueue_transactional_job` (imported inside the function to avoid a circular
  import, since `tasks.py` imports this module at the top level). `_send_now(...)` is the old
  synchronous body, private, called only by the job. New `send_submission_email(submission,
  recipients)`: subject `"New submission: <form name>"` (never any payload text), prefixed
  `"[Possible spam] "` when `"model_shadow" in submission.spam_signals`; truncates field values at
  2000 chars with a `[truncated, N characters total]` note, comma-joins list values; sets
  `reply_to` from an `email`/`e-mail`/`email_address` payload field only if it contains no
  `\r`/`\n` (checked before anything else — an explicit, independently-testable header-injection
  guard) and passes `validate_email`.
- **`notifications/tasks.py`** (new) — `RETRY = Retry(max=3, interval=[10, 60, 300])`.
  `enqueue_transactional_job`/`send_transactional_job` wrap `email._send_now`.
  `enqueue_submission_notification`/`send_submission_notification(submission_id)`: re-fetches by
  id (`DoesNotExist` → no-op), no-ops if already `sent` (idempotent), defensively re-checks for a
  verified recipient (ingest already decided this at store time — this only guards a
  verification-state race) and sets `skipped` if none, and on send failure inspects
  `rq.get_current_job().retries_left` (`None`/`<= 0` → this was the final attempt → set `failed`
  and log a warning; otherwise re-raise and leave `pending` for RQ's own retry/backoff to pick up).
  All status writes use `Submission.objects.filter(id=...).update(...)`, never `.save()` on the
  fetched instance, so a concurrent field change elsewhere is never clobbered.
- **`notifications/templates/notifications/email/submission_notification.{txt,html}`** (new) —
  label/value per field, submission time, a link to the form detail page
  (`settings.PUBLIC_BASE_URL + reverse("forms_app:detail", ...)`, `# TODO(Day 11)`: point at the
  submission detail page once it exists). The `.txt` template wraps its field loop in
  `{% autoescape off %}` (first template here rendering raw submitter text — Django autoescapes by
  engine default regardless of file extension); the `.html` template stays autoescaped and uses
  `|linebreaksbr` (escapes before converting newlines, so it's safe under autoescape-on).
- **`ingest/views.py`** — new `_enqueue_notification(form_id, submission_id)` helper: calls
  `enqueue_submission_notification`, catching and logging any exception as a warning (Redis down)
  rather than letting it propagate, since `on_commit` here fires synchronously inside the view
  (no `ATOMIC_REQUESTS`) and an uncaught exception would turn into a 500. Ham branch: checks
  `form.account.users.filter(is_verified=True).exists()` before creating the `Submission`, sets
  `notification_status` to `pending`/`skipped` accordingly, and — only when a verified recipient
  exists — registers `transaction.on_commit(lambda: _enqueue_notification(form.id,
  submission.id))` inside the `atomic()` block, closing only over the two plain UUIDs. Spam+`flag`
  branch: `notification_status=skipped` added to the existing `Submission.objects.create(...)`
  call (FR-5.1). Spam+`drop` branch untouched (no row is ever created there).
- **`notifications/management/commands/send_pending_notifications.py`** (new, plus package
  `__init__.py`s) — enqueues ham submissions with `notification_status=pending`,
  `created_at` between now−24h and now−2min.
- **`forms_app/models.py`** — `Submission.NotificationStatus`
  (`pending`/`sent`/`skipped`/`failed`, default `pending`), `notification_status` field,
  `notified_at` (nullable), and a new `Meta.indexes` entry on `["notification_status",
  "created_at"]` (the two existing indexes are both scoped by `form` first; the management
  command filters across all forms/accounts by status + a time window, so it needs its own
  composite index). Migration **`forms_app/migrations/0003_submission_notification_status.py`**
  (generated via `makemigrations`, then renamed from Django's auto `_and_more` suffix) — plain
  `AddField` ×2 + `AddIndex`, no PK change, no data migration needed (`default="pending"` is
  correct even for a zero-row backfill).
- **root `conftest.py`** — new autouse fixture `_synchronous_rq_queues` forcing, per test, both
  `RQ_QUEUES[...]["ASYNC"] = False` **and** `settings.RQ = {"COMMIT_MODE": "auto"}`. The second
  setting turned out to be load-bearing, not optional (see Deviations below).
- **Tests** — `notifications/tests/test_email.py` (existing tests retargeted at `_send_now`, one
  new test for the public enqueue-then-send round trip), `notifications/tests/test_submission_email.py`
  (new — subject/prefix, no-payload-in-subject, HTML escaping, text non-escaping, truncation, list
  joining, Reply-To valid/invalid/injection, form URL), `notifications/tests/test_tasks.py` (new —
  send+mark-sent, idempotent re-run, deleted-submission no-op, failed-on-final-attempt vs
  pending-when-retries-remain, no-job-context treated as final, defensive skip-if-no-verified-user,
  enqueue calls pass `retry=RETRY`), `notifications/tests/test_commands.py` (new — window
  filtering, spam/skipped rows ignored), `ingest/tests/test_notifications_integration.py` (new,
  using `django_capture_on_commit_callbacks` — ham enqueues only after commit; ham with no
  verified user → skipped, zero callbacks; spam → skipped, zero callbacks; spam+drop → no row;
  Redis-down-at-enqueue → 200, stays `pending`, warning logged), `accounts/tests/test_views.py` /
  `test_password_reset.py` (one new test each — verification/reset email enqueued on the
  `"emails"` queue, not sent inline).

## FRs / SRS sections covered

FR-5.1 (enqueue on new ham submission), FR-5.2 (email content: fields, dashboard link, never
blocks the response), FR-1.2 (notifications blocked until email verified — `skipped`, permanently),
NFR-1 (ingest path: enqueue only, no SMTP/HTTP calls in the request), NFR-3 (worker/Redis down
degrades gracefully — submission still stores, `notification_status` stays `pending` for the
safety-net command to pick up later).

## How to verify manually

```
docker compose run --rm web python manage.py makemigrations --check --dry-run
docker compose run --rm web python manage.py migrate
docker compose run --rm web pytest -q
docker compose run --rm web sh -c "ruff check . && ruff format --check ."
```

## Test results

- `pytest -q`: full suite green, exit code 0, zero failures (the plain-text pass-dot progress bar
  doesn't print a final `N passed` summary line under this `docker compose run --rm` invocation —
  a display quirk of that command, not a test issue; confirmed via exit code and an explicit
  grep for `fail|error` finding nothing).
- `ruff check .` / `ruff format --check .`: clean (fixed one `E501` line-too-long and two
  formatting-only diffs along the way).
- `makemigrations --check --dry-run`: no changes after `migrate` was applied.

## Live verification

Ran the full stack for real (`docker compose up -d web worker mailpit`, rebuilding both the `web`
and **`worker`** images — `docker compose build web` alone left the `worker` service's separate
image stale and missing `anymail`, caught via its startup traceback before the real test began).

1. **Happy path** — created a verified-user account + form via `manage.py shell`, POSTed a ham
   submission. First attempt used the actual local `.env` (gitignored, predates this feature) and
   fell through to the code-default `console` backend — worked correctly (job completed, full
   HTML table rendered to worker stdout) but confirmed the fallback-default design works as
   intended rather than silently failing. Added `EMAIL_PROVIDER=smtp` / `EMAIL_HOST=mailpit` /
   `EMAIL_PORT=1025` to the local `.env` to match `.env.example`, restarted, resubmitted: message
   appeared in Mailpit (`http://localhost:8025`) with subject `"New submission: Smoke Test Form"`
   and `Reply-To: jane@example.com` (from the submitted `email` field) — confirms subject-building,
   HTML rendering, and Reply-To extraction all work against a real SMTP transport, not just
   Django's test `mail.outbox`.
2. **Worker down** — `docker compose stop worker`, submitted → `200`, `notification_status`
   confirmed `pending` (job queued in Redis, nothing to process it yet). `docker compose start
   worker` → within ~3s the queued job ran, `notification_status` flipped to `sent` with
   `notified_at` set, and Mailpit's message count went from 1 to 2.
3. **Redis down** — `docker compose stop redis`, submitted → still `200`
   (`duration_ms=18932.0` logged — see Deviations below), `notification_status` confirmed
   `pending`, and the expected `ingest: failed to enqueue submission notification ...` warning
   (with `redis.exceptions.ConnectionError` traceback via `exc_info=True`) appeared in the `web`
   logs.
4. **Recovery** — `docker compose start redis`; `send_pending_notifications` run immediately
   correctly skipped the Redis-down submission (98.8s old, under the 2-minute floor) while
   enqueuing 10 older pending rows (pre-existing dev-database submissions from earlier days'
   manual testing, retroactively `pending` by the migration's default — harmless, all landed in
   Mailpit). Re-ran the command once the submission had aged past 2 minutes (216s): `Enqueued 1
   pending submission notification(s)`, and the row flipped to `notification_status=sent` with
   `notified_at` set — confirms the safety-net command correctly reprocesses exactly the row an
   enqueue failure left behind, once it clears the window's minimum age.

### Redis-outage latency fix — live re-verification

Re-ran the outage scenario after the fix above, restarting `web`+`worker` first to load the new
settings (confirmed via `/healthz` returning `{"status": "ok", ...}` and the worker log showing it
reconnected cleanly under the new `HOST`/`PORT`-based `RQ_QUEUES` config — a real check, since
django-rq's `"URL"`-vs-`HOST`/`PORT` config shapes are handled by entirely different branches of
`get_redis_connection`).

- `docker compose stop redis`, then 20 submissions fired back-to-back (`curl -w "%{time_total}"`)
  against the same live account/form used in the original pass:
  ```
  n=20  min=0.041s  p50=0.064s  p95=0.109s  max=0.366s
  ```
  All 20 returned `200`; all 20 confirmed `notification_status=pending` in the DB. The single
  `redis circuit breaker tripped; skipping Redis calls for 5.0s` line was logged exactly **once**
  across the whole 20-request burst (checked with `docker logs --since 2m`, since `docker logs`
  otherwise also surfaces trips from the earlier ~19s/~4s runs still in the same container's log
  history). This meets the stated target (first request ≤ ~1s: **0.366s**; the rest well under
  300ms: p50 **64ms**, p95 **109ms** — both far better than the ~1s/300ms bar, not just under it).
- `docker compose start redis`; a submission fired immediately after returned in ~0.1s and was
  still `pending` (breaker still open, correctly time-boxed rather than health-check-gated); by
  the time a follow-up check ran a few seconds later (past `REDIS_BREAKER_SECONDS=5`), a
  submission had already gone through normally end-to-end — `notification_status=sent`, and
  Mailpit's inbox showed the new message — confirming delivery resumes automatically once the
  breaker's interval elapses, with no manual intervention.

## Deviations from the spec / open items

- **django-rq 4.2.0's default `COMMIT_MODE` is `"on_db_commit"`**, not the `"auto"`/immediate
  behavior an older version's `AUTOCOMMIT` default might suggest: `Queue.enqueue_call` itself
  wraps dispatch in `transaction.on_commit(...)` whenever `connection.in_atomic_block` is true —
  independent of, and layered on top of, our own explicit `transaction.on_commit(...)` in
  `ingest/views.py`. Since `pytest-django`'s `@pytest.mark.django_db` wraps an entire test in one
  atomic block, this meant `RQ_QUEUES[...]["ASYNC"] = False` alone was not sufficient to make jobs
  run synchronously in tests — django-rq's own internal on-commit deferral still applied and
  never fired on rollback. Fixed by also forcing `settings.RQ = {"COMMIT_MODE": "auto"}` in the
  test fixture; this only disables *django-rq's* internal deferral, not our own explicit
  `on_commit` calls in `ingest/views.py`, which still require `django_capture_on_commit_callbacks`
  in tests exactly as designed. In production this double-deferral is harmless (each layer just
  calls back immediately once no atomic block is open), but it means the `ingest/views.py`
  wrapping is technically redundant with what django-rq now does automatically — kept anyway
  since the spec explicitly calls for `transaction.on_commit`, and it keeps the enqueue-failure
  `try/except` unambiguously ours to control rather than dependent on a third-party library's
  internal commit-mode default.
- **Redis-outage latency**: the live Redis-down test originally measured **~19 seconds** for the
  full ingest request to return (still `200`, as designed), not the sub-300ms NFR-1 target —
  `redis.Redis.from_url(...)` was used with no `socket_connect_timeout` both in the RQ enqueue path
  and in the pre-existing `core/ratelimit.py` rate limiter. **Fixed** — see the "Follow-up:
  Redis-outage latency fix" section at the top of this file for the design and re-measured numbers
  (p50 64ms / p95 109ms / max 366ms across a 20-request outage burst).
- Everything else matches the approved plan.

## Follow-ups (not built now)

- The narrow residual gap noted above: an `accounts` flow (signup/password-reset) that happens to
  be the very first Redis touch after the breaker closes during a sustained outage could still
  see one ~4s-latency request before tripping the breaker for everyone else. Not fixed — see
  Deviations in the Redis-outage-latency section for why.
- Day 11 dashboard: point the email's form link at the submission detail page once it exists
  (`# TODO(Day 11)` left in `notifications/email.py::_form_url`); surface `notification_status`
  (esp. `failed`) in the submissions list.
- Day 13: schedule `send_pending_notifications` via cron.

## Suggested commits

1. `feat(notifications): add django-anymail and EMAIL_PROVIDER-driven backend selection`
   — `pyproject.toml`, `uv.lock`, `config/settings/base.py`, `config/settings/local.py`,
   `.env.example`, `docker-compose.yml`

2. `feat(forms_app): add Submission.notification_status/notified_at (FR-5.1)`
   — `forms_app/models.py`, `forms_app/migrations/0003_submission_notification_status.py`

3. `feat(notifications): enqueue transactional email via RQ instead of sending inline`
   — `notifications/email.py`, `notifications/tasks.py`, `notifications/tests/test_email.py`,
   `notifications/tests/test_tasks.py`, `conftest.py`, `accounts/tests/test_views.py`,
   `accounts/tests/test_password_reset.py`

4. `feat(notifications): submission notification email content and templates (FR-5.2)`
   — `notifications/templates/notifications/email/submission_notification.txt`,
   `notifications/templates/notifications/email/submission_notification.html`,
   `notifications/tests/test_submission_email.py`

5. `feat(ingest): enqueue submission notification on commit for stored ham (FR-5.1, NFR-3)`
   — `ingest/views.py`, `ingest/tests/test_notifications_integration.py`

6. `feat(notifications): add send_pending_notifications management command`
   — `notifications/management/__init__.py`,
   `notifications/management/commands/__init__.py`,
   `notifications/management/commands/send_pending_notifications.py`,
   `notifications/tests/test_commands.py`

7. `fix(core): bound Redis client timeouts and add a shared circuit breaker (NFR-1)`
   — `config/settings/base.py`, `.env.example`, `core/circuit_breaker.py`, `core/bounded_call.py`,
   `core/ratelimit.py`, `core/views.py`, `notifications/tasks.py`, `conftest.py`,
   `core/tests/test_circuit_breaker.py`, `core/tests/test_bounded_call.py`,
   `core/tests/test_ratelimit.py`, `notifications/tests/test_tasks.py`,
   `ingest/tests/test_notifications_integration.py`

8. `docs(progress): add Day 10 summary`
   — `docs/progress/day-10.md`

Commit 3 depends on commit 2 (the job writes `notification_status`, which must exist). Commit 5
depends on commits 2, 3, and 4 (it wires the enqueue call and needs the templates/content to exist
for its integration tests to exercise a real send). Commit 6 depends on commits 2 and 3. Commit 7
depends on commits 3 and 5 (it edits `notifications/tasks.py` and adds tests to
`ingest/tests/test_notifications_integration.py`, both created by those commits) but is otherwise
independent — it touches no file from commits 1/2/4/6. No file is split across commits.
