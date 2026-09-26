# Day 3 — Auth flows

## Files changed

- **Settings**: `config/settings/base.py` (`LOGIN_URL`/`LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL`,
  `DEFAULT_FROM_EMAIL`, Redis-backed `CACHES`, project-level `templates/` in `TEMPLATES[0]["DIRS"]`),
  `config/settings/local.py` (console `EMAIL_BACKEND`), `config/urls.py` (wired in `accounts.urls`,
  `dashboard.urls`), `.env.example` (`DEFAULT_FROM_EMAIL`)
- **`notifications/`**: `email.py` (`send_transactional`), its text/HTML templates under
  `notifications/templates/notifications/email/`, `notifications/tests/test_email.py`
- **`accounts/`**: `tokens.py` (stateless signed verification token), `forms.py` (`SignupForm`,
  `EmailAuthenticationForm`, `TransactionalPasswordResetForm`), `emails.py`
  (`send_verification_email`), `views.py`, `urls.py`, all templates under
  `accounts/templates/accounts/`, tests: `test_tokens.py`, `test_views.py`, `test_password_reset.py`
- **`dashboard/`**: `views.py` (`home`, login-gated placeholder), `urls.py`, `templates/dashboard/home.html`,
  `tests/test_views.py`
- **`templates/base.html`** — shared nav/messages/unverified-banner shell

No model or migration changes — everything is stateless (signed tokens) or reads existing
fields (`User.is_verified`, `Account.plan`).

## FRs / NFRs covered

- FR-1.1 — signup at `/signup`: email + password, `Account`+`User` created atomically
  (reuses `UserManager.create_user`), email explicitly lowercased, user logged in, verification
  email sent synchronously.
- FR-1.2 — verification at `/verify/<token>`: stateless `django.core.signing` token, 3-day expiry,
  single-purpose salt. Invalid/expired token shows a friendly page with a resend option (for
  logged-in unverified users). Resend is rate-limited to 1/minute/user via the cache.
- FR-1.3 — login/logout at `/login`/`/logout` (email as username, logout POST-only), password
  reset at `/reset` using Django's built-in views wired to `send_transactional`.
- FR-1.4 (partial) — `/settings` shows email, verified status, plan. Usage figures deferred to
  Day 7.
- NFR-7 (basics) — every input has an associated `<label>`, errors render next to their field,
  logout is a `<form method="post">` rather than a link.

## How to verify manually

```
docker compose up
```
Then:
1. Visit `/signup`, create an account → redirected to `/dashboard`, unverified banner visible.
2. Check the `web` container logs for the console-emailed verification link; visiting it sets
   `is_verified` and the banner disappears.
3. `/logout` (GET) → 405; log out via the page's button (POST) → redirected to `/login`.
4. Log back in with a mixed-case email → succeeds.
5. `/settings` shows email / verified / plan (`free`).
6. `/reset` with a known and an unknown email both land on the same "check your email" page;
   only the known address gets a console email.

## Test results

- `docker compose run --rm web pytest` → **40 passed**.
- `docker compose run --rm web ruff check .` → all checks passed.
- `docker compose run --rm web ruff format --check .` → all files formatted.
- Full flow additionally exercised by hand with `curl` against the running stack (not just the
  test suite): signup → auto-login → dashboard; verification link from the console email;
  banner appearing/disappearing; mixed-case login; GET/POST logout behavior.

## Deviations from the SRS/plan

None. Implementation matches the approved plan; `AUTH_PASSWORD_VALIDATORS` was already set to
Django's defaults from Day 1, so no change was needed there.

## Follow-ups (explicitly out of scope for Day 3)

- Auth rate limiting beyond the resend-verification throttle — Day 7.
- Styling / Tailwind / HTMX — Day 11.
- Real email provider (Postmark/Resend/SendGrid) — Day 10; `send_transactional`'s signature is
  stable so Day 10 can wrap it in an RQ job without touching call sites.
- Password-confirmation field and a display-name field on `User` — neither is needed yet;
  trivial to add later with no migration impact.

## Suggested commits

1. `feat(notifications): add send_transactional email helper (SRS §8)`
2. `feat(accounts): add signup, verification, login/logout, password reset (FR-1.1–1.3)`
3. `feat(dashboard): add login-gated placeholder dashboard`
4. `chore: wire auth settings, urls, and templates dir`
