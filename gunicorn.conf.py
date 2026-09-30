import os

# ~186MB/worker (the in-process spam model + Django); default 2 fits a small
# single instance, override via WEB_CONCURRENCY for a bigger box.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))


def post_worker_init(worker):
    """Warm spam.scoring's process-level scorer before this worker accepts
    requests. Import is local to this function, not module-level: gunicorn's
    master process executes this whole config file before any worker forks
    and before config.wsgi (which runs django.setup()) is ever imported — a
    module-level `from spam import scoring` here would import a Django model
    module before the app registry is ready and crash boot entirely.
    post_worker_init runs inside a forked worker, after that worker's own
    load_wsgi() has already triggered django.setup(), so the deferred import
    here is safe.
    """
    try:
        from spam import scoring

        scoring.warm()
    except Exception:
        # scoring.warm() -> Scorer._do_refresh_locked already swallows its own
        # failures (falls back to heuristics-only or keeps serving the last
        # good version); this is belt-and-suspenders so a worker-boot hook can
        # never prevent the worker itself from coming up.
        worker.log.exception("spam scorer warm() failed during worker boot")
