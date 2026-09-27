import logging

import pytest
from django.core import mail

from accounts.models import Account, User
from core import circuit_breaker
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _make_form(**kwargs):
    account = kwargs.pop("account", None) or Account.objects.create(name="Acme Inc")
    kwargs.setdefault("name", "Contact form")
    return Form.objects.create(account=account, **kwargs)


def _add_verified_user(account):
    User.objects.create_user(
        email="owner@example.com", password="s3cret-pass123", account=account, is_verified=True
    )


def test_ham_submission_does_not_send_before_commit(client):
    account = Account.objects.create(name="Acme Inc")
    _add_verified_user(account)
    form = _make_form(account=account)

    # No django_capture_on_commit_callbacks wrapper here on purpose: pytest-django
    # wraps each test in a rolled-back transaction, so on_commit callbacks
    # registered inside it never actually run.
    response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.notification_status == Submission.NotificationStatus.PENDING
    assert mail.outbox == []


def test_ham_submission_sends_email_after_commit(client, django_capture_on_commit_callbacks):
    account = Account.objects.create(name="Acme Inc")
    _add_verified_user(account)
    form = _make_form(account=account)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert len(callbacks) == 1
    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.notification_status == Submission.NotificationStatus.SENT
    assert len(mail.outbox) == 1


def test_ham_submission_skipped_when_no_verified_user(client, django_capture_on_commit_callbacks):
    account = Account.objects.create(name="Acme Inc")
    form = _make_form(account=account)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert len(callbacks) == 0
    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.notification_status == Submission.NotificationStatus.SKIPPED
    assert mail.outbox == []


def test_spam_flag_submission_is_skipped_and_never_enqueues(
    client, django_capture_on_commit_callbacks
):
    account = Account.objects.create(name="Acme Inc")
    _add_verified_user(account)
    form = _make_form(account=account)  # spam_action defaults to "flag"

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = client.post(f"/f/{form.token}", {"name": "Jane", "_honeypot": "bot-filled"})

    assert len(callbacks) == 0
    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.status == Submission.Status.SPAM
    assert submission.notification_status == Submission.NotificationStatus.SKIPPED
    assert mail.outbox == []


def test_spam_drop_submission_creates_no_row(client, django_capture_on_commit_callbacks):
    account = Account.objects.create(name="Acme Inc")
    _add_verified_user(account)
    form = _make_form(account=account, spam_action=Form.SpamAction.DROP)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = client.post(f"/f/{form.token}", {"name": "Jane", "_honeypot": "bot-filled"})

    assert len(callbacks) == 0
    assert response.status_code == 200
    assert Submission.objects.count() == 0
    assert mail.outbox == []


def test_redis_down_at_enqueue_returns_200_and_leaves_pending(
    client, django_capture_on_commit_callbacks, monkeypatch, caplog
):
    account = Account.objects.create(name="Acme Inc")
    _add_verified_user(account)
    form = _make_form(account=account)

    def _raise(_submission_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr("ingest.views.enqueue_submission_notification", _raise)

    with caplog.at_level(logging.WARNING, logger="ingest"):
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.notification_status == Submission.NotificationStatus.PENDING
    assert mail.outbox == []
    assert any("failed to enqueue submission notification" in r.message for r in caplog.records)


def test_breaker_open_at_enqueue_skips_redis_and_leaves_pending(
    client, django_capture_on_commit_callbacks, monkeypatch, caplog
):
    circuit_breaker.trip()

    def _fail_if_called(name):
        raise AssertionError("must not touch django_rq while the breaker is open")

    monkeypatch.setattr("notifications.tasks.django_rq.get_queue", _fail_if_called)

    account = Account.objects.create(name="Acme Inc")
    _add_verified_user(account)
    form = _make_form(account=account)

    with caplog.at_level(logging.WARNING, logger="ingest"):
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.notification_status == Submission.NotificationStatus.PENDING
    assert mail.outbox == []
    assert any("failed to enqueue submission notification" in r.message for r in caplog.records)
