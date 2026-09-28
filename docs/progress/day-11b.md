# Day 11b — Visual redesign

## Summary

Replaced the stock-Tailwind look from Day 11 with a defined visual identity:
a token-based color system (paper/ink/ink-raised/signal/signal-deep/line/
danger/danger-soft), a self-hosted variable font (Schibsted Grotesk, chosen
for its `tnum` OpenType feature), a real two-shell app layout (a navy sidebar
app shell for the authenticated dashboard/forms/settings pages that collapses
to a mobile drawer, and a centered wordmark+panel shell for auth/standalone
pages), an inbox-style submissions list, dashboard usage progress bars, and a
small set of action-driven motion touches (toasts, HTMX cross-fade, copy-button
feedback, mobile drawer). No view, URL, or model logic changed — every edit is
templates, CSS (`tailwind.config.js` / `static_src/css/input.css`), one new
vendored font, and one small vanilla-JS file.

Full design rationale (token contrast table, font verification, wireframes,
the six approved amendments) is in the plan this was built from:
`C:\Users\USER\.claude\plans\read-claude-md-and-docs-progress-day-11-linear-boot.md`.

## Files changed

**Tailwind purge fix**
- `core/forms.py` — `_DEFAULT_CLASS`/`_WIDGET_CLASSES` now hold the component
  class names `"field-input"`/`"field-checkbox"` instead of long utility
  strings. Same `setdefault("class", css)` logic, unchanged. Those two
  classes are defined in `input.css` under `@layer components`. **Correction
  (this session, see Fixes below): defining them under `@layer components`
  does *not*, on its own, protect them from Tailwind's purge — they were
  still being silently dropped from the built CSS. The actual fix is the
  `safelist` entry added to `tailwind.config.js` this session; this
  `core/forms.py` change is necessary (it's what the classes are named) but
  was not sufficient by itself.**

**Font**
- `static/fonts/schibsted-grotesk/` (new) — `SchibstedGrotesk-Variable-latin.woff2`
  (self-hosted, vendored from Google Fonts), `OFL.txt`, `NOTICE.txt`
  (provenance + why it won over Onest/Figtree).
  **Verification, not assumption:** downloaded all three try-order
  candidates (Schibsted Grotesk → Onest → Figtree) and inspected each with
  `fontTools` (`TTFont(path)['GSUB']`). All three turned out to carry `tnum`;
  Schibsted Grotesk won as first-in-order and had the fullest numeral
  feature set (`dnom`/`numr`/`frac`/`pnum`/`tnum` vs. Onest's `pnum`/`tnum`
  only). It's a variable font (`wght` 400–900) — self-hosted as one file with
  `font-weight: 400 600` in `@font-face` rather than three near-duplicate
  static instances, which is smaller and simpler than the plan's original
  "three static weights" framing while keeping the same license/feature
  guarantees (noted as a minor implementation refinement below).

**Tokens / CSS**
- `tailwind.config.js` — `theme.fontFamily.sans` replaced (not extended) so
  Schibsted Grotesk is first in the stack; `theme.extend.colors` adds the 8
  tokens; **`safelist: ["field-input", "field-checkbox"]` (added this
  session — see Fixes below, this is what actually fixes the purge bug; the
  original `@layer components` framing did not).**
- `static_src/css/input.css` — `@font-face`; reduced-motion kill switch in
  `@layer base`; `@layer components` (`.field-input`, `.field-checkbox`,
  `.btn`/`.btn-primary`/`.btn-secondary`/`.btn-danger`, `.panel`,
  `.kv-row`/`.kv-label`/`.kv-value`, `.pill`/`.pill-good`/`.pill-bad`/
  `.pill-neutral`, `.tab`/`.tab-active`/`.tab-inactive`, `.nav-link`); plain
  CSS for the HTMX `#submissions-panel` cross-fade, `.toast` states, and the
  mobile `#mobile-drawer`/`#mobile-drawer-backdrop` states. **`.field-input`/
  `.field-checkbox` now also apply `border` (this session — see Fixes
  below), not just `border-line`.**

**Template shells**
- `templates/_base_html.html` (new) — the one `<html><head>…<body>` shared by
  every page (font preload, `app.css` link, `{% block title %}`,
  `{% block robots %}`).
- `templates/base.html` — rewritten as the authenticated app shell (desktop
  sidebar / mobile topbar+drawer, skip link, toasts, resend-verification
  banner, `{% block content %}`). Used by `dashboard/*`, `forms_app/*`,
  `accounts/templates/accounts/settings.html`.
- `templates/base_centered.html` (new) — wordmark + centered white panel on
  paper. Used by signup/login/verify_result/password_reset_*,
  `ingest/thanks.html`, `ingest/error.html`, `rate_limited.html`.
- `templates/_messages.html`, `templates/_sidebar_nav.html` (new) — shared
  partials (toast list; sidebar/drawer nav, reused by both).
- `templates/_form_fields.html`, `templates/rate_limited.html` — token
  restyle (`rate_limited.html` also switched to `base_centered.html`).

**Pages restyled** (tokens/components/copy per the plan; no field/route
changes): all of `accounts/templates/accounts/*`,
`forms_app/templates/forms_app/{form_new,form_detail}.html`,
`dashboard/templates/dashboard/*`, `ingest/templates/ingest/{thanks,error}.html`.

Notable non-cosmetic bits within the restyle:
- `forms_app/form_detail.html` — new ink-background "endpoint URL" hero block
  with a signal-filled Copy button (didn't exist before, only the two
  snippet blocks had one); `id="embed-snippet"` added to the "Embed
  snippet" heading so the submissions-list empty state can deep-link to it;
  the old inline `easyformsCopy()` `<script>` is gone, replaced by
  `data-copy-target`/`data-copy-label` attributes handled generically in
  `static/js/app.js`.
- `dashboard/submissions_list.html` — restructured from `<table>` to
  `<ul><li><a>` so each row is one clickable/focusable element with a 3px
  status-color left edge; same `rows`/`page_obj`/`status`/`filters` context
  and the same `id="submissions-panel"`/`hx-*` attributes HTMX depends on.
  Three new empty-state messages (see plan) — the one place new copy was
  introduced, resolved entirely from the existing `status` context variable
  (no view change needed).
- `dashboard/home.html` — usage shown as `{% widthratio %}`-computed
  progress bars (signal, danger ≥90%); desktop `<table>` (`hidden md:table`)
  alongside a `md:hidden` stacked-card list for the same `forms` queryset, so
  nothing scrolls horizontally on a phone.

**JS**
- `static/js/app.js` (new) — toast show/dismiss/auto-timeout, mobile drawer
  open/close (Escape, backdrop click, focus management), generic copy-button
  "Copied ✓" feedback, and an instant filter-tab active-state toggle. The
  filter-tab listener is delegated on `document` rather than bound to the
  `<nav>` directly — HTMX's `outerHTML` swap replaces that node wholesale on
  every filter click, which would otherwise silently kill a directly-bound
  listener after the first click.

**Playwright tooling (this session)**
- `pyproject.toml` — the `browser-test` group (added, unverified, last
  session) is removed again. `uv.lock` never had a `playwright` entry for it
  (confirmed by grep), so no `uv lock` regeneration was needed — and since
  the group was never installed anywhere (`uv sync --frozen` has no
  `--group` flag at either Dockerfile call site), removing it makes
  `pyproject.toml` byte-identical to HEAD again. It no longer shows up in
  `git status` and needs no commit at all.
- `scripts/screenshots.py`, `scripts/interaction_checks.py` (new) — standalone
  scripts run from the official, version-pinned
  `mcr.microsoft.com/playwright/python:v1.47.0-jammy` image in a throwaway
  container (`pip install playwright==1.47.0` on top — the image ships the
  browser binaries at `/ms-playwright` but not the Python package itself, so
  a plain `docker run` needs that one quick install; no browser download
  happens since `PLAYWRIGHT_BROWSERS_PATH` already points at the baked-in
  ones). Nothing Playwright-related was added to `pyproject.toml`, `uv.lock`,
  or the Dockerfile. `screenshots.py` attaches to the compose network and
  hits `http://web:8000`; `interaction_checks.py` instead runs with
  `--network container:easyforms-web-1` (joins the `web` container's own
  network namespace) so it can load the app as plain `http://localhost:8000`
  — needed because the copy-button check uses `navigator.clipboard`, which
  browsers only expose on a secure context, and `localhost` (unlike the
  compose DNS name `web`) is unconditionally treated as one. `ALLOWED_HOSTS`
  already being `["*"]` in `config/settings/local.py` meant no settings
  change was needed for either hostname.
- Demo data for the screenshot/interaction pass is seeded and purged by
  `var/seed_demo.py` / `var/purge_demo.py` — throwaway, gitignored (`var/`),
  not committed, per the task's "via a script you run, not committed data."

**Tests**
- `core/tests/test_static_css.py` (new) — reads the built `static/css/app.css`
  off disk and asserts it contains `.field-input`/`.field-checkbox` and a
  sample of token-derived utility classes actually used in templates.
- `dashboard/tests/test_submissions_list.py` — the one test asserting a
  literal HTML string (`Failed` notification pill) updated to match the new
  `pill pill-bad` markup; no assertion logic changed.

## FRs / NFRs covered

None new — this is purely the visual layer over Day 11's FR-6.1–6.4 (dashboard,
submissions list/detail/CSV) and NFR-7 (focus states, labels, heading order).

