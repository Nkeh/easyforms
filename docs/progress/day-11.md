# Day 11 — Dashboard + styling

## Summary

Wired in Tailwind (standalone CLI, no Node) and a vendored HTMX, restyled every
existing page, and built the submissions dashboard: per-form ham/spam/ham-this-month
counts (FR-6.4), a filterable paginated submissions list (FR-6.1), a submission
detail page (FR-6.2), CSV export (FR-6.3), and submission delete (NFR-6). Fixed
the `# TODO(Day 11)` in `notifications/email.py` so the submission-notification
email now links to the new detail page instead of the form page.

## Files changed

**Tailwind/HTMX build**
- `Dockerfile` — new `tailwind-cli` stage (pinned `v3.4.17` standalone binary,
  downloaded and SHA-256-verified against a hash computed at implementation
  time — Tailwind publishes no official per-binary checksum, so this is a
  TOFU pin) and `tailwind-build` stage (copies `tailwind.config.js`,
  `static_src/`, and every app's `templates/`, runs a one-shot minified
  build). The final stage copies the built `static/css/app.css` in after
  `COPY . .` so it isn't clobbered.
- `docker-compose.yml` — new `tailwind` service (`target: tailwind-cli`,
  bind-mounted, `-w`/`--watch` + `--poll`, `stdin_open: true` + `tty: true`).
  `--poll` and the stdin/tty flags were both required in practice, not just
  belt-and-suspenders — see Deviations below.
- `tailwind.config.js` (new), `static_src/css/input.css` (new) — the three
  `@tailwind` directives only, no custom layer.
- `static/js/htmx.min.js` (new) — vendored HTMX `v1.9.12`, header comment
  records the version and the upstream file's SHA-256.
- `config/settings/base.py` — `STATICFILES_DIRS = [BASE_DIR / "static"]`.
- `.gitignore` — `static/css/app.css` (build artifact; the rest of `static/`
  stays tracked so the vendored HTMX file is checked in).

**Restyle (Tailwind classes only, no behavior change except where noted)**
- `core/forms.py` (new) — `TailwindStyledForm` mixin; sets a Tailwind input
  class on every field's widget in `__init__` by widget type, so individual
  form classes don't repeat the class string.
