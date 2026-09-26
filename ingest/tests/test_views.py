import json
import logging

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import Account
from core.utils import hash_ip
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _make_form(**kwargs):
    account = kwargs.pop("account", None) or Account.objects.create(name="Acme Inc")
    kwargs.setdefault("name", "Contact form")
    return Form.objects.create(account=account, **kwargs)


def test_json_submission_is_stored(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}",
        data=json.dumps({"name": "Jane", "email": "jane@example.com"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.form == form
    assert submission.payload == {"name": "Jane", "email": "jane@example.com"}
    assert submission.status == Submission.Status.HAM
    assert submission.spam_score is None
    assert submission.model_version is None
    assert response.json()["id"] == str(submission.id)


def test_form_encoded_submission_is_stored(client):
    form = _make_form()

    response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.payload == {"name": "Jane"}


def test_multi_value_field_stored_as_list(client):
    form = _make_form()

    response = client.post(f"/f/{form.token}", {"interests": ["a", "b", "c"]})

    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.payload == {"interests": ["a", "b", "c"]}


def test_reserved_fields_are_stripped_from_payload(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane", "_honeypot": "", "_ts": "12345", "_redirect": "https://x.example.com"},
    )

    assert response.status_code == 200
    submission = Submission.objects.get()
    assert submission.payload == {"name": "Jane"}


def test_nested_json_returns_422(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}",
        data=json.dumps({"name": "Jane", "address": {"city": "NYC"}}),
        content_type="application/json",
    )

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "invalid_payload"
    assert Submission.objects.count() == 0


def test_invalid_json_returns_422(client):
    form = _make_form()

    response = client.post(f"/f/{form.token}", data="{not json", content_type="application/json")

    assert response.status_code == 422
    assert Submission.objects.count() == 0


def test_file_upload_returns_422(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane", "attachment": SimpleUploadedFile("a.txt", b"content")},
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


def test_unsupported_content_type_returns_415(client):
    form = _make_form()

    response = client.post(f"/f/{form.token}", data="hello", content_type="text/plain")

    assert response.status_code == 415
    assert Submission.objects.count() == 0


def test_unknown_token_returns_404(client):
    response = client.post("/f/does-not-exist", {"name": "Jane"})

    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "not_found"


def test_inactive_form_returns_404(client):
    form = _make_form(is_active=False)

    response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert response.status_code == 404


def test_get_is_rejected_with_405(client):
    form = _make_form()

    response = client.get(f"/f/{form.token}")

    assert response.status_code == 405


def test_allowed_origin_gets_echoed_acao_and_vary(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}", {"name": "Jane"}, HTTP_ORIGIN="https://good.example.com"
    )

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "https://good.example.com"
    assert response["Vary"] == "Origin"
    assert "Access-Control-Allow-Credentials" not in response


def test_disallowed_origin_returns_403_and_stores_nothing(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}", {"name": "Jane"}, HTTP_ORIGIN="https://evil.example.com"
    )

    assert response.status_code == 403
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "origin_not_allowed"
    assert Submission.objects.count() == 0


def test_empty_allow_list_accepts_any_origin(client):
    form = _make_form(allowed_origins=[])

    response = client.post(
        f"/f/{form.token}", {"name": "Jane"}, HTTP_ORIGIN="https://anywhere.example.com"
    )

    assert response.status_code == 200


