import pytest

from accounts.models import Account, User
from forms_app.models import Form

pytestmark = pytest.mark.django_db


def test_dashboard_redirects_anonymous_to_login(client):
    response = client.get("/dashboard")

    assert response.status_code == 302
    assert response.url.startswith("/login")


def test_dashboard_shows_empty_state_with_no_forms(client):
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    client.login(username="owner@example.com", password="s3cret-pass123")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Create your first form" in response.content.decode()


def test_dashboard_lists_only_own_accounts_forms(client):
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    Form.objects.create(account=user.account, name="My Form")

    other_account = Account.objects.create(name="Other Co")
    Form.objects.create(account=other_account, name="Someone Else's Form")

    client.login(username="owner@example.com", password="s3cret-pass123")
    response = client.get("/dashboard")
    content = response.content.decode()

    assert "My Form" in content
    assert "Someone Else's Form" not in content
