# Day 12 — Label correction, monitoring, retention purge

## Summary

Closes the feedback loop described in SRS §7 and the retention half of NFR-6,
both deferred since Day 9b/Day 11b. Owners can now flip a submission's label
from the dashboard (FR-4.4) — via HTMX with a toast+Undo on both the
submissions list and the detail page, or via a plain POST fallback with no
JS — which sets/maintains a new `corrected`/`corrected_at`/`original_status`
trio on `Submission`. Ham rows the model would have flagged in shadow mode
now surface a "Possible spam" pill and filter tab. `spam/monitoring.py` +
`manage.py spam_report` report score distribution, spam rate, false-positive/
negative counts, correction rate, and shadow-mode precision, per model
version and overall, with a WARNING-log alert when the false-positive rate
crosses a threshold. `Form.retention_days` (already on the model since Day 4,
unused until now) is exposed on the form-edit page, capped by plan, and a new
`purge_expired_submissions` command deletes submissions past their form's
effective retention in batches, never touching `UsageEvent`.

Full plan this was built from:
`C:\Users\USER\.claude\plans\read-claude-md-docs-srs-md-sections-abstract-avalanche.md`.

## Files changed

**Data model (`Submission.original_status`/`corrected_at`, `billing.plans`
plumbing both label correction and retention depend on)**
- `forms_app/models.py` — `Submission` gains `original_status` (set once at
  ingest, never touched again) and `corrected_at` (nullable). `Form` gains
  an `effective_retention_days` property (`self.retention_days or
  retention_days_for(self.account)`).
- `forms_app/migrations/0004_submission_original_status_corrected_at.py` —
  adds both fields; `original_status` gets a one-off `default="ham"` for the
  `AddField` (existing rows), then a `RunPython` step backfills it from
  `status` via `F("status")`, per the task spec ("backfilled from status for
  existing rows").
- `forms_app/admin.py` — `SubmissionAdmin` lists/filters the two new fields.
- `billing/plans.py` — `get_plan(account)` (the unknown-plan-fallback lookup,
  moved here from `billing/limits.py::_plan_config` so plan lookup has one
  home per CLAUDE.md rule 6), `RETENTION_DAY_CHOICES = [7, 14, 30, 60, 90]`,
  `retention_days_for(account)`, `retention_choices_for(account)`.
- `billing/limits.py` — `_plan_config` is now a one-line wrapper around
  `billing.plans.get_plan`; no behavior change (confirmed by the existing
  `test_unknown_plan_falls_back_to_free_and_logs_warning` test, unchanged).
- `ingest/views.py` — both `Submission.objects.create(...)` call sites (ham
  and spam branches) now also set `original_status=status`.
- Test-factory consistency fixes only (no assertions changed): every
  `_make_submission`-style helper across `dashboard/tests/test_views.py`,
  `notifications/tests/{test_commands,test_submission_email,test_tasks}.py`,
  and `forms_app/tests/test_models.py` now also passes `original_status`
  (defaulted to the same value as `status`) — without this, `Submission`
  objects.create() would have silently stored `original_status=""` for every
  existing test (Django doesn't error on a missing non-nullable `CharField`
  with no `default`, it just uses `""`; nothing crashed, but it would have
  been silently wrong for any test that later inspected the field).
- `billing/tests/test_plans.py` (new) — `get_plan`/`retention_days_for`/
  `retention_choices_for`.

**Label correction (FR-4.4)**
- `dashboard/views.py` — new `submission_label` view (`@require_POST`,
  owner-scoped via the existing `_get_owned_form`/`_get_owned_submission`
  helpers). Flips `status`, recomputes `corrected`/`corrected_at` from
  `status != original_status`, never touches `UsageEvent`/quota/
  notifications (the view simply never references them). Three response
  shapes for an HTMX request (`fragment` POST field: `row`, `status`,
  `panel` — see design note below); a non-HTMX POST sets a `messages.success`
  toast and redirects to a `url_has_allowed_host_and_scheme`-validated
  `next` (falling back to the submissions list) — first use of that Django
  helper in the repo. Also: `STATUS_FILTERS`/`_STATUS_FILTER_VALUES` (now
  including `possible_spam`), `_filter_submissions`/`_row_visible_under_filter`
  /`_submission_list_context` extracted so `submission_list`, `submissions_csv`,
  and the label view's own re-renders share one filtering implementation.
- `dashboard/urls.py` — `forms/<pk>/submissions/<submission_pk>/label` →
  `dashboard:submission_label`.
- `dashboard/templates/dashboard/_submission_row.html` (new) — the list
  row, extracted verbatim from `submissions_list.html`'s loop (plus a
  `submission-row` class, the possible-spam pill, and the flip form) so it's
  the single source of truth for both the full-page list render and the
  label view's row-fragment response.
