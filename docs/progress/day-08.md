# Day 8 — Bootstrap spam model

## Files changed

- **`spam/features.py`** (new) — `extract_text(payload)`, the single source of truth for
  train/serve text input: joins string values and string-list items from a payload dict in
  sorted-key order, skipping reserved keys (reuses `ingest.parsing.RESERVED_PREFIX`) and any
  non-string/non-list value. `TextStatsExtractor` — one sklearn `BaseEstimator`/`TransformerMixin`
  producing five engineered numeric columns (`link_count, has_url, uppercase_ratio, log_length,
  digit_ratio`) from a list of text strings; each formula is a separate private function so it's
  independently testable.
- **`spam/storage.py`** (new) — `ArtifactStore` ABC (`put`/`get`/`exists`), `LocalArtifactStore`
  (filesystem, with a same-path guard to avoid `shutil.SameFileError`), `S3ArtifactStore` (R2 via
  boto3, using low-level `put_object`/`get_object`/`head_object` rather than
  `upload_file`/`download_file` so `botocore.stub.Stubber` can intercept calls in tests),
  `get_artifact_store()` factory reading `settings.ARTIFACT_STORAGE` (raises
  `ImproperlyConfigured` on an unknown value).
- **`spam/models.py`** — added `threshold` (nullable float), `sha256` (char64, blank), and
  `sklearn_version` (char32, blank) to `ModelVersion`; added `ModelVersionManager.activate(mv)`,
  which deactivates every other active row then activates the target inside one
  `transaction.atomic()` block (in that order, so the partial unique constraint never sees two
  active rows at once).
- **`spam/migrations/0002_modelversion_threshold_sha256_sklearn_version.py`** (new) — adds the
  three fields above; all nullable/blank-with-default, so the existing (untouched)
  `spam/tests/test_models.py` keeps passing.
- **`spam/training.py`** (new) — `download_dataset` (downloads and SHA-256-verifies the UCI SMS
  Spam Collection zip, cached in `--data-dir`, reused if already extracted), `load_dataset`
  (parses the tab-separated corpus), `build_pipeline` (`FeatureUnion` of word TF-IDF 1–2 grams,
  char_wb TF-IDF 3–5 grams, and scaled `TextStatsExtractor` output → `LogisticRegression`,
  `class_weight="balanced"`), `select_threshold` (lowest threshold with test-set spam precision ≥
  the configurable floor, default 0.98; falls back to 0.9 with a logged warning if unreachable),
  `train_and_save` (stratified 80/20 split, fixed `random_state=42`, trains, saves metrics/
  threshold/sha256/sklearn_version, `joblib`-dumps and uploads the artifact, creates the
  `ModelVersion` row, optionally activates it, or does none of that in `--dry-run`).
- **`spam/loading.py`** (new) — `load_model_version(mv)`: downloads to a local cache
  (`MODEL_ARTIFACT_DIR`) if not already present, verifies SHA-256 **before** any `joblib.load`
  call, verifies scikit-learn major.minor version match, raises `SpamModelLoadError` with a clear
  message on either mismatch. Not called from anywhere yet — Day 9 wires it into app startup.
- **`spam/management/commands/train_spam_model.py`** (new) — `--activate`, `--dry-run`,
  `--min-precision` (default 0.98), `--data-dir` (default `settings.SPAM_DATASET_DIR`). Prints
  metrics JSON and a success/warning line.
- **`spam/management/commands/activate_spam_model.py`** (new) — `activate_spam_model <version>`,
  raises `CommandError` for an unknown version tag, otherwise calls
  `ModelVersion.objects.activate`.
- **`config/settings/base.py`** — new `ARTIFACT_STORAGE`, `MODEL_ARTIFACT_DIR` (default
  `/var/lib/easyforms/artifacts`), `SPAM_DATASET_DIR` (default `/var/lib/easyforms/data`),
  `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` settings.
- **`.env.example`** — matching block with dummy values.
- **`pyproject.toml`** / **`uv.lock`** — added `scikit-learn>=1.9,<1.10` (resolved 1.9.1) and
  `boto3>=1.43,<1.44` (resolved 1.43.103); `joblib`/`botocore` come in transitively.
