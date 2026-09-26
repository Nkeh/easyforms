import pytest

from accounts.models import User
from accounts.tokens import make_verification_token, read_verification_token

pytestmark = pytest.mark.django_db


def test_make_and_read_verification_token_roundtrip():
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass")

    token = make_verification_token(user)

    assert read_verification_token(token) == str(user.id)


def test_read_verification_token_rejects_tampered_token():
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass")
    token = make_verification_token(user)
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

    assert read_verification_token(tampered) is None


def test_read_verification_token_rejects_expired_token():
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass")
    token = make_verification_token(user)

    assert read_verification_token(token, max_age=-1) is None