def test_missing_origin_header_is_accepted(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert response.status_code == 200


def test_null_origin_rejected_when_allow_list_non_empty(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(f"/f/{form.token}", {"name": "Jane"}, HTTP_ORIGIN="null")

    assert response.status_code == 403


def test_preflight_allowed_origin_returns_204(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.options(f"/f/{form.token}", HTTP_ORIGIN="https://good.example.com")

    assert response.status_code == 204
    assert response["Access-Control-Allow-Origin"] == "https://good.example.com"
    assert response["Access-Control-Allow-Methods"] == "POST"
    assert response["Access-Control-Allow-Headers"] == "Content-Type"
    assert response["Access-Control-Max-Age"] == "86400"


def test_preflight_disallowed_origin_returns_403(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.options(f"/f/{form.token}", HTTP_ORIGIN="https://evil.example.com")

    assert response.status_code == 403


def test_stored_ip_hash_matches_hash_ip_and_never_equals_raw_ip(client, settings):
    settings.IP_HASH_SECRET = "test-secret"
    form = _make_form()

    client.post(f"/f/{form.token}", {"name": "Jane"}, REMOTE_ADDR="203.0.113.7")

    submission = Submission.objects.get()
    assert submission.source_ip_hash == hash_ip("203.0.113.7")
    assert submission.source_ip_hash != "203.0.113.7"


def test_log_output_contains_no_payload_values(client, caplog):
    form = _make_form()

    with caplog.at_level(logging.INFO, logger="ingest"):
        client.post(f"/f/{form.token}", {"name": "TOP-SECRET-MARKER-VALUE"})

    assert "TOP-SECRET-MARKER-VALUE" not in caplog.text
    assert str(form.id) in caplog.text
    assert "status=200" in caplog.text


# --- HTML-mode redirects (FR-3.5) ------------------------------------------


def test_html_mode_success_redirects_to_allowed_redirect_field(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane", "_redirect": "https://good.example.com/thank-you"},
        HTTP_ACCEPT="text/html",
    )

    assert response.status_code == 303
    assert response["Location"] == "https://good.example.com/thank-you"


def test_html_mode_redirect_falls_back_to_redirect_url_when_origin_not_allowed(client):
    form = _make_form(
        allowed_origins=["https://good.example.com"],
        redirect_url="https://good.example.com/fallback",
    )

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane", "_redirect": "https://evil.example.com/x"},
        HTTP_ACCEPT="text/html",
    )

    assert response.status_code == 303
    assert response["Location"] == "https://good.example.com/fallback"


def test_html_mode_redirect_ignored_when_allow_list_empty(client):
    form = _make_form(allowed_origins=[], redirect_url="https://good.example.com/fallback")

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane", "_redirect": "https://good.example.com/x"},
        HTTP_ACCEPT="text/html",
    )

    assert response.status_code == 303
    assert response["Location"] == "https://good.example.com/fallback"


def test_html_mode_javascript_redirect_ignored(client):
    form = _make_form(
        allowed_origins=["https://good.example.com"],
        redirect_url="https://good.example.com/fallback",
    )

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane", "_redirect": "javascript:alert(1)"},
        HTTP_ACCEPT="text/html",
    )

    assert response.status_code == 303
    assert response["Location"] == "https://good.example.com/fallback"


def test_html_mode_falls_back_to_thanks_page(client):
    form = _make_form(allowed_origins=[], redirect_url=None)

    response = client.post(f"/f/{form.token}", {"name": "Jane"}, HTTP_ACCEPT="text/html")

    assert response.status_code == 303
    assert response["Location"] == "/thanks"


def test_thanks_page_renders_with_noindex(client):
    response = client.get("/thanks")

    assert response.status_code == 200
    assert 'name="robots" content="noindex"' in response.content.decode()


# --- Error format in both response modes (FR-3.6) --------------------------


def test_not_found_error_json_mode(client):
    response = client.post("/f/does-not-exist", {"name": "Jane"})

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": "not_found",
        "message": "This form does not exist or is no longer accepting submissions.",
    }


def test_not_found_error_html_mode(client):
    response = client.post("/f/does-not-exist", {"name": "Jane"}, HTTP_ACCEPT="text/html")

    assert response.status_code == 404
    assert response["Content-Type"].startswith("text/html")
    assert "does not exist" in response.content.decode()


def test_method_not_allowed_error_json_mode(client):
    form = _make_form()

    response = client.get(f"/f/{form.token}")

    assert response.status_code == 405
    assert response.json()["error"] == "method_not_allowed"
    assert response["Allow"] == "POST, OPTIONS"


def test_method_not_allowed_error_html_mode(client):
    form = _make_form()

    response = client.get(f"/f/{form.token}", HTTP_ACCEPT="text/html")

    assert response.status_code == 405
    assert response["Content-Type"].startswith("text/html")


def test_origin_not_allowed_error_json_mode(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}", {"name": "Jane"}, HTTP_ORIGIN="https://evil.example.com"
    )

    assert response.status_code == 403
    assert response.json()["error"] == "origin_not_allowed"
    assert "Access-Control-Allow-Origin" not in response