- **`Dockerfile`** — creates `/var/lib/easyforms/{artifacts,data}` and `chown`s them to `appuser`
  *before* the `USER appuser` line, so that when docker-compose mounts fresh named volumes at
  those exact paths, they inherit ownership from the image layer instead of being auto-created
  `root:root` by the Docker daemon (see "Deviations" below — this replaces an earlier manual
  workaround).
- **`docker-compose.yml`** — named volume `artifacts` mounted at
  `/var/lib/easyforms/artifacts` for both `web` and `worker`; named volume `training_data`
  mounted at `/var/lib/easyforms/data` for `web` only (only the training command reads/writes
  it). Neither path sits under the `.:/app` bind mount, which is what lets the Dockerfile's
  pre-created ownership apply.
- **`.gitignore`** — added `var/` (harmless leftover guard; the app itself no longer uses any
  `var/` path under the repo, everything moved to `/var/lib/easyforms` outside it).
- **`spam/tests/`** — `test_features.py`, `test_storage.py`, `test_training.py`, `test_loading.py`,
  `test_commands.py`, `test_activation.py` (new file — the existing `test_models.py` was left
  unmodified), plus fixtures `fixtures/sms_fixture.tsv` (39 hand-written rows, 25 ham / 14 spam,
  same `label\ttext` shape as the real corpus) and `fixtures/sms_fixture.zip` (the same content
  zipped as `SMSSpamCollection`, used for the checksum tests via `file://` URLs).

## FRs / SRS sections covered

SRS §7 (the ML component) and §13 Day 8 row: bootstrap a spam model trained offline on a public
corpus, save as a versioned artifact to object storage, no inline scoring yet.

## How to verify manually

From a completely clean slate (no containers, no volumes — this is exactly how a fresh clone
would start):

```
docker compose down -v
docker compose build web worker
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py makemigrations --check --dry-run   # "No changes detected"
docker compose run --rm web pytest -q
docker compose run --rm web sh -c "ruff check . && ruff format --check ."
docker compose run --rm web python manage.py train_spam_model --activate       # no manual chown needed
docker compose run --rm web python manage.py shell -c \
  "from spam.models import ModelVersion; print(list(ModelVersion.objects.values('version','is_active')))"
```

## Test results

- `pytest -q`: **251 passed** (38 of them new, in `spam/`).
- `ruff check .` / `ruff format --check .`: clean.
- `makemigrations --check --dry-run`: no changes detected (the hand-written migration matches the
  model exactly).

## Live run against the real corpus (from a clean `docker compose down -v`)

`docker compose run --rm web python manage.py train_spam_model --activate`, run immediately after
`docker compose down -v` + rebuild + `migrate` — fresh `pgdata`, `artifacts`, and `training_data`
volumes, no manual permission fix of any kind:

```json
{
  "precision": 0.9859154929577465,
  "recall": 0.9395973154362416,
  "f1": 0.9621993127147767,
  "roc_auc": 0.9928230994761488,
  "confusion_matrix": [[964, 2], [9, 140]],
  "threshold": 0.6224054631685678,
  "threshold_used_fallback": false,
  "dataset": "uci_sms_spam_collection",
  "n_rows": 5574,
  "n_train": 4459,
  "n_test": 1115,
  "class_balance": {"ham": 4827, "spam": 747}
}
Saved ModelVersion 20260926T134543Z (active=True)
```

Precision (0.986) cleared the 0.98 floor without falling back to the 0.9 default. Exactly one
`ModelVersion` row is active afterward, confirmed via `manage.py shell`. Before running the
command, `ls -la /var/lib/easyforms /var/lib/easyforms/artifacts /var/lib/easyforms/data` inside
the container was checked and showed both fresh volumes already owned by `appuser:appuser` (not
`root:root`) — the Dockerfile fix working as intended. After the run, the artifact was confirmed
present at `/var/lib/easyforms/artifacts/spam/models/20260926T134543Z.joblib` and the extracted
corpus at `/var/lib/easyforms/data/SMSSpamCollection`, both inside the named volumes, not the
bind-mounted working tree.

