# Runbook

Operational procedures for the production Docker Compose stack
(`docker-compose.prod.yml`). All commands assume you're in the repo root on
the host that runs the stack, with a real `.env` (see
`.env.production.example`) next to it.

## First deploy

1. Provision a host (VPS or PaaS container host) with Docker + Compose
   installed, and point `DOMAIN` at it (A/AAAA record).
2. Copy `.env.production.example` to `.env`, fill in every blank value (see
   that file's comments for how to generate secrets).
3. `docker compose -f docker-compose.prod.yml build`
4. `docker compose -f docker-compose.prod.yml run --rm web python manage.py check --deploy`
   — must report no issues before continuing.
5. `docker compose -f docker-compose.prod.yml up -d db redis` — bring up
   state first.
6. `docker compose -f docker-compose.prod.yml run --rm web python manage.py migrate`
   — the release step; deliberately not baked into any service's `command`.
7. `docker compose -f docker-compose.prod.yml up -d` — start everything else
   (web, worker, scheduler, caddy).
8. Visit `https://$DOMAIN` and confirm the app loads over TLS.
9. Bootstrap the spam model once real data exists (Day 8's
   `train_spam_model` / `activate_spam_model`, run the same way as below).

## Routine deploy

```
git pull
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm web python manage.py check --deploy
docker compose -f docker-compose.prod.yml run --rm web python manage.py migrate
docker compose -f docker-compose.prod.yml up -d
```
`up -d` recreates any service whose image changed and leaves the rest alone.
Tag images with the git SHA (`docker compose ... build --build-arg ...` or
`docker tag easyforms:latest easyforms:<sha>`) if you want a specific
rollback target rather than just "the previous build."

## Rollback

If you tagged images per-deploy: retag the previous image as `easyforms:latest`
(or point `image:` at the specific tag in `docker-compose.prod.yml`), then:
```
docker compose -f docker-compose.prod.yml up -d
```
If the failing deploy included a migration, roll the migration back first
(`manage.py migrate <app> <previous_migration_name>`) before rolling the code
back — this stack has no automatic migration-rollback step, by design (see
"Migrations" in CLAUDE.md: never edit an applied migration).

## Restore from backup

**Never restore into the live `DATABASE_URL` directly** — `manage.py restore`
has no default target for exactly this reason; you must always pass
`--database-url` explicitly.

1. Find the backup key (local: list `BACKUP_LOCAL_DIR`; R2: list the bucket
   under `backups/`) — keys look like `backups/2026/09/30/20260930T020000Z.dump.gz`.
2. Restore into a **fresh, empty** database first to verify the backup
   before touching anything live:
   ```
   docker compose -f docker-compose.prod.yml exec db \
     createdb -U $POSTGRES_USER restore_check
   docker compose -f docker-compose.prod.yml run --rm web \
     python manage.py restore --key backups/2026/09/30/20260930T020000Z.dump.gz \
     --database-url postgres://easyforms:<password>@db:5432/restore_check
   ```
3. Spot-check row counts / recent rows in `restore_check`, then drop it.
4. Only once verified: stop `web`/`worker`/`scheduler`, restore into the real
   target database, then bring the stack back up.

## Rotate secrets

1. Generate the new value (see `.env.production.example`'s comments).
2. Update `.env` on the host.
3. `docker compose -f docker-compose.prod.yml up -d` — recreates services
   that read `env_file: .env` with the new values (gunicorn/rqworker/
   supercronic processes all restart; sessions/CSRF cookies signed with the
   old `SECRET_KEY` are invalidated if you rotate that one).
4. Rotating `R2_ACCESS_KEY_ID`/`BACKUP_R2_ACCESS_KEY_ID`: create the new R2
   token first, confirm the app can read/write with it, *then* revoke the
   old token in the Cloudflare dashboard — don't revoke before confirming.

## Activate a new spam model

Unchanged from Day 8/9 — training happens offline, activation is explicit:
```
docker compose -f docker-compose.prod.yml run --rm web \
  python manage.py train_spam_model --dataset ...
docker compose -f docker-compose.prod.yml run --rm web \
  python manage.py eval_spam_model <new-version>
docker compose -f docker-compose.prod.yml run --rm web \
  python manage.py activate_spam_model <new-version>
```
The web/worker processes pick up the newly active `ModelVersion` within
`SPAM_MODEL_REFRESH_SECONDS` (default 60s) — no restart needed.

## Read `spam_report`

```
docker compose -f docker-compose.prod.yml run --rm web \
  python manage.py spam_report --days 7
```
Also runs daily at 06:00 UTC via the `scheduler` service
(`deploy/crontab`) — its output lands in `scheduler`'s container logs
(`docker compose -f docker-compose.prod.yml logs scheduler`). A `WARNING`-level
"ALERT" line means the false-positive rate crossed `SPAM_FP_ALERT_RATE`
(default 2%) with at least `SPAM_ALERT_MIN_ROWS` (default 50) spam-labelled
rows in the window — the signal to look at recent corrections and consider
retraining (SRS §7).

## R2 lifecycle rule (backups)

Not implemented in code — configure directly in the Cloudflare dashboard on
`BACKUP_BUCKET`: a lifecycle rule that expires (deletes) objects under the
`backups/` prefix after 30 days, so old backups don't accumulate storage
cost indefinitely. `ARTIFACT_STORAGE`'s bucket (model artifacts) should
*not* get this rule — those are kept deliberately.
