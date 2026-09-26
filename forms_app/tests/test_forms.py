import pytest

from accounts.models import Account
from forms_app.forms import FormEditForm
from forms_app.models import Form

pytestmark = pytest.mark.django_db


def _make_form(**kwargs):
    account = kwargs.pop("account", None) or Account.objects.create(name="Acme Inc")
    return Form.objects.create(account=account, name="Contact form", **kwargs)


def _edit(form_obj, allowed_origins="", redirect_url=""):
    return FormEditForm(
        data={
            "name": form_obj.name,
            "allowed_origins": allowed_origins,
            "redirect_url": redirect_url,
            "spam_action": form_obj.spam_action,
        },
        instance=form_obj,
    )


def test_initial_allowed_origins_renders_as_newline_joined_text():
    form_obj = _make_form(allowed_origins=["https://a.example.com", "https://b.example.com"])

    form = FormEditForm(instance=form_obj)

    assert form.initial["allowed_origins"] == "https://a.example.com\nhttps://b.example.com"


def test_valid_https_origin_is_accepted():
    form = _edit(_make_form(), allowed_origins="https://example.com")

    assert form.is_valid(), form.errors
    assert form.cleaned_data["allowed_origins"] == ["https://example.com"]


def test_http_localhost_and_127_allowed_with_any_port():
    form = _edit(
        _make_form(),
        allowed_origins="http://localhost:3000\nhttp://127.0.0.1:8080",
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["allowed_origins"] == [
        "http://localhost:3000",
        "http://127.0.0.1:8080",
    ]


def test_origin_with_path_is_rejected():
    form = _edit(_make_form(), allowed_origins="https://example.com/webhook")

    assert not form.is_valid()
    assert "path" in str(form.errors["allowed_origins"])


def test_origin_with_trailing_slash_is_rejected():
    form = _edit(_make_form(), allowed_origins="https://example.com/")

    assert not form.is_valid()


def test_origin_with_wildcard_is_rejected():
    form = _edit(_make_form(), allowed_origins="https://*.example.com")

    assert not form.is_valid()
    assert "wildcard" in str(form.errors["allowed_origins"])


def test_http_non_localhost_is_rejected():
    form = _edit(_make_form(), allowed_origins="http://example.com")

    assert not form.is_valid()
    assert "https" in str(form.errors["allowed_origins"])


def test_origins_are_normalized_and_deduped():
    form = _edit(
        _make_form(),
        allowed_origins="HTTPS://Example.com\nhttps://example.com\n  https://example.com  ",
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["allowed_origins"] == ["https://example.com"]


def test_redirect_url_accepts_http_and_https():
    form = _edit(_make_form(), redirect_url="https://example.com/thanks")

    assert form.is_valid(), form.errors


def test_redirect_url_rejects_non_http_scheme():
    form = _edit(_make_form(), redirect_url="ftp://example.com/thanks")

    assert not form.is_valid()
    assert "http" in str(form.errors["redirect_url"])
