# Day 9 — Inline spam scoring, heuristics, ingest wiring

## Files changed

- **`spam/scoring.py`** (new) — `Verdict` dataclass (`status`, `spam_score`, `model_version`,
  `signals`, `duration_ms`). `Scorer`: a process-level, lazy-loading, thread-safe (one `Lock`)
  scorer. `score(fields, reserved, now)`: honeypot check first (hard short-circuit, skips model
  work entirely); then a `_refresh()` with double-checked-locking around a
  `SPAM_MODEL_REFRESH_SECONDS`-bounded interval gate (cheap outer check with no lock, re-checked
  inside the lock before doing real work); then the `_ts` fast-submit heuristic (tolerates clock
  skew up to 60s, flags a genuinely fast past submission or a >60s future timestamp); then, if a
  pipeline is loaded, `p = pipeline.predict_proba([extract_text(fields)])[0][1]` against the
  model's threshold (lowered by `SPAM_FAST_SUBMIT_MARGIN`, floored at 0.05, on a fast submission).
  `_do_refresh_locked()` never raises: no active `ModelVersion` or a failed *first* load →
  heuristics-only; a failed *reload* while a good pipeline is already serving → keeps serving the
  last-known-good pipeline and logs a warning instead of blanking the whole fleet over one bad
  rollout (this was an explicit design decision confirmed with the user — see Deviations). Every
  failure path logs once per continuous failure streak, not once per request. A module singleton
  (`_default_scorer`) plus thin `warm()`/`score()` wrappers for the gunicorn hook and
  `ingest/views.py`.
- **`forms_app/models.py`** — `Submission.spam_signals` (`JSONField(default=list, blank=True)`).
- **`forms_app/migrations/0002_submission_spam_signals.py`** (new) — one additive `AddField`.
- **`ingest/views.py`** — `_log()` gains an optional `verdict` param (appends
  `verdict=<status> signals=<...> score_ms=<...>`, never payload); new `_build_success_response()`
  helper (extracted from the old ham-only bottom-of-`submit()` code) used identically by ham,
  flagged-spam, and dropped-spam so the response is byte-identical in shape across all three. The
  `# Day 9 will insert spam scoring here` slot now calls `spam_scoring.score(fields, reserved,
  timezone.now())` and branches: ham → unchanged quota-check + `Submission`+`UsageEvent` in one
  `transaction.atomic()`; spam → **never** quota-checked, **never** metered (CLAUDE.md rule 7) —
  `spam_action="flag"` stores a `Submission` with `status=spam`; `spam_action="drop"` stores
  nothing and returns a fresh `uuid.uuid4()` as the response id.
- **`gunicorn.conf.py`** (new, repo root) — `post_worker_init(worker)` calls `spam.scoring.warm()`
  with the import deliberately local to the function (a module-level import would crash the
  master process before `django.setup()` ever runs — see inline docstring) and a broad
  `except Exception` as a second line of defense so a worker-boot hook can never prevent the
  worker itself from coming up.
- **`Dockerfile`** — `CMD` now passes `-c gunicorn.conf.py`.
- **`config/settings/base.py`** / **`.env.example`** — `SPAM_MODEL_REFRESH_SECONDS` (60),
  `SPAM_MIN_SUBMIT_SECONDS` (3), `SPAM_FAST_SUBMIT_MARGIN` (0.25).
- **`spam/fixtures/form_sanity.json`** (new) — 24 hand-written realistic contact-form messages
  (12 ham, 12 spam), each `{"label", "fields"}` shaped like a real submission payload.
- **`spam/management/commands/eval_spam_model.py`** (new) — `--model-version` optional (named
  `--model-version`, not `--version`, since Django's `BaseCommand` already reserves `--version`
  globally on every command — found by the test suite, not anticipated in planning). Scores the
  fixture through the active (or given) model via `extract_text` + `predict_proba` directly,
  **bypassing** `spam.scoring.score()` entirely (no honeypot/`_ts` metadata in the fixture — this
  is a model-quality check, not an ingest-path check). Always exits 0; prints per-entry results
  plus false-positive/false-negative index lists.
- **`ingest/tests/conftest.py`** (new) — autouse fixture resetting
  `spam.scoring._default_scorer`'s private state before/after every test. Necessary because the
  singleton is a real process-lifetime object that pytest-django's per-test DB rollback does not
  touch; without this, a test that loads a real pipeline into it would leak that state into every
  later test in the same worker process.