- `dashboard/templates/dashboard/_submission_status.html` (new) — the
  detail page's status `kv-row`, now `id="submission-status"` (the HTMX
  swap target), with the possible-spam/corrected pills and the flip form.
- `dashboard/templates/dashboard/_toast_oob.html` (new) — see design note.
- `dashboard/templates/dashboard/submissions_list.html` — row loop now
  `{% include "dashboard/_submission_row.html" %}`; new possible-spam
  empty-state branch.
- `dashboard/templates/dashboard/submission_detail.html` — status `kv-row`
  replaced by `{% include "dashboard/_submission_status.html" %}`.
- `templates/_messages.html` — `#toast-container` is now always rendered
  (previously only inside `{% if messages %}`), so an HTMX response always
  has somewhere to out-of-band-insert a toast into, even on a page that
  loaded with zero Django messages.
- `static/js/app.js` — `initToasts()`'s per-toast wiring extracted into
  `activateToast(toast)` (idempotent, guarded by `data-activated`), called
  both on `DOMContentLoaded` (existing toasts) and from a new
  `initHtmxToasts()` that rescans `#toast-container .toast` after every
  `htmx:afterSwap` (which also fires once OOB swaps settle) — needed because
  HTMX-injected toasts arrive outside the `DOMContentLoaded` pass.
- `static_src/css/input.css` / `tailwind.config.js` — new `warn`/`warn-soft`
  color tokens and `.pill-warn` (no amber token existed before — only
  `signal`/`danger`/`line`/`ink`); `.submission-row`/`.submission-row.htmx-swapping`
  opacity transition (same idea as the existing `#submissions-panel` cross-fade,
  generalized to a class since rows don't have unique ids).
- `dashboard/tests/test_submission_label.py` (new) — 404s (other account,
  other form same account), GET→405, flip both directions sets/clears
  `corrected`/`corrected_at`, `original_status` immutable, idempotent
  same-status flip, invalid `status`→400, never touches `UsageEvent` or
  `notification_status`, HTMX fragment responses (status/row, including the
  collapse-to-empty case under a mismatched filter), toast+Undo markup,
  non-HTMX redirect preserving `next` (and rejecting an off-host one).
- `dashboard/tests/{test_submissions_list,test_submission_detail,test_submissions_csv}.py`
  — possible-spam filter/pill/CSV tests; detail-page flip-button-label test.

**Design note — HTMX fragment shapes and a real bug found live-testing them:**
The label view picks one of three response shapes via a `fragment` hidden
field the caller sends: `status` (detail page — swaps `#submission-status`),
`row` (list page — swaps the clicked `<li>`, or returns empty so it fades out
via the `.submission-row.htmx-swapping` transition when the new status no
longer matches the current filter tab), and `panel` (the Undo button when it
was reached from a list row — re-renders the *whole* `submissions_list.html`
page and lets the client's `hx-select="#submissions-panel"` carve out the
fragment, exactly like the existing filter-tab links already do; deliberate
simplification since Undo is rare enough that a full-panel refresh instead of
re-locating a possibly-already-removed row is the pragmatic choice — Undo
from the detail page just uses `fragment=status`, no collapse problem there).

Every HTMX response also appends an out-of-band toast. **Two real bugs
surfaced only by loading this in an actual browser (curl and the Django test
client both hid them — see Test results below):**
1. `templates/_messages.html` had a two-line `{# ... #}` comment. Django's
   `{# #}` tag cannot span multiple lines (undocumented-in-practice but real
   limitation — the tokenizer regex has no `DOTALL`); mine silently fell back
   to literal *text*, rendering as visible garbage at the top of every
   authenticated page. Caught by eyeballing a Playwright screenshot. Fixed by
   switching to `{% comment %}...{% endcomment %}`, which is multi-line safe.
2. `_toast_oob.html`'s first draft wrapped the whole `.toast` div itself in
   `hx-swap-oob="beforeend:#toast-container"`. That's backwards: htmx's
   position-based OOB swap styles (`beforeend`/`afterbegin`/etc.) insert the
   *content* of the oob-marked element into the selector-matched target — the
   marked element's own tag is only a carrier (its ID is what participates in
   matching for the plain `hx-swap-oob="true"` case). So every toast landed
   in `#toast-container` with its `class="toast"` wrapper stripped off,
   leaving unstyled, JS-inert content — `.toast` never matched anything, so
   nothing ever became visible. Confirmed via `htmx:afterSwap`/`oobAfterSwap`
   event tracing in a real Playwright session (dev-only `var/debug_flip.py`,
   deleted — see Fixes below for the debugging trail). Fixed by moving the
   OOB marker onto a `<div id="toast-container" hx-swap-oob="beforeend">`
   *wrapper* with the real `.toast` div nested inside as its content — this
   mirrors htmx's own canonical "append to a list" example, which also
   id-matches an element to itself for exactly this reason.

