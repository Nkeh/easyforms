import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_dashboard_redirects_anonymous_to_login(client):
    response = client.get("/dashboard")

    assert response.status_code == 302
    assert response.url.startswith("/login")


def test_dashboard_shows_placeholder_for_logged_in_user(client):
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    client.login(username="owner@example.com", password="s3cret-pass123")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Day 11" in response.content.decode()