- **`spam/tests/test_scoring.py`** (new, 20 tests) — `_parse_ts` variants; honeypot short-circuit
  (and that it never calls `predict_proba`); non-string/empty honeypot ignored; fast-`_ts`
  flipping a borderline score; missing/garbage `_ts` inert; small future skew tolerated vs. large
  future skew flagged; `fast_submit` recorded-but-inert in heuristics-only mode; heuristics-only
  logged once across many calls (no active model, and load-raises cases); a failed *reload* keeps
  serving the last-known-good pipeline and logs a warning once; version-rollover after the refresh
  interval elapses (DB-backed, using two real tiny trained `ModelVersion`s).
- **`spam/tests/test_eval_command.py`** (new, 5 tests).
- **`ingest/tests/test_views.py`** (extended, +9 tests) — honeypot flag/drop storage and response
  shape (JSON and HTML/303 modes), spam bypassing quota even at the account's limit (paired with
  a regression test confirming ham is still blocked at the limit), and a no-payload-in-logs test
  for the spam path.

## FRs / SRS sections covered

FR-4.1 (score every submission inline), FR-4.2 (honeypot + timing heuristics as hard/soft
signals), FR-4.3 (label by threshold, apply the form's `spam_action`), SRS §4 (submission request
lifecycle), §7 (serving/versioning, threshold policy). FR-4.4 (dashboard correction) and
notifications (FR-5.x) are explicitly Day 10/12, untouched.

## How to verify manually

```
docker compose build web worker
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py makemigrations --check --dry-run   # "No changes detected"
docker compose run --rm web pytest -q
docker compose run --rm web sh -c "ruff check . && ruff format --check ."
docker compose run --rm web python manage.py eval_spam_model
docker compose up -d web
curl -X POST http://localhost:8000/f/<token> -d "name=Bot" -d "_honeypot=filled"
curl -X POST http://localhost:8000/f/<token> -d "name=Jane" -d "message=hi"
```

## Test results

- `pytest -q`: **272 passed** (34 new: 20 in `test_scoring.py`, 5 in `test_eval_command.py`, 9
  added to `ingest/tests/test_views.py`).
- `ruff check .` / `ruff format --check .`: clean.
- `makemigrations --check --dry-run`: no changes detected.

## Live verification

**`eval_spam_model`** against the real active model (`20260926T134543Z`, threshold 0.622, trained
Day 8 on the UCI SMS Spam Collection):
```
[0] label=ham predicted=spam p=0.844 MISMATCH
[1] label=ham predicted=spam p=0.971 MISMATCH
[2] label=ham predicted=ham p=0.047 OK
[3] label=ham predicted=ham p=0.342 OK
[4] label=ham predicted=spam p=0.881 MISMATCH
[5] label=ham predicted=spam p=0.727 MISMATCH
[6] label=ham predicted=ham p=0.375 OK
[7] label=ham predicted=ham p=0.203 OK
[8] label=ham predicted=spam p=0.829 MISMATCH
[9] label=ham predicted=spam p=0.961 MISMATCH
[10] label=ham predicted=ham p=0.210 OK
[11] label=ham predicted=spam p=0.854 MISMATCH
[12]-[23] all 12 spam entries: predicted=spam, p in [0.777, 1.000] — all OK
model version=20260926T134543Z threshold=0.6224054631685678
false positives (ham predicted spam): [0, 1, 4, 5, 8, 9, 11]
false negatives (spam predicted ham): []
```
**7 of 12 realistic ham messages are false positives** (all 12 real spam messages are correctly
caught). See Deviations below — this is a real, expected finding, not a bug.

**Honeypot + normal submission**, POSTed to a running `web` (Django `runserver`):
```
POST _honeypot=filled-by-bot  -> {"ok": true, "id": "d06895a1-..."}
POST (no honeypot, real text) -> {"ok": true, "id": "a9baecea-..."}
```
Stored rows:
```
id=d06895a1...  status=spam  spam_score=None        spam_signals=['honeypot']  model_version=None
id=a9baecea...  status=ham   spam_score=0.0374...    spam_signals=[]            model_version=71b7a0a8-...
```
Confirms: honeypot is heuristics-only (no model touched), a normal submission is scored by the
real active model end-to-end, and the response shape is identical between the two (`{"ok",
"id"}`, both 200).