**Shadow visibility ("Possible spam")**
Definition matches `notifications/email.py`'s existing `"[Possible spam]"`
subject-prefix logic exactly (`status == ham and "model_shadow" in
spam_signals`) — no new signal/status invented. Pill + filter tab covered
above; CSV export's `_payload_key_union` raw-SQL helper also handles
`status=possible_spam` (JSONB `@>` containment) so the header/rows stay
correct under that filter.

**Monitoring (SRS §7)**
- `spam/monitoring.py` (new) — `build_report(days=7)`: per-model-version
  (plus a `heuristics-only` bucket for `model_version=None`, and one
  `overall` row) `VersionStats` — scored/unscored counts, spam rate, a
  10-bucket `[0,1]` score histogram, false positives (`original_status=spam,
  status=ham`) and negatives (`original_status=ham, status=spam`),
  corrections and correction rate. Shadow evidence computed once (not per
  version): among `model_shadow` rows older than 48h *and* inside the
  `--days` window, how many the owner confirmed as spam vs. left as ham,
  reported with the row count so a small sample is obvious.
  `check_fp_alert(overall)` — false-positive rate among spam-labelled rows,
  logs a `logging.getLogger("spam")` WARNING when it exceeds
  `SPAM_FP_ALERT_RATE` (default 0.02) *and* there are at least
  `SPAM_ALERT_MIN_ROWS` (default 50) spam-labelled rows; called from
  `build_report` itself so any future caller gets the same alerting.
- `spam/management/commands/spam_report.py` (new) — `--days` (default 7); a
  thin formatter over `monitoring.py`, matching `eval_spam_model.py`'s
  existing shape.
- `config/settings/base.py` / `.env.example` — `SPAM_FP_ALERT_RATE`,
  `SPAM_ALERT_MIN_ROWS`, same `env(...)` pattern as `SPAM_MODEL_MODE`.
- `spam/tests/test_monitoring.py`, `spam/tests/test_spam_report_command.py`
  (new) — seeded FP/FN/shadow-confirmed/shadow-unconfirmed mix; alert fires
  above both thresholds, not below either; no payload substring ever in a
  report or command output.

