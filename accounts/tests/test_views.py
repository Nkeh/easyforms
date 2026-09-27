import pytest
from django.core import mail
from django.db import IntegrityError
from django.test import Client

from accounts.models import Account, User
from forms_app.models import Form

pytestmark = pytest.mark.django_db


def test_signup_creates_account_and_user_and_logs_in(client):
    response = client.post("/signup", {"email": "New@Example.com", "password": "s3cret-pass123"})

    assert response.status_code == 302
    assert response.url == "/dashboard"
    assert Account.objects.count() == 1
    user = User.objects.get()
    assert user.email == "new@example.com"
    assert "_auth_user_id" in client.session
    assert len(mail.outbox) == 1


def test_signup_verification_email_is_sent_via_the_emails_queue_not_inline(client, monkeypatch):
    from notifications.tasks import send_transactional_job

    queue_names = []
    enqueued_funcs = []

    class _RecordingQueue:
        def enqueue(self, func, *args, **kwargs):
            enqueued_funcs.append(func)

    def _get_queue(name):
        queue_names.append(name)
        return _RecordingQueue()

    monkeypatch.setattr("notifications.tasks.django_rq.get_queue", _get_queue)

    client.post("/signup", {"email": "new@example.com", "password": "s3cret-pass123"})

    assert queue_names == ["emails"]
    assert enqueued_funcs == [send_transactional_job]


def test_signup_rolls_back_account_and_user_when_save_fails(client, monkeypatch):
    def raise_integrity_error(self, *args, **kwargs):
        raise IntegrityError("boom")

    monkeypatch.setattr(User, "save", raise_integrity_error)

    response = client.post("/signup", {"email": "new@example.com", "password": "s3cret-pass123"})

    assert response.status_code == 200
    assert Account.objects.count() == 0
    assert User.objects.count() == 0


def test_signup_rejects_duplicate_email_case_insensitively(client):
    User.objects.create_user(email="dup@example.com", password="s3cret-pass123")

    response = client.post("/signup", {"email": "DUP@Example.com", "password": "s3cret-pass123"})

    assert response.status_code == 200
    assert User.objects.count() == 1


def test_verify_sets_is_verified_true(client):
    from accounts.tokens import make_verification_token

    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    token = make_verification_token(user)

    response = client.get(f"/verify/{token}")

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.is_verified is True


def test_verify_rejects_invalid_token(client):
    response = client.get("/verify/garbage-token")

    assert response.status_code == 200
    assert response.context["success"] is False


def test_login_with_mixed_case_email_succeeds(client):
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")

    response = client.post(
        "/login", {"username": "Owner@Example.com", "password": "s3cret-pass123"}
    )

    assert response.status_code == 302
    assert "_auth_user_id" in client.session


def test_logout_via_get_is_rejected(client):
    response = client.get("/logout")

    assert response.status_code == 405


def test_logout_via_post_succeeds(client):
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    client.login(username="owner@example.com", password="s3cret-pass123")

    response = client.post("/logout")

    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


def test_resend_verification_is_rate_limited(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "accounts.views.send_verification_email", lambda user, request: calls.append(user)
    )
    User.objects.create_user(email="unverified@example.com", password="s3cret-pass123")
    client.login(username="unverified@example.com", password="s3cret-pass123")

    client.post("/resend-verification")
    client.post("/resend-verification")

    assert len(calls) == 1


def test_resend_verification_noop_when_already_verified(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "accounts.views.send_verification_email", lambda user, request: calls.append(user)
    )
    User.objects.create_user(
        email="verified@example.com", password="s3cret-pass123", is_verified=True
    )
    client.login(username="verified@example.com", password="s3cret-pass123")

    client.post("/resend-verification")

    assert calls == []


def test_settings_redirects_anonymous_to_login(client):
    response = client.get("/settings")

    assert response.status_code == 302
    assert response.url.startswith("/login")


def test_settings_shows_email_verified_and_plan(client):
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    client.login(username="owner@example.com", password="s3cret-pass123")

    response = client.get("/settings")

    content = response.content.decode()
    assert "owner@example.com" in content
    assert "free" in content


def test_settings_shows_forms_and_submissions_usage(client):
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    Form.objects.create(account=user.account, name="My form")
    client.login(username="owner@example.com", password="s3cret-pass123")

    response = client.get("/settings")
    content = response.content.decode()

    assert "1 / 3" in content
    assert "0 / 250" in content


def test_login_is_rate_limited_by_ip(client, settings):
    settings.AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE = 2
    settings.AUTH_RATE_LIMIT_LOGIN_EMAIL_PER_MINUTE = 1000
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")

    for _ in range(2):
        response = client.post(
            "/login", {"username": "owner@example.com", "password": "wrong-password"}
        )
        assert response.status_code == 200

    response = client.post(
        "/login", {"username": "owner@example.com", "password": "wrong-password"}
    )

    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0


def test_login_is_rate_limited_by_email_case_insensitively(client, settings):
    settings.AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE = 1000
    settings.AUTH_RATE_LIMIT_LOGIN_EMAIL_PER_MINUTE = 2
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")

    client.post("/login", {"username": "Owner@Example.com", "password": "wrong-password"})
    client.post("/login", {"username": "OWNER@EXAMPLE.COM", "password": "wrong-password"})

    response = client.post(
        "/login", {"username": "owner@example.com", "password": "wrong-password"}
    )

    assert response.status_code == 429


def test_signup_is_rate_limited_by_ip(settings):
    settings.AUTH_RATE_LIMIT_SIGNUP_IP_PER_HOUR = 2

    Client().post("/signup", {"email": "a@example.com", "password": "s3cret-pass123"})
    Client().post("/signup", {"email": "b@example.com", "password": "s3cret-pass123"})
    response = Client().post("/signup", {"email": "c@example.com", "password": "s3cret-pass123"})

    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0
