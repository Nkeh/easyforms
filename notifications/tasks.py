import logging

import django_rq
import redis
from django.utils import timezone
from rq import Retry, get_current_job

from core import circuit_breaker
from forms_app.models import Submission
from notifications import email

logger = logging.getLogger("notifications")

RETRY = Retry(max=3, interval=[10, 60, 300])


def _enqueue(func, **enqueue_kwargs) -> None:
    """Shared enqueue path for both job types: skips Redis entirely (raising
    immediately) while the circuit breaker is open, and trips it on a real
    Redis failure so the *next* Redis-touching call (rate limiter or
    another enqueue) also skips instead of hanging on its own timeout.

    Deliberately NOT wrapped in core.bounded_call's thread-pool timeout
    (unlike core.ratelimit.hit): with the test suite's RQ_QUEUES ASYNC=False,
    .enqueue() executes the job function synchronously as part of this call
    — running that on a bounded_call worker thread would give the job a
    different (thread-local) DB connection than the test's own transaction,
    so it silently can't see the just-created Submission row. In production
    ASYNC=True, so .enqueue() only ever does a fast Redis push here — the
    ingest hot path is still protected because core.ratelimit's calls run
    first and, on a Redis outage, already trip the shared breaker before
    this is ever reached (see ingest/views.py's call order).
    """
    if circuit_breaker.is_open():
        raise circuit_breaker.CircuitOpenError("redis circuit breaker open")
    try:
        django_rq.get_queue("emails").enqueue(func, retry=RETRY, **enqueue_kwargs)
    except redis.RedisError:
        circuit_breaker.trip()
        raise


def enqueue_transactional_job(*, to: str, subject: str, template: str, context: dict) -> None:
    _enqueue(
        send_transactional_job,
        kwargs={"to": to, "subject": subject, "template": template, "context": context},
    )


def send_transactional_job(*, to: str, subject: str, template: str, context: dict) -> None:
    email._send_now(to=to, subject=subject, template=template, context=context)


def enqueue_submission_notification(submission_id) -> None:
    _enqueue(send_submission_notification, args=(submission_id,))


def send_submission_notification(submission_id) -> None:
    """Re-fetches the submission by id (never passed the ORM object across
    the enqueue boundary) so a deleted submission is a clean no-op and the
    job always acts on current data.
    """
    job = get_current_job()

    try:
        submission = Submission.objects.select_related("form", "form__account").get(
            id=submission_id
        )
    except Submission.DoesNotExist:
        return

    if submission.notification_status == Submission.NotificationStatus.SENT:
        return  # idempotent: a re-run must never send a second email

    recipients = list(
        submission.form.account.users.filter(is_verified=True)
        .order_by("email")
        .values_list("email", flat=True)
    )
    if not recipients:
        # Defensive only: ingest already sets notification_status=skipped at
        # store time when there's no verified user (FR-1.2). Kept as a
        # safety net against a race where verification state changed between
        # store and send.
        Submission.objects.filter(id=submission_id).update(
            notification_status=Submission.NotificationStatus.SKIPPED
        )
        return

    try:
        email.send_submission_email(submission, recipients)
    except Exception:
        if job is None or (job.retries_left or 0) <= 0:
            logger.warning(
                "notifications: giving up on submission notification submission_id=%s",
                submission_id,
                exc_info=True,
            )
            Submission.objects.filter(id=submission_id).update(
                notification_status=Submission.NotificationStatus.FAILED
            )
        raise  # let RQ's own Retry/backoff own the retry decision

    Submission.objects.filter(id=submission_id).update(
        notification_status=Submission.NotificationStatus.SENT,
        notified_at=timezone.now(),
    )
