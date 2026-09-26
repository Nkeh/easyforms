import pytest
from django.core import mail
from django.db import IntegrityError

from accounts.models import Account, User

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
