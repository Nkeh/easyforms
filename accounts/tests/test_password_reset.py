import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_reset_done_page_identical_for_known_and_unknown_email(client):
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")

    known_response = client.post("/reset", {"email": "owner@example.com"}, follow=True)
    unknown_response = client.post("/reset", {"email": "nobody@example.com"}, follow=True)

    assert known_response.status_code == unknown_response.status_code == 200
    assert known_response.redirect_chain == unknown_response.redirect_chain
    assert len(mail.outbox) == 1


def test_reset_uses_send_transactional_with_expected_template_and_context(client, monkeypatch):
    calls = []
    monkeypatch.setattr("accounts.forms.send_transactional", lambda **kwargs: calls.append(kwargs))
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")

    client.post("/reset", {"email": "owner@example.com"})

    assert len(calls) == 1
    call = calls[0]
    assert call["to"] == "owner@example.com"
    assert call["template"] == "password_reset"
    assert call["subject"] == "Reset your EasyForms password"
    assert call["context"]["user"] == user
    assert "uid" in call["context"]
    assert "token" in call["context"]


def test_reset_confirm_round_trip_sets_new_password(client):
    User.objects.create_user(email="owner@example.com", password="old-pass-123")
    user = User.objects.get(email="owner@example.com")
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    response = client.get(f"/reset/{uidb64}/{token}", follow=True)
    assert response.status_code == 200
    confirm_url = response.redirect_chain[-1][0]

    response = client.post(
        confirm_url,
        {"new_password1": "brand-new-pass-456", "new_password2": "brand-new-pass-456"},
    )

    assert response.status_code == 302
    assert response.url == "/reset/complete"
    assert client.login(username="owner@example.com", password="brand-new-pass-456")


def test_reset_request_is_rate_limited_by_ip(settings):
    settings.AUTH_RATE_LIMIT_RESET_IP_PER_HOUR = 2
    settings.AUTH_RATE_LIMIT_RESET_EMAIL_PER_HOUR = 1000

    Client().post("/reset", {"email": "a@example.com"})
    Client().post("/reset", {"email": "b@example.com"})
    response = Client().post("/reset", {"email": "c@example.com"})

    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0


def test_reset_request_is_rate_limited_by_email(client, settings):
    settings.AUTH_RATE_LIMIT_RESET_IP_PER_HOUR = 1000
    settings.AUTH_RATE_LIMIT_RESET_EMAIL_PER_HOUR = 2

    client.post("/reset", {"email": "owner@example.com"})
    client.post("/reset", {"email": "owner@example.com"})
    response = client.post("/reset", {"email": "owner@example.com"})

    assert response.status_code == 429


def test_reset_rate_limit_response_identical_for_known_and_unknown_email(settings):
    settings.AUTH_RATE_LIMIT_RESET_IP_PER_HOUR = 1000
    settings.AUTH_RATE_LIMIT_RESET_EMAIL_PER_HOUR = 1
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")

    known_client = Client()
    known_client.post("/reset", {"email": "owner@example.com"})
    known_response = known_client.post("/reset", {"email": "owner@example.com"})

    unknown_client = Client()
    unknown_client.post("/reset", {"email": "nobody@example.com"})
    unknown_response = unknown_client.post("/reset", {"email": "nobody@example.com"})

    assert known_response.status_code == unknown_response.status_code == 429
    assert known_response.content == unknown_response.content
