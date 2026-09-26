# Day 6 — Response modes, redirects, size limits, error format, logging

## Files changed

- **`ingest/responses.py`** (new) — `wants_json(request)`, `error_response(request, code, status, *, form=None)`. Builds every error response (JSON and HTML) and attaches CORS headers when a form is given and its origin is allowed.
- **`ingest/redirects.py`** (new) — `resolve_redirect_url(form, reserved)`: `_redirect` → `form.redirect_url` → hosted `/thanks`, per CLAUDE.md rule 8.
- **`ingest/origin_policy.py`** — renamed private `_normalize` → public `normalize_origin` (pure rename) so `redirects.py` can reuse the same normalization without inheriting `allowed_origin()`'s "empty list = allow all" CORS default.
- **`ingest/parsing.py`** — new `PayloadTooLarge` exception, `_cap_body()` (caps the read for missing/oversize `Content-Length`), `_check_field_limits()` (field count, key length, value/list-item length), `RequestDataTooBig`/`TooManyFieldsSent` mapped to `PayloadTooLarge`. `parse_body()` now returns the `reserved` dict for real use (previously discarded).
- **`ingest/views.py`** — rewritten `submit()`: check order is now method → size (`Content-Length`) → form lookup → origin → OPTIONS preflight → parse → success/redirect. All error paths (existing and new) go through `error_response`. New `thanks` view. Dropped `@require_http_methods` in favor of an explicit check so 405 gets our formatted response.
- **`ingest/urls.py`** — added `path("thanks", views.thanks, name="thanks")` → `/thanks`.
- **`ingest/templates/ingest/thanks.html`**, **`ingest/templates/ingest/error.html`** (new) — standalone pages (don't extend the authenticated `templates/base.html`), both `<meta name="robots" content="noindex">`.
- **`config/settings/base.py`** — `LOGGING` dict (stdout, `key=value` formatter, per-app loggers, level from `LOG_LEVEL`), `INGEST_MAX_BODY_BYTES`/`INGEST_MAX_FIELDS`/`INGEST_MAX_FIELD_CHARS`/`INGEST_MAX_KEY_CHARS`, and `DATA_UPLOAD_MAX_MEMORY_SIZE`/`DATA_UPLOAD_MAX_NUMBER_FIELDS` aligned to the ingest settings.
- **`.env.example`** — added `LOG_LEVEL` and the four `INGEST_MAX_*` vars.
- Tests: new `ingest/tests/test_responses.py`, `ingest/tests/test_redirects.py`; extended `ingest/tests/test_parsing.py` and `ingest/tests/test_views.py`; updated three Day-5 tests whose exact-dict-equality assertions broke once error bodies gained a `message` field.

No model or migration changes.

## FRs / NFRs covered

- **FR-3.5** — JSON callers unchanged (`200 {"ok": true, "id": ...}`); HTML-mode (classic form post) callers get `303` to the first valid of `_redirect` (only if its origin is in `form.allowed_origins`), `form.redirect_url`, or hosted `/thanks`.
- **FR-3.6** — every error (403/404/405/413/415/422) now has a consistent JSON shape (`{"ok": false, "error": "<code>", "message": "<text>"}`) and an HTML equivalent with the same status/message. CORS headers are attached to error responses when the (already-loaded) form's origin is allowed.
- **NFR-10** — structured `key=value` logs on stdout, level from `LOG_LEVEL`. Never logs payload or IP (unchanged guarantee from Day 5's `_log()`, now actually surfaced via the new `LOGGING` config instead of Django's un-configured default).
- **Input limits (SRS §11)** — `INGEST_MAX_BODY_BYTES`/`_FIELDS`/`_FIELD_CHARS`/`_KEY_CHARS`, all env-overridable, all → 413 before storing.

## How to verify manually

```
docker compose up
```
1. Create a form (no `redirect_url`, empty `allowed_origins`) and POST to `/f/{token}` with `Accept: text/html` and a form-encoded body → `303` to `/thanks`, page renders with `noindex`.
2. Set `redirect_url` on the form → same POST now redirects there instead.
3. Add an allowed origin and post `_redirect=https://<that-origin>/somewhere` → redirects to the `_redirect` value; posting a `_redirect` to a *different* origin falls back to `redirect_url`.
4. `curl -X POST http://localhost:8000/f/{token} --data-binary @bigfile.txt` with a body over 64KB → `413`.
5. `docker compose logs web` → `level=INFO logger=ingest message=...` lines, no payload/IP content.

## Test results

- `docker compose run --rm web pytest` → **177 passed**.
- `docker compose run --rm web ruff check .` → all checks passed.
- `docker compose run --rm web ruff format --check .` → all files formatted.
- Live smoke test against the running stack (not just the suite): browser-style POST → `303` → `/thanks` rendered; oversized POST → `413`; `docker compose logs web` showed the new log format with no payload/IP.

## Deviations from the plan

None functionally. Two implementation notes carried over from planning, not deviations:
- The "chunked/no-`Content-Length`, over limit" branch of `_cap_body` can't be exercised through `RequestFactory` or the Django test client — Django's `WSGIRequest` fixes `content_length = 0` at construction whenever the header is absent, which caps any `request.read()` at 0 bytes regardless of what `_cap_body` asks for. It's implemented and unit-tested against a minimal stub object instead; it's defense-in-depth for a deployment that behaves differently from real WSGI/gunicorn, not something reachable via live traffic today.
- `DATA_UPLOAD_MAX_MEMORY_SIZE`/`_NUMBER_FIELDS` only protect the form/multipart path (Django enforces them inside `.POST`/`.FILES` parsing, never on raw `.body`) — `_cap_body` is the sole size defense for the JSON path.

`docs/progress/day-05.md` still doesn't exist (Day 5 was implemented but never documented before this task) — flagged, not backfilled, per the user's call.

## Follow-ups (out of scope for Day 6)

- Rate limiting / 429, plan limits, `UsageEvent` metering — Day 7.
- Spam scoring, notifications — Days 8–10.

## Suggested commits

1. `feat(ingest): add response-mode detection and shared error responses (FR-3.6)`
   — `ingest/responses.py`, refactor `ingest/views.py`'s existing 404/403/415/422 paths onto it, update the three Day-5 tests whose exact-dict assertions broke.
2. `feat(ingest): add classic-form-post redirect resolution (FR-3.5)`
   — `ingest/redirects.py`, the `normalize_origin` rename in `ingest/origin_policy.py`, the `/thanks` view/URL/template, `ingest/templates/ingest/error.html`, wire redirect resolution + `wants_json` into `ingest/views.py`'s success path, `ingest/tests/test_redirects.py` and the new redirect/thanks tests in `test_views.py`.
3. `feat(ingest): enforce request size limits (SRS §11)`
   — `ingest/parsing.py` size/field/key/char checks, the pre-lookup `Content-Length` check and new check ordering in `ingest/views.py`, the `INGEST_MAX_*`/`DATA_UPLOAD_MAX_*` settings, `.env.example`, size-limit tests in `test_parsing.py` and `test_views.py`.
4. `chore(config): add stdout LOGGING config (NFR-10)`
   — `config/settings/base.py` `LOGGING`/`LOG_LEVEL`, `docs/progress/day-06.md`.