## Deviations from the spec / open items

- **Dataset URL differs from the one first identified during planning.** The UCI page's listed
  "direct download" host (`ucimlrepo.z13.web.core.windows.net`, an Azure Static Web Apps domain)
  does not resolve from this environment (or, it turned out, from this Docker Desktop network) —
  DNS failure, not a checksum/content problem. Switched to the long-standing stable path,
  `https://archive.ics.uci.edu/ml/machine-learning-databases/00228/smsspamcollection.zip`, which
  resolves fine and serves the identical well-known 5574-row corpus (verified: 4827 ham / 747
  spam, matching the dataset's documented shape). `DATASET_SHA256` is pinned to this file's real
  hash, computed and confirmed working end-to-end during the live run above, not left as a
  placeholder.
- **Model/dataset directories moved outside `/app` entirely.** They now live at
  `/var/lib/easyforms/artifacts` and `/var/lib/easyforms/data` (both env-overridable via
  `MODEL_ARTIFACT_DIR` / `SPAM_DATASET_DIR`), instead of under `/app/var/...`. The original
  `/app/var/...` placement (inside the docker-compose bind mount `.:/app`) meant the Docker daemon
  had to auto-create the mount point for the `artifacts` named volume as `root:root` on first use
  (standard Docker behavior when a volume's target doesn't already exist under a bind-mounted
  path), which blocked the non-root `appuser` from writing there or beside it. Moving both
  directories outside the bind mount lets the Dockerfile create and `chown` them to `appuser`
  *at image-build time*; Docker then copies that ownership into each fresh named volume the first
  time it's mounted, since the volume's target path has real, correctly-owned content in the image
  layer to inherit from. Verified from a full `docker compose down -v` + rebuild with no manual
  fix required (see the live run above) — the workaround from the first Day 8 pass (a manual
  `chown` via `docker compose run --user root`) is no longer needed and has been removed.
- Everything else matches the task spec as given.

## Follow-ups (not built now)

- Day 9: wire `spam.loading.load_model_version` into app startup (loading the currently-active
  `ModelVersion`, falling back to heuristics-only scoring per CLAUDE.md rule 10 if unavailable),
  inline scoring in the ingest path, honeypot/timing heuristics, and labelling.

## Suggested commits

1. `chore(deps): add scikit-learn and boto3 for the spam model pipeline`
   — `pyproject.toml`, `uv.lock`

2. `feat(spam): add artifact storage backends for R2 and local dev (FR from SRS §7)`
   — `spam/storage.py`, `config/settings/base.py`, `.env.example`, `Dockerfile`,
   `docker-compose.yml`, `.gitignore`, `spam/tests/test_storage.py`

3. `feat(spam): add shared text/feature extraction for train and serve (SRS §7)`
   — `spam/features.py`, `spam/tests/test_features.py`

4. `feat(spam): add threshold/sha256/sklearn_version to ModelVersion and an activate manager method`
   — `spam/models.py`, `spam/migrations/0002_modelversion_threshold_sha256_sklearn_version.py`,
   `spam/tests/test_activation.py`

5. `feat(spam): add offline training pipeline and management commands (SRS §7, §13 day 8)`
   — `spam/training.py`, `spam/loading.py`, `spam/management/__init__.py`,
   `spam/management/commands/__init__.py`, `spam/management/commands/train_spam_model.py`,
   `spam/management/commands/activate_spam_model.py`, `spam/tests/test_training.py`,
   `spam/tests/test_loading.py`, `spam/tests/test_commands.py`, `spam/tests/fixtures/`

6. `docs(progress): add Day 8 summary`
   — `docs/progress/day-08.md`

Each commit's own tests pass standalone in the order given (2 depends only on stdlib+boto3+Django
settings already in place; 3 is fully independent; 4 depends on nothing new besides Django; 5
depends on 2/3/4 all being present).