**Timing** — 100 sequential form-encoded POSTs against `runserver` (single dev process, not
gunicorn — a conservative proxy, since prod runs multiple gunicorn workers):
```
n=100  min=6.4ms  max=94.3ms  p50=8.9ms  p95=55.8ms
```
Comfortably under NFR-1's p95 < 300ms target.

**Artifact size / worker RSS** — the active model artifact is **3.1 MB** on disk
(`spam/models/20260926T134543Z.joblib`). Started a real gunicorn instance
(`gunicorn config.wsgi:application -c gunicorn.conf.py`) to verify `post_worker_init`: the worker
booted cleanly, `/healthz` returned 200, and **no** "spam scorer warm() failed" line appeared in
the logs (confirms `warm()` succeeded silently). Worker RSS after boot: **~186 MB** (peak 189 MB)
— dominated by the numpy/scipy/scikit-learn/Django baseline memory footprint, not the 3.1 MB
artifact itself. (A follow-up submission through this gunicorn instance to double-confirm
model-backed scoring hit the per-IP rate limit — shared bucket with the 100-request timing run
moments earlier — so that specific confirmation reused the `runserver` result above instead,
which already exercises the identical `Scorer` code path.)

## Deviations from the spec / open items

- **`eval_spam_model`'s flag is `--model-version`, not `--version`.** Django's `BaseCommand`
  reserves `--version` on every management command (prints the Django version) — the test suite
  caught this collision (`argparse.ArgumentError: conflicting option string`) before it ever
  reached the live run. Fixed by renaming; no other behavior change.
- **Real-data false-positive rate (see Live verification above) is a genuine finding worth
  flagging, not a defect.** The Day 8 model was trained entirely on SMS spam text — a very
  different register from realistic web contact-form messages (which legitimately contain names,
  phone numbers, "call me", capitalized words, etc. — exactly the surface features an SMS-spam
  classifier learned to associate with spam). All real spam in the fixture was still caught
  (0 false negatives), and since the default `spam_action` is `flag` (not `drop` — SRS §7's
  explicit threshold policy: "tuned for high precision... so legitimate submissions are rarely
  hidden," reversible from the dashboard), a false positive today is *visible and correctable*,
  not silently lost. This is exactly the cold-start risk SRS §14 calls out ("Spam model cold
  start... default to flag not drop, ship the correction loop early, retrain once real labels
  exist") and is expected to improve once Day 12's correction flow feeds real labelled data back
  into retraining — not a Day 9 scope item, just worth surfacing prominently before any real form
  is switched to `spam_action="drop"`.
- **Design decisions confirmed with the user during planning** (both already reflected above,
  restated here for the record): the `_ts` "future" clause tolerates up to 60s of clock skew
  rather than flagging any future timestamp at all; a failed *reload* of a newly-activated model
  keeps serving the last-known-good pipeline rather than dropping the whole fleet to
  heuristics-only.
- Everything else matches the task spec as given.

## Follow-ups (not built now)

- Day 10: worker + notification emails on new ham submissions.
- Day 12: dashboard label correction (`corrected` flag) — the flywheel for the false-positive
  finding above.
- Retraining on real submissions / owner corrections, per SRS §7's feedback loop — out of scope
  until real labelled data exists.

## Suggested commits

1. `feat(spam): add process-level lazy-loaded scorer with honeypot/_ts heuristics (FR-4.1, FR-4.2)`
   — `spam/scoring.py`, `config/settings/base.py`, `.env.example`, `spam/tests/test_scoring.py`

2. `feat(forms_app): add spam_signals to Submission`
   — `forms_app/models.py`, `forms_app/migrations/0002_submission_spam_signals.py`

3. `feat(ingest): wire spam scoring into the submit view, honor spam_action (FR-4.3)`
   — `ingest/views.py`, `ingest/tests/conftest.py`, `ingest/tests/test_views.py`

4. `feat(spam): warm the scorer on gunicorn worker boot`
   — `gunicorn.conf.py`, `Dockerfile`

5. `feat(spam): add eval_spam_model sanity-check command and fixture`
   — `spam/fixtures/form_sanity.json`, `spam/management/commands/eval_spam_model.py`,
   `spam/tests/test_eval_command.py`

6. `docs(progress): add Day 9 summary`
   — `docs/progress/day-09.md`

Each commit's own tests pass standalone in the order given (1 needs nothing new besides Day 8's
`spam` app; 2 is a plain additive migration; 3 depends on 1 and 2; 4 depends on 1; 5 depends on
Day 8's `spam.loading`/`spam.features` only, independent of 1–4).