**Retention (NFR-6)**
- `forms_app/forms.py` — `FormEditForm` gains a declared `retention_days =
  TypedChoiceField(coerce=int, choices=[])`, with `choices` built in
  `__init__` from `retention_choices_for(self.instance.account)` (so an
  out-of-cap value is a normal Django choice-validation error, no extra
  `clean_retention_days` needed) and `initial` defaulting to
  `effective_retention_days`.
- `forms_app/templates/forms_app/form_detail.html` — new "Retention" `kv-row`
  ("Submissions are deleted after N days."); the field itself already
  renders via the existing generic `{% include "_form_fields.html" %}`.
- `forms_app/management/commands/purge_expired_submissions.py` (new;
  `forms_app` rather than `spam` since this is about `Form`/`Submission`,
  not spam scoring) — `--dry-run`, `--batch-size` (default 1000). Per form,
  computes `now - effective_retention_days`, fetches expired ids ordered by
  `pk`, deletes in `batch_size` chunks each inside its own
  `transaction.atomic()`. Logs one line per form with the count (never
  content); `UsageEvent` is never referenced, so it's untouched by
  construction.
- `forms_app/tests/test_forms.py`, `forms_app/tests/test_views.py` —
  retention-choice tests (capped by plan, over-cap rejected, initial value);
  the pre-existing `_edit()` helper and `test_token_cannot_be_changed_via_post`
  now pass `retention_days` (a required field as of this change — both were
  failing without this fix, see Test results).
- `forms_app/tests/test_purge_expired_submissions.py` (new) — respects
  per-form/plan-default retention, `UsageEvent` survives, dry-run deletes
  nothing but still reports counts, multiple `transaction.atomic()` batches
  with a small `--batch-size` (asserted via `CaptureQueriesContext` counting
  `SAVEPOINT` statements, not by mocking `transaction.atomic`).

**Demo tooling** (gitignored, not part of any commit below)
- `var/seed_demo.py` — `original_status` added everywhere; new seeded rows: a
  confirmed shadow row (flipped ham→spam, `corrected=True`), an unconfirmed
  one (left ham), a false positive and a false negative, and three
  submissions past the free plan's 30-day retention.
- `scripts/screenshots.py` — new `submissions-possible-spam` page.
- `scripts/interaction_checks.py` — new `check_label_flip_and_undo` (click
  the detail-page flip button, assert the pill updates and a toast+Undo
  appears; click Undo, assert the original status is restored).

## FRs / NFRs covered

- **FR-4.4** — owner label correction, `corrected` flag, from the dashboard.
- **SRS §7 (feedback loop / monitoring)** — score distribution, spam rate,
  owner-correction rate, shadow evidence, false-positive alert threshold.
- **NFR-6 (retention)** — per-form retention capped by plan, exposed in the
  UI; `purge_expired_submissions` deletes only what's past that retention.

## How to verify manually

```
docker compose up -d --build web worker tailwind
docker compose run --rm web python manage.py migrate
docker compose run --rm web sh -c "ruff check . && ruff format --check . && pytest -q"
docker compose run --rm web python var/seed_demo.py
docker compose run --rm web python manage.py spam_report --days 7
docker compose run --rm web python manage.py purge_expired_submissions --dry-run
docker compose run --rm web python manage.py purge_expired_submissions
```
Then in the browser: `/forms/<id>/submissions?status=possible_spam`, flip a
row and confirm the toast+Undo; `/forms/<id>/submissions/<sid>`, flip and
confirm the status pill + toast; `/forms/<id>` → Settings → change retention
and save.

## Test results — this session, all green

```
docker compose run --rm web python manage.py makemigrations --check --dry-run   # No changes detected
docker compose run --rm web python manage.py migrate                            # Applying forms_app.0004_..._corrected_at... OK
docker compose run --rm web sh -c "ruff check . && ruff format --check ."       # All checks passed! / 157 files already formatted
docker compose run --rm web pytest -q                                          # 455 passed
```