- `accounts/forms.py` — `SignupForm`, `EmailAuthenticationForm`,
  `TransactionalPasswordResetForm` now mix in `TailwindStyledForm`; added
  `StyledSetPasswordForm` (Django's built-in `SetPasswordForm` styled) and
  wired it into `accounts/urls.py`'s `PasswordResetConfirmView`.
- `forms_app/forms.py` — `FormCreateForm`, `FormEditForm` mix in
  `TailwindStyledForm`.
- `templates/base.html`, `templates/rate_limited.html`,
  `templates/_form_fields.html` (new — shared field-loop partial used by
  every form template), all of `accounts/templates/accounts/*`,
  `forms_app/templates/forms_app/{form_detail,form_new}.html`,
  `ingest/templates/ingest/{thanks,error}.html` — restyled. `form_detail.html`
  also gained a "View submissions" link.

**Dashboard**
- `dashboard/views.py` — rewritten. `home()` now annotates `account.forms`
  with `ham_count`/`spam_count`/`ham_this_month` in one query (conditional
  `Count(..., filter=Q(...))`, no per-form loop) and adds a
  `check_limit(account, "submissions")` call. New views: `submission_list`,
  `submission_detail`, `submission_delete`, `submissions_csv`, plus local
  `_get_owned_form`/`_get_owned_submission` scoping helpers (same idiom as
  `forms_app._get_owned_form`).
- `dashboard/urls.py` — four new routes under `forms/<uuid:pk>/submissions...`
  (see FR-6.1–6.3 below); `dashboard/home.html` unaffected as `dashboard:home`.
- `dashboard/templates/dashboard/home.html` — restyled + new Ham/Spam/Ham
  this month columns + a "Submissions" link per row.
- `dashboard/templates/dashboard/submissions_list.html` (new),
  `submission_detail.html` (new), `submission_delete_confirm.html` (new).

**Notification link fix**
- `notifications/email.py` — `_form_url(form)` replaced with
  `_submission_url(submission)`, now reverses `dashboard:submission_detail`.
- `notifications/tests/test_submission_email.py` — updated expected URL.

**Tests (new/extended)**
- `dashboard/tests/test_views.py` — per-form count assertions; a query-count
  regression test comparing 1-form vs. 5-form request query counts (proves no
  N+1, without hardcoding an absolute count tied to auth-middleware internals).
- `dashboard/tests/test_submissions_list.py` (new), `test_submission_detail.py`
  (new), `test_submissions_csv.py` (new).

## FRs / NFRs covered

FR-6.1 (list, filter, paginate), FR-6.2 (detail), FR-6.3 (CSV export),
FR-6.4 (per-form + account usage counts), NFR-6 (confirm-then-delete),
NFR-7 (focus states, labels, heading order — see Verification below).

## How to verify manually

```
docker compose up -d db redis mailpit
docker compose up -d --build web worker tailwind   # tailwind needs --build once
docker compose run --rm web python manage.py migrate
```

Then, logged in as a form owner:
- `/dashboard` — per-form Ham/Spam/Ham-this-month columns, styled table.
- `/forms/<id>/submissions` — filter links (`?status=ham|spam|all`) work as
  plain links and swap in place when JS/HTMX is active (`hx-select` pulls
  just the `#submissions-panel` fragment out of the full-page response —
  there's no server-side `HX-Request` branching).
- `/forms/<id>/submissions/<sid>` — every payload field shown, escaped, no
  auto-linked URLs; "Delete submission" → confirm page → POST deletes.
- `/forms/<id>/submissions.csv` — downloads with a UTF-8 BOM, union header,
  CSV-injection-guarded cells.

## Test results

`docker compose run --rm web sh -c "ruff check . && ruff format --check . && pytest -q"`
— all checks pass, full suite green (398 tests).

## Live verification (screenshot-free)

- Built image: Tailwind CLI download + SHA-256 check passed; `tailwindcss
  --minify` produced `static/css/app.css`, copied into the final image.
- Seeded a demo account/form/submissions via `manage.py shell`, logged in with
  `curl` (CSRF token from the login page + session cookie), then confirmed via
  `curl`:
  - `/dashboard` → 200, `<link rel="stylesheet" href="/static/css/app.css">`
    present, `/static/css/app.css` and `/static/js/htmx.min.js` both serve 200.
  - `/forms/<id>/submissions?status=ham` (plain link, no JS) → only ham rows.
  - Same request with `HX-Request: true` → 200 (full page; client-side
    `hx-select` does the fragment extraction, confirmed by reading the
    response — no separate partial template exists to verify server-side).
  - `/forms/<id>/submissions/<sid>` → 200, shows spam score/model
    version/delete link; `/delete` (GET) → confirm page, doesn't delete.
  - `/forms/<id>/submissions.csv` → BOM (`EF BB BF`) confirmed byte-for-byte,
    header `id,created_at,status,spam_score,message,name` (sorted union),
    CRLF line endings from `csv.writer`'s default dialect.
  - A different account's form → 404 on `/submissions`.
  - Cleaned up the demo account afterward.

## Deviations from the plan

- **Tailwind `--watch` needed two extra fixes beyond the plan.** First,
  `entrypoint: tailwindcss` (a bare string) is Compose *shell form*, which
  silently drops the `command:` args — the container ran bare `tailwindcss`
  with no args and exited immediately. Fixed by using list/exec form:
  `entrypoint: ["tailwindcss"]`. Second, even after that fix the process
  still exited immediately in both `up -d` and attached `run` — traced to
  `stdin_open`/`tty` not being set, so the container's stdin was closed
  (EOF), which the standalone binary appears to treat as a shutdown signal.
  Added `stdin_open: true` and `tty: true`. Third, once the process stayed
  running, file changes made from the Windows host side weren't detected via
  inotify through the bind mount (a known Docker-Desktop-on-Windows
  limitation for host-path bind mounts) — added `--poll`, confirmed a template
  edit triggers a rebuild (with several seconds of latency, which is the
  polling tradeoff, not a bug).
- **CSV filename slug**: confirmed with the user — uses
  `slugify(form.name)` (falling back to the form's id if that's empty), not
  `form.token`, since "form-slug" reads as name-derived and `Form` has no
  literal slug field.
- **WhiteNoise/`collectstatic` deferred to Day 13** (confirmed with the
  user) — `runserver` already serves `STATICFILES_DIRS` fine while
  `DEBUG=True`; a real `DEBUG=False` deploy needs WhiteNoise, which is Day
  13's job per the SRS build order. The built CSS is still copied into the
  final image today, per the plan.

## Follow-ups (not done today)

- WhiteNoise middleware + `STATIC_ROOT`/`collectstatic` for real static
  serving under `DEBUG=False` — Day 13.
- Label correction (`corrected` flag) and retention purge — Day 12, per the
  SRS; out of scope here as instructed.
- The submissions-list HTMX enhancement always re-fetches the full page and
  extracts a fragment client-side (`hx-select`) rather than a lighter
  partial-only response; fine at today's scale, worth revisiting if the page
  grows heavier.

## Suggested commits

Each commit is independently green; no file is split across commits.

1. `build(static): Tailwind CLI + HTMX vendoring, no CDN/Node`
   `Dockerfile`, `docker-compose.yml`, `tailwind.config.js`,
   `static_src/css/input.css`, `static/js/htmx.min.js`, `.gitignore`,
   `config/settings/base.py`

2. `feat(ui): restyle base layout and existing pages with Tailwind`
   `core/forms.py`, `accounts/forms.py`, `accounts/urls.py`,
   `forms_app/forms.py`, `templates/base.html`, `templates/rate_limited.html`,
   `templates/_form_fields.html`, `accounts/templates/accounts/*`,
   `forms_app/templates/forms_app/form_detail.html`,
   `forms_app/templates/forms_app/form_new.html`,
   `ingest/templates/ingest/thanks.html`, `ingest/templates/ingest/error.html`

3. `feat(dashboard): submissions dashboard (FR-6.1-6.4)`
   `dashboard/views.py`, `dashboard/urls.py`,
   `dashboard/templates/dashboard/home.html`,
   `dashboard/templates/dashboard/submissions_list.html`,
   `dashboard/templates/dashboard/submission_detail.html`,
   `dashboard/templates/dashboard/submission_delete_confirm.html`,
   `dashboard/tests/test_views.py`,
   `dashboard/tests/test_submissions_list.py`,
   `dashboard/tests/test_submission_detail.py`,
   `dashboard/tests/test_submissions_csv.py`,
   `notifications/email.py`, `notifications/tests/test_submission_email.py`,
   `docs/progress/day-11.md`

(Kept as one commit rather than split by FR: `dashboard/views.py` contains
both the home-page counts and the submissions list/detail/delete/CSV views
in one file, and CLAUDE.md requires every commit to pass tests on its own
with no file split across commits — splitting this FR-6.4 code from
FR-6.1-6.3 would mean shipping half of one file per commit.)