def test_origin_not_allowed_error_html_mode(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane"},
        HTTP_ORIGIN="https://evil.example.com",
        HTTP_ACCEPT="text/html",
    )

    assert response.status_code == 403
    assert response["Content-Type"].startswith("text/html")


def test_unsupported_media_type_error_json_mode(client):
    form = _make_form()

    response = client.post(f"/f/{form.token}", data="hello", content_type="text/plain")

    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_media_type"


def test_unsupported_media_type_error_html_mode(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}", data="hello", content_type="text/plain", HTTP_ACCEPT="text/html"
    )

    assert response.status_code == 415
    assert response["Content-Type"].startswith("text/html")


def test_invalid_payload_error_json_mode(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}",
        data=json.dumps({"name": "Jane", "address": {"city": "NYC"}}),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_payload"


def test_invalid_payload_error_html_mode(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane", "attachment": SimpleUploadedFile("a.txt", b"content")},
        HTTP_ACCEPT="text/html",
    )

    assert response.status_code == 422
    assert response["Content-Type"].startswith("text/html")


def test_payload_too_large_from_content_length_json_mode(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}",
        data=json.dumps({"name": "Jane"}),
        content_type="application/json",
        CONTENT_LENGTH=str(10 * 1024 * 1024),
    )

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"
    assert Submission.objects.count() == 0


def test_payload_too_large_from_content_length_html_mode(client):
    form = _make_form()

    response = client.post(
        f"/f/{form.token}",
        {"name": "Jane"},
        HTTP_ACCEPT="text/html",
        CONTENT_LENGTH=str(10 * 1024 * 1024),
    )

    assert response.status_code == 413
    assert response["Content-Type"].startswith("text/html")


def test_payload_too_large_in_parse_json_mode(client, settings):
    settings.INGEST_MAX_FIELDS = 1
    form = _make_form()

    response = client.post(f"/f/{form.token}", {"a": "1", "b": "2"})

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


# --- CORS on error responses (FR-3.6) ---------------------------------------


def test_in_parse_payload_too_large_carries_acao_when_origin_allowed(client, settings):
    settings.INGEST_MAX_FIELDS = 1
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}", {"a": "1", "b": "2"}, HTTP_ORIGIN="https://good.example.com"
    )

    assert response.status_code == 413
    assert response["Access-Control-Allow-Origin"] == "https://good.example.com"


def test_unsupported_media_type_carries_acao_when_origin_allowed(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}",
        data="hello",
        content_type="text/plain",
        HTTP_ORIGIN="https://good.example.com",
    )

    assert response.status_code == 415
    assert response["Access-Control-Allow-Origin"] == "https://good.example.com"


def test_invalid_payload_carries_acao_when_origin_allowed(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}",
        data=json.dumps({"name": "Jane", "address": {"city": "NYC"}}),
        content_type="application/json",
        HTTP_ORIGIN="https://good.example.com",
    )

    assert response.status_code == 422
    assert response["Access-Control-Allow-Origin"] == "https://good.example.com"


def test_pre_lookup_payload_too_large_never_carries_acao(client):
    form = _make_form(allowed_origins=["https://good.example.com"])

    response = client.post(
        f"/f/{form.token}",
        data=json.dumps({"name": "Jane"}),
        content_type="application/json",
        HTTP_ORIGIN="https://good.example.com",
        CONTENT_LENGTH=str(10 * 1024 * 1024),
    )

    assert response.status_code == 413
    assert "Access-Control-Allow-Origin" not in response


def test_not_found_never_carries_acao(client):
    response = client.post(
        "/f/does-not-exist", {"name": "Jane"}, HTTP_ORIGIN="https://good.example.com"
    )

    assert response.status_code == 404
    assert "Access-Control-Allow-Origin" not in response


def test_method_not_allowed_never_carries_acao(client):
    form = _make_form()

    response = client.get(f"/f/{form.token}", HTTP_ORIGIN="https://good.example.com")

    assert response.status_code == 405
    assert "Access-Control-Allow-Origin" not in response
