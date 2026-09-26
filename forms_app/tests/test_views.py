import pytest
from django.test import override_settings

from accounts.models import Account, User
from forms_app.models import Form

pytestmark = pytest.mark.django_db


def _make_user(account_name="Acme Inc", **kwargs):
    account = Account.objects.create(name=account_name)
    user = User.objects.create_user(
        email=kwargs.pop("email", "owner@example.com"),
        password="s3cret-pass123",
        account=account,
        **kwargs,
    )
    return user


def _make_form(account, **kwargs):
    return Form.objects.create(account=account, name="Contact form", **kwargs)


def test_create_generates_token_and_redirects_to_detail(client):
    user = _make_user()
    client.force_login(user)

    response = client.post("/forms/new", {"name": "Contact form"})

    form = Form.objects.get()
    assert response.status_code == 302
    assert response.url == f"/forms/{form.pk}"
    assert form.account == user.account
    assert form.token


def test_create_anonymous_redirects_to_login(client):
    response = client.get("/forms/new")

    assert response.status_code == 302
    assert response.url.startswith("/login")


def test_detail_of_other_accounts_form_is_404(client):
    other_account = Account.objects.create(name="Other Co")
    other_form = _make_form(other_account)
    user = _make_user()
    client.force_login(user)

    response = client.get(f"/forms/{other_form.pk}")

    assert response.status_code == 404


def test_edit_of_other_accounts_form_is_404(client):
    other_account = Account.objects.create(name="Other Co")
    other_form = _make_form(other_account)
    user = _make_user()
    client.force_login(user)

    response = client.post(f"/forms/{other_form.pk}", {"name": "Hijacked", "spam_action": "flag"})

    assert response.status_code == 404
    other_form.refresh_from_db()
    assert other_form.name == "Contact form"


def test_deactivate_of_other_accounts_form_is_404(client):
    other_account = Account.objects.create(name="Other Co")
    other_form = _make_form(other_account)
    user = _make_user()
    client.force_login(user)

    response = client.post(f"/forms/{other_form.pk}/deactivate")

    assert response.status_code == 404
    other_form.refresh_from_db()
    assert other_form.is_active is True


def test_detail_anonymous_redirects_to_login(client):
    account = Account.objects.create(name="Acme Inc")
    form = _make_form(account)

    response = client.get(f"/forms/{form.pk}")

    assert response.status_code == 302
    assert response.url.startswith("/login")


def test_token_cannot_be_changed_via_post(client):
    user = _make_user()
    form = _make_form(user.account)
    original_token = form.token
    client.force_login(user)

    client.post(
        f"/forms/{form.pk}",
        {"name": "Renamed", "spam_action": "flag", "token": "attacker-supplied-token"},
    )

    form.refresh_from_db()
    assert form.token == original_token
    assert form.name == "Renamed"


def test_deactivate_via_get_is_rejected(client):
    user = _make_user()
    form = _make_form(user.account)
    client.force_login(user)

    response = client.get(f"/forms/{form.pk}/deactivate")

    assert response.status_code == 405


def test_deactivate_via_post_toggles_is_active(client):
    user = _make_user()
    form = _make_form(user.account)
    client.force_login(user)

    response = client.post(f"/forms/{form.pk}/deactivate")

    form.refresh_from_db()
    assert response.status_code == 302
    assert form.is_active is False


def test_activate_via_post_toggles_is_active(client):
    user = _make_user()
    form = _make_form(user.account, is_active=False)
    client.force_login(user)

    response = client.post(f"/forms/{form.pk}/activate")

    form.refresh_from_db()
    assert response.status_code == 302
    assert form.is_active is True


@override_settings(PUBLIC_BASE_URL="http://example.test")
def test_snippet_contains_endpoint_url_and_honeypot(client):
    user = _make_user()
    form = _make_form(user.account)
    client.force_login(user)

    response = client.get(f"/forms/{form.pk}")
    content = response.content.decode()

    assert f"http://example.test/f/{form.token}" in content
    assert "_honeypot" in content


def test_detail_shows_warning_when_no_allowed_origins(client):
    user = _make_user()
    form = _make_form(user.account, allowed_origins=[])
    client.force_login(user)

    response = client.get(f"/forms/{form.pk}")

    assert "Any website can submit to this form" in response.content.decode()


def test_detail_hides_warning_when_allowed_origins_set(client):
    user = _make_user()
    form = _make_form(user.account, allowed_origins=["https://example.com"])
    client.force_login(user)

    response = client.get(f"/forms/{form.pk}")

    assert "Any website can submit to this form" not in response.content.decode()


def test_create_blocked_at_active_forms_limit(client):
    user = _make_user()
    for _ in range(3):
        _make_form(user.account)
    client.force_login(user)

    response = client.post("/forms/new", {"name": "One too many"})

    assert response.status_code == 200
    assert "limit of 3 active forms" in response.content.decode()
    assert Form.objects.filter(account=user.account).count() == 3


def test_create_succeeds_after_deactivating_one_at_limit(client):
    user = _make_user()
    forms = [_make_form(user.account) for _ in range(3)]
    forms[0].is_active = False
    forms[0].save(update_fields=["is_active"])
    client.force_login(user)

    response = client.post("/forms/new", {"name": "Fits now"})

    assert response.status_code == 302
    assert Form.objects.filter(account=user.account, is_active=True).count() == 3


def test_activate_blocked_at_active_forms_limit(client):
    user = _make_user()
    for _ in range(3):
        _make_form(user.account)
    inactive_form = _make_form(user.account, is_active=False)
    client.force_login(user)

    response = client.post(f"/forms/{inactive_form.pk}/activate", follow=True)

    inactive_form.refresh_from_db()
    assert inactive_form.is_active is False
    assert "limit of 3 active forms" in response.content.decode()