**Test count: 455 passed, up from 359 on Day 11b (+96).** No decreases.
Breakdown of the new/changed test files' counts: `dashboard/tests/
test_submission_label.py` 18 (new), `spam/tests/test_monitoring.py` 13 (new),
`spam/tests/test_spam_report_command.py` 4 (new), `forms_app/tests/
test_purge_expired_submissions.py` 8 (new), `billing/tests/test_plans.py` 4
(new), plus additions to `dashboard/tests/{test_submissions_list,
test_submission_detail,test_submissions_csv}.py` and `forms_app/tests/
{test_forms,test_models}.py`.

**`spam_report --days 7` on seeded data:**
```
Spam report — last 7 day(s)

Overall:
  submissions scored: 101
  unscored (heuristics only): 6
  spam rate: 0.149 (15 spam)
  score histogram (10 buckets, 0.0-1.0): [38, 43, 0, 0, 0, 0, 0, 5, 7, 2]
  false positives (spam -> ham): 1 / 14 spam-labelled
  false negatives (ham -> spam): 2 / 87 ham-labelled
  corrections: 3 / 101 (rate=0.030)

Model version: 20260926T174759Z
  submissions scored: 52
  ...
Model version: 20260926T134543Z
  submissions scored: 9
  ...
Model version: heuristics-only
  submissions scored: 40
  unscored (heuristics only): 6
  spam rate: 0.375 (15 spam)
  false positives (spam -> ham): 1 / 14 spam-labelled
  false negatives (ham -> spam): 2 / 26 ham-labelled
  corrections: 3 / 40 (rate=0.075)

Shadow evidence (model_shadow rows older than 48h):
  1 confirmed spam, 1 left as ham, out of 2 (observed precision=0.500)

No alert threshold crossed.
```
Matches the seeded mix exactly (1 FP, 2 FN, 1 confirmed + 1 unconfirmed
shadow row).

**`purge_expired_submissions`:** `--dry-run` reported "Would delete 3
expired submission(s)." and left the DB untouched (confirmed via a direct
count); the real run reported "Deleted 3 expired submission(s)." and the
`Submission` count dropped 104→101 while `UsageEvent` count (61) was
unchanged before/after.

**Browser (via curl, session cookie + CSRF token, simulating both paths):**
- Non-HTMX POST (no `HX-Request` header): `302` redirect to the submissions
  list, `messages` cookie carrying "Marked as spam.", DB shows
  `status=spam, original_status=ham, corrected=True, corrected_at` set.
- HTMX POST (`HX-Request: true`, `fragment=status`): `200` with the
  `#submission-status` fragment (new pill + flipped button label) followed
  by the OOB toast+Undo fragment; DB shows `corrected=False,
  corrected_at=None` after flipping back to `original_status`.

**Playwright** (`scripts/screenshots.py`, `scripts/interaction_checks.py`,
official `mcr.microsoft.com/playwright/python:v1.47.0-jammy` image): all 23
screenshots regenerated (including the new `submissions-possible-spam`
pages) and reviewed by hand — this is what caught the `{# #}` comment bug
(visible garbage text at the top of every page in the first pass, gone after
the fix). All 7 interaction checks pass, including the two new ones:
"Label flip: status pill updates and a toast with Undo appears" and "Label
flip: Undo restores the original status" — this is what caught the OOB-swap
bug (first pass timed out waiting for `.toast` to appear; passes now).

## Fixes made this session

- **Real bug — multi-line `{# #}` Django comment rendered as literal text.**
  See the Design note above. `templates/_messages.html`.
- **Real bug — OOB toast never appeared (wrong element carried
  `hx-swap-oob`).** See the Design note above. `dashboard/templates/
  dashboard/_toast_oob.html`. Found by writing a throwaway
  `var/debug_flip.py` (gitignored, deleted before finishing) that logged
  `htmx:beforeSwap`/`htmx:oobBeforeSwap`/`htmx:oobAfterSwap`/`htmx:afterSwap`
  and dumped `#toast-container`'s live `innerHTML` after a real click —
  curl and the Django test client both only inspect the HTTP response body,
  never actual post-swap DOM state, so neither could have caught this; only
  a real browser executing htmx's own JS could.