## How to verify manually

```
docker compose build web
docker compose up -d db redis mailpit
docker compose up -d --build web worker tailwind
docker compose run --rm web python manage.py migrate
docker compose run --rm web sh -c "ruff check . && ruff format --check . && pytest -q"
```
Then visually: `/dashboard`, `/forms/<id>`, `/forms/<id>/submissions`,
`/forms/<id>/submissions/<sid>`, and the auth pages, at both desktop and
390px-mobile widths; keyboard-tab through each to confirm focus order and a
visible outline; toggle `prefers-reduced-motion` and confirm transitions
collapse to instant.

## Test results — run this session, all green

Disk/Docker were confirmed fixed at the start of this session
(`docker network ls` already showed the compose network up).

```
docker compose build                                    # clean, no errors
docker compose up -d db redis mailpit
docker compose up -d --build web worker tailwind
docker compose run --rm web python manage.py migrate     # no pending migrations
docker compose run --rm web sh -c "ruff check . && ruff format --check ."   # All checks passed! / 147 files already formatted
docker compose run --rm web python manage.py makemigrations --check --dry-run   # No changes detected
docker compose run --rm web pytest -q                    # 359 passed
```

Production-image purge check (step 4 of the brief — deliberately separate
from `core/tests/test_static_css.py`, which only ever sees the dev
bind-mounted CSS the `tailwind` service writes to the host, not what the
Dockerfile's `tailwind-build` stage actually bakes into the image):
`docker create`+`docker cp`'d `/app/static/css/app.css` out of the built
`easyforms-web` image and grepped it — `.field-input`, `.field-checkbox`,
and all seven sampled token classes (`bg-ink`, `bg-paper`, `bg-signal`,
`text-signal-deep`, `border-line`, `bg-danger-soft`, `text-danger`) present.

Playwright: `scripts/screenshots.py` produced all 23 screenshots (11 pages ×
1280px/390px + the mobile drawer shot); every one reviewed by hand (see
Fixes below for what that turned up). `scripts/interaction_checks.py`: all 5
checks pass (dashboard focus order/visibility, form-detail focus
order/visibility, HTMX status-filter swap, copy-button feedback,
`prefers-reduced-motion` collapsing transitions to ~0). Demo data seeded via
`var/seed_demo.py`, purged via `var/purge_demo.py` after — confirmed gone
(`Account.objects.filter(name="Demo Co").count() == 0`).

## Fixes made this session

- **Real bug — `.field-input`/`.field-checkbox` had no visible border.**
  `static_src/css/input.css` applied `border-line` (a border *color*
  utility) but never a border-*width* utility; Tailwind's Preflight resets
  `border-width: 0` on every element, so every text input, textarea, and
  select in the app rendered with no visible edge at all — on the login/
  signup panels (white input on the white centered-panel background) this
  made the fields completely invisible; on `paper`-background pages
  (settings form on `forms_app/form_detail.html`) it was only barely visible
  via the input's own `bg-white` contrasting against the page. Caught by
  screenshotting `/login` and `/signup` and looking at them. Fixed by adding
  `border` to both classes in `input.css`. Verified: re-shot screenshots
  show a clear 1px border on every field at both widths; full suite still
  green.

- **Real bug — the Day 11b "purge fix" itself didn't work.**
  `core/tests/test_static_css.py::test_built_css_contains_widget_component_classes`
  failed on first run: `.field-input`/`.field-checkbox` were **absent** from
  the built `app.css`, even though they're defined under `@layer components`
  in `input.css`. The original rationale (`docs/progress/day-11b.md`'s
  "Tailwind purge fix" note, and `core/forms.py`'s docstring) assumed
  `@layer components` classes ship unconditionally regardless of content
  scanning — that's wrong for Tailwind v3's JIT engine, which purges *any*
  class name (utility or hand-written `@layer` class) that never appears as
  a literal string in a file matched by `content` in `tailwind.config.js`.
  Since `content` only globs `.html` templates and `field-input`/
  `field-checkbox` are only ever written by `core/forms.py` (Python, never
  scanned), they were being silently dropped from the build — the exact
  purge bug the Day 11b work set out to fix, still present. Fixed with an
  explicit `safelist: ["field-input", "field-checkbox"]` in
  `tailwind.config.js`, which is Tailwind's documented mechanism for exactly
  this case (a class that can't be found by content scanning). Verified via
  both the pytest assertion and the separate production-image grep above.

- **Stale test markup — `dashboard/tests/test_views.py`.**
  `test_dashboard_shows_usage_and_create_link_below_limit` and
  `test_dashboard_hides_create_link_at_limit` asserted the literal string
  `"1 / 3 forms used"` / `"3 / 3 forms used"`, from Day 11's original
  single-line usage text. Day 11b's progress-bar markup
  (`dashboard/home.html`) splits this into separate `<span>Forms</span>` and
  `<span class="tabular-nums">1 / 3</span>` elements with no "forms used"
  text anywhere — an assertion-vs-markup mismatch, not a real bug. Updated
  both assertions to the new literal `<span class="tabular-nums">…</span>`
  markup (same style `test_submissions_list.py` already uses for its pill
  assertion); no view or template logic changed.

- **Screenshot-script bug (my own tooling, not the app) —
  `scripts/screenshots.py` never navigated to `/login` before screenshotting
  it**, so the first "login" pass produced two blank white PNGs. Fixed by
  adding the missing `page.goto()`; re-shot and confirmed correct.

## Deviations from the plan

- **Font: one self-hosted variable file, not three static weights.** The
  plan's typography section said "self-hosted as woff2 (weights
  400/500/600)"; all three try-order candidates turned out to be variable
  fonts, so the actually-correct and smaller implementation is one file with
  a `font-weight: 400 600` range in `@font-face`, letting the browser
  interpolate 500 rather than shipping three near-duplicate static
  instances. Same license, same verified `tnum` feature, strictly less code
  — flagging as a deviation because the plan's wording implied three files.

- **`pyproject.toml` ends up with no diff at all.** The `browser-test` group
  added last session is removed this session (see Playwright tooling,
  above); since it was never installed anywhere and `uv.lock` never
  reflected it, removing it makes `pyproject.toml` identical to HEAD again —
  it doesn't appear in `git status` and there's nothing to commit for it.

## Follow-ups (not done today)

- Everything already deferred by the Day 11 doc (WhiteNoise/`collectstatic`,
  label correction, HTMX partial-only responses) is still deferred — nothing
  here changes those.
- `scripts/screenshots.py`/`scripts/interaction_checks.py` are one-off
  verification tools, not wired into CI — worth considering for a future day
  if visual regressions become a recurring problem.

## Suggested commits

Ordered so each is independently green; no file split across commits.
`pyproject.toml` is intentionally absent — see Deviations above, it has no
diff this session.

1. `fix(ui): fix Tailwind purge dropping Python-set and hand-authored classes`
   `core/forms.py`, `tailwind.config.js`, `static_src/css/input.css`
   (Combined into one commit, not split as originally suggested: the
   `.field-input`/`.field-checkbox` classes `core/forms.py` sets are defined
   in `input.css`, and the actual purge fix is the `safelist` entry in
   `tailwind.config.js` — `core/forms.py` alone fixes nothing without both.
   This commit also carries this session's border-width fix, since it's the
   same two classes and splitting it out would leave an intermediate commit
   with known-invisible form fields.)

2. `feat(ui): design tokens and self-hosted font`
   `static/fonts/`
   (Font files only — the token/component CSS moved into commit 1 above
   since it now shares a file with the purge fix.)

3. `feat(ui): app shell + centered auth shell, replacing the single base.html`
   `templates/_base_html.html`, `templates/base.html`,
   `templates/base_centered.html`, `templates/_messages.html`,
   `templates/_sidebar_nav.html`, `templates/_form_fields.html`,
   `templates/rate_limited.html`, `static/js/app.js`

4. `feat(ui): restyle accounts pages onto the new shells`
   `accounts/templates/accounts/*`

5. `feat(ui): restyle forms_app pages, add endpoint copy button`
   `forms_app/templates/forms_app/{form_new,form_detail}.html`

6. `feat(ui): restyle dashboard — progress bars, inbox list, empty states`
   `dashboard/templates/dashboard/*`, `dashboard/tests/test_submissions_list.py`,
   `dashboard/tests/test_views.py`

7. `feat(ui): restyle ingest thanks/error pages onto the centered shell`
   `ingest/templates/ingest/{thanks,error}.html`

8. `test(ui): assert built CSS keeps the purge-fix and token classes`
   `core/tests/test_static_css.py`

9. `chore: add Playwright screenshot/interaction-check scripts`
   `scripts/screenshots.py`, `scripts/interaction_checks.py`
   (Standalone dev tooling, run from the official Playwright image — not
   tied to any template/CSS change, so it doesn't belong in commits 1–8.)

10. `docs: Day 11b progress notes`
    `docs/progress/day-11b.md`

(Commits 2–7 are UI-only and safe to squash together if preferred; kept
separate here for reviewability, matching the one-area-per-commit pattern
Day 11's own suggestions used.)
