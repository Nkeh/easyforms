import uuid
from types import SimpleNamespace

import pytest
import redis
from django.core import mail

from accounts.models import Account, User
from core import circuit_breaker
from forms_app.models import Form, Submission
from notifications import tasks

pytestmark = pytest.mark.django_db


def _make_account_with_verified_user():
    account = Account.objects.create(name="Acme Inc")
    User.objects.create_user(
        email="owner@example.com", password="s3cret-pass123", account=account, is_verified=True
    )
    return account


def _make_submission(account=None, **kwargs):
    account = account or _make_account_with_verified_user()
    form = kwargs.pop("form", None) or Form.objects.create(account=account, name="Contact form")
    return Submission.objects.create(
        form=form,
        payload=kwargs.pop("payload", {"name": "Jane"}),
        status=Submission.Status.HAM,
        original_status=Submission.Status.HAM,
        source_ip_hash="a" * 64,
        notification_status=kwargs.pop(
            "notification_status", Submission.NotificationStatus.PENDING
        ),
        **kwargs,
    )


def test_send_submission_notification_sends_and_marks_sent():
    submission = _make_submission()

    tasks.send_submission_notification(submission.id)

    submission.refresh_from_db()
    assert submission.notification_status == Submission.NotificationStatus.SENT
    assert submission.notified_at is not None
    assert len(mail.outbox) == 1


def test_send_submission_notification_is_idempotent():
    submission = _make_submission()

    tasks.send_submission_notification(submission.id)
    tasks.send_submission_notification(submission.id)

    assert len(mail.outbox) == 1
    submission.refresh_from_db()
    assert submission.notification_status == Submission.NotificationStatus.SENT


def test_send_submission_notification_deleted_submission_is_noop():
    tasks.send_submission_notification(uuid.uuid4())

    assert mail.outbox == []


def test_send_submission_notification_marks_failed_on_final_attempt(monkeypatch):
    submission = _make_submission()
    monkeypatch.setattr(
        tasks.email,
        "send_submission_email",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(tasks, "get_current_job", lambda: SimpleNamespace(retries_left=0))

    with pytest.raises(RuntimeError):
        tasks.send_submission_notification(submission.id)

    submission.refresh_from_db()
    assert submission.notification_status == Submission.NotificationStatus.FAILED


def test_send_submission_notification_leaves_pending_when_retries_remain(monkeypatch):
    submission = _make_submission()
    monkeypatch.setattr(
        tasks.email,
        "send_submission_email",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(tasks, "get_current_job", lambda: SimpleNamespace(retries_left=2))

    with pytest.raises(RuntimeError):
        tasks.send_submission_notification(submission.id)

    submission.refresh_from_db()
    assert submission.notification_status == Submission.NotificationStatus.PENDING


def test_send_submission_notification_no_job_context_treated_as_final_attempt(monkeypatch):
    submission = _make_submission()
    monkeypatch.setattr(
        tasks.email,
        "send_submission_email",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(tasks, "get_current_job", lambda: None)

    with pytest.raises(RuntimeError):
        tasks.send_submission_notification(submission.id)

    submission.refresh_from_db()
    assert submission.notification_status == Submission.NotificationStatus.FAILED


def test_send_submission_notification_skips_if_no_verified_user_when_job_runs():
    account = Account.objects.create(name="Acme Inc")
    form = Form.objects.create(account=account, name="Contact form")
    submission = Submission.objects.create(
        form=form,
        payload={"name": "Jane"},
        status=Submission.Status.HAM,
        source_ip_hash="a" * 64,
        notification_status=Submission.NotificationStatus.PENDING,
    )

    tasks.send_submission_notification(submission.id)

    submission.refresh_from_db()
    assert submission.notification_status == Submission.NotificationStatus.SKIPPED
    assert mail.outbox == []


def test_enqueue_raises_immediately_when_breaker_open_without_touching_redis(monkeypatch):
    circuit_breaker.trip()

    def _fail_if_called(name):
        raise AssertionError("enqueue must not touch django_rq while the breaker is open")

    monkeypatch.setattr(tasks.django_rq, "get_queue", _fail_if_called)

    with pytest.raises(circuit_breaker.CircuitOpenError):
        tasks.enqueue_submission_notification(uuid.uuid4())


def test_enqueue_trips_the_shared_breaker_on_redis_error(monkeypatch):
    class FakeQueue:
        def enqueue(self, *args, **kwargs):
            raise redis.exceptions.ConnectionError("boom")

    monkeypatch.setattr(tasks.django_rq, "get_queue", lambda name: FakeQueue())

    assert circuit_breaker.is_open() is False
    with pytest.raises(redis.exceptions.ConnectionError):
        tasks.enqueue_submission_notification(uuid.uuid4())
    assert circuit_breaker.is_open() is True


def test_enqueue_transactional_job_and_enqueue_submission_notification_use_retry(monkeypatch):
    calls = []

    class FakeQueue:
        def enqueue(self, func, *args, **kwargs):
            calls.append((func, args, kwargs))

    monkeypatch.setattr(tasks.django_rq, "get_queue", lambda name: FakeQueue())

    tasks.enqueue_transactional_job(to="a@example.com", subject="s", template="t", context={})
    tasks.enqueue_submission_notification(uuid.uuid4())

    assert len(calls) == 2
    for _func, _args, kwargs in calls:
        assert kwargs["retry"] is tasks.RETRY