- **Test bug (not a product bug) — two possible-spam tests asserted plain
  substring "Possible spam" instead of the actual pill markup**, so they
  passed even before the pill existed on rows, because the new "Possible
  spam" *filter tab* text (present on every list-page render regardless of
  any row's content) made the naive substring always true. Tightened both
  to assert the literal `<span class="pill pill-warn">Possible spam</span>`
  markup. `dashboard/tests/{test_submissions_list,test_submission_detail}.py`.

## Deviations from the plan

None — the approved plan's HTMX fragment design (row/status/panel,
OOB toast) is implemented as written; the two bugs above were implementation
mistakes surfaced by live-testing, not plan changes.

## Follow-ups (not done today)

- **Retraining on real/corrected submissions** — explicitly out of scope per
  the task brief: needs a privacy-policy disclosure first (Day 14). The
  `corrected=True` rows this feature produces are exactly the "labelled data
  flywheel" SRS §7 describes, but no retraining pipeline or UI was built.
- Cron scheduling for `spam_report` and `purge_expired_submissions` is Day 13
  (both commands are already `--dry-run`/idempotent-safe to run repeatedly).

## Suggested commits

Ordered so each passes the full test suite on its own; no file split across
commits. `forms_app/models.py` needs `billing/plans.py`'s new functions to
import correctly, so the data-model commit carries both.

1. `feat(forms_app,billing): Submission.original_status/corrected_at, Form.effective_retention_days`
```
git add forms_app/models.py forms_app/migrations/0004_submission_original_status_corrected_at.py forms_app/admin.py billing/plans.py billing/limits.py billing/tests/test_plans.py ingest/views.py forms_app/tests/test_models.py notifications/tests/test_commands.py notifications/tests/test_submission_email.py notifications/tests/test_tasks.py dashboard/tests/test_views.py
git commit -m "feat(forms_app,billing): Submission.original_status/corrected_at, Form.effective_retention_days"
```

2. `feat(dashboard): label correction — flip endpoint, HTMX toast+Undo, possible-spam visibility (FR-4.4)`
```
git add dashboard/views.py dashboard/urls.py dashboard/templates/dashboard/_submission_row.html dashboard/templates/dashboard/_submission_status.html dashboard/templates/dashboard/_toast_oob.html dashboard/templates/dashboard/submissions_list.html dashboard/templates/dashboard/submission_detail.html templates/_messages.html static/js/app.js static_src/css/input.css tailwind.config.js dashboard/tests/test_submission_label.py dashboard/tests/test_submissions_list.py dashboard/tests/test_submission_detail.py dashboard/tests/test_submissions_csv.py scripts/screenshots.py scripts/interaction_checks.py
git commit -m "feat(dashboard): label correction - flip endpoint, HTMX toast+Undo, possible-spam visibility (FR-4.4)"
```

3. `feat(forms_app): per-form retention capped by plan + purge_expired_submissions (NFR-6)`
```
git add forms_app/forms.py forms_app/templates/forms_app/form_detail.html forms_app/tests/test_forms.py forms_app/tests/test_views.py forms_app/management/__init__.py forms_app/management/commands/__init__.py forms_app/management/commands/purge_expired_submissions.py forms_app/tests/test_purge_expired_submissions.py
git commit -m "feat(forms_app): per-form retention capped by plan + purge_expired_submissions (NFR-6)"
```

4. `feat(spam): spam_report monitoring command — score/FP-FN/correction/shadow stats (SRS 7)`
```
git add spam/monitoring.py spam/management/commands/spam_report.py spam/tests/test_monitoring.py spam/tests/test_spam_report_command.py config/settings/base.py .env.example
git commit -m "feat(spam): spam_report monitoring command - score/FP-FN/correction/shadow stats (SRS 7)"
```

5. `docs(progress): Day 12 summary`
```
git add docs/progress/day-12.md
git commit -m "docs(progress): Day 12 summary"
```

Then:
```
git status   # expected: clean
```
