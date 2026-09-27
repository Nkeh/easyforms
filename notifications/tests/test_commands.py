from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from accounts.models import Account, User
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _make_account_with_verified_user():
    account = Account.objects.create(name="Acme Inc")
    User.objects.create_user(
        email="owner@example.com", password="s3cret-pass123", account=account, is_verified=True
    )
    return account


def _make_submission(account, age, **kwargs):
    form = Form.objects.create(account=account, name="Contact form")
    submission = Submission.objects.create(
        form=form,
        payload={"name": "Jane"},
        status=kwargs.pop("status", Submission.Status.HAM),
        source_ip_hash="a" * 64,
        notification_status=kwargs.pop(
            "notification_status", Submission.NotificationStatus.PENDING
        ),
        **kwargs,
    )
    Submission.objects.filter(pk=submission.pk).update(created_at=timezone.now() - age)
    submission.refresh_from_db()
    return submission


def test_send_pending_notifications_enqueues_only_within_window():
    account = _make_account_with_verified_user()

    too_new = _make_submission(account, timedelta(seconds=30))
    in_window = _make_submission(account, timedelta(hours=1))
    too_old = _make_submission(account, timedelta(hours=25))
    already_sent = _make_submission(
        account,
        timedelta(hours=1),
        notification_status=Submission.NotificationStatus.SENT,
    )

    call_command("send_pending_notifications")

    too_new.refresh_from_db()
    in_window.refresh_from_db()
    too_old.refresh_from_db()
    already_sent.refresh_from_db()

    assert too_new.notification_status == Submission.NotificationStatus.PENDING
    assert in_window.notification_status == Submission.NotificationStatus.SENT
    assert too_old.notification_status == Submission.NotificationStatus.PENDING
    assert already_sent.notification_status == Submission.NotificationStatus.SENT
    assert len(mail.outbox) == 1


def test_send_pending_notifications_ignores_spam_and_skipped():
    account = _make_account_with_verified_user()

    spam = _make_submission(
        account,
        timedelta(hours=1),
        status=Submission.Status.SPAM,
        notification_status=Submission.NotificationStatus.SKIPPED,
    )
    skipped_ham = _make_submission(
        account,
        timedelta(hours=1),
        notification_status=Submission.NotificationStatus.SKIPPED,
    )

    call_command("send_pending_notifications")

    spam.refresh_from_db()
    skipped_ham.refresh_from_db()
    assert spam.notification_status == Submission.NotificationStatus.SKIPPED
    assert skipped_ham.notification_status == Submission.NotificationStatus.SKIPPED
    assert mail.outbox == []
