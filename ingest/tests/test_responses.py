import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from ingest.responses import error_response, wants_json

factory = RequestFactory()

_ALL_CODES = [
    ("origin_not_allowed", 403),
    ("not_found", 404),
    ("method_not_allowed", 405),
    ("payload_too_large", 413),
    ("unsupported_media_type", 415),
    ("invalid_payload", 422),
]


def _form(allowed_origins):
    return SimpleNamespace(allowed_origins=allowed_origins)


@pytest.mark.parametrize(
    "content_type,accept,expected",
    [
        ("application/json", None, True),
        ("application/json", "text/html", True),
        ("application/x-www-form-urlencoded", None, True),
        ("application/x-www-form-urlencoded", "*/*", True),
        ("application/x-www-form-urlencoded", "text/html", False),
        ("application/x-www-form-urlencoded", "text/html,application/xhtml+xml", False),
    ],
)
def test_wants_json_matrix(content_type, accept, expected):
    extra = {}
    if accept is not None:
        extra["HTTP_ACCEPT"] = accept
    request = factory.post("/f/some-token", data="x", content_type=content_type, **extra)

    assert wants_json(request) is expected


@pytest.mark.parametrize("code,status", _ALL_CODES)
def test_error_response_json_mode(code, status):
    request = factory.post("/f/some-token", data="{}", content_type="application/json")

    response = error_response(request, code, status)

    assert response.status_code == status
    body = json.loads(response.content)
    assert body["ok"] is False
    assert body["error"] == code
    assert isinstance(body["message"], str) and body["message"]


@pytest.mark.parametrize("code,status", _ALL_CODES)
def test_error_response_html_mode(code, status):
    request = factory.post(
        "/f/some-token",
        data="name=Jane",
        content_type="application/x-www-form-urlencoded",
        HTTP_ACCEPT="text/html",
    )

    response = error_response(request, code, status)

    assert response.status_code == status
    assert response["Content-Type"].startswith("text/html")
    assert str(status) in response.content.decode()


def test_error_response_no_cors_without_form():
    request = factory.post(
        "/f/some-token",
        data="{}",
        content_type="application/json",
        HTTP_ORIGIN="https://good.example.com",
    )

    response = error_response(request, "not_found", 404)

    assert "Access-Control-Allow-Origin" not in response


def test_error_response_cors_when_origin_allowed():
    form = _form(["https://good.example.com"])
    request = factory.post(
        "/f/some-token",
        data="{}",
        content_type="application/json",
        HTTP_ORIGIN="https://good.example.com",
    )

    response = error_response(request, "invalid_payload", 422, form=form)

    assert response["Access-Control-Allow-Origin"] == "https://good.example.com"
    assert response["Vary"] == "Origin"


def test_error_response_no_cors_when_origin_not_allowed():
    form = _form(["https://good.example.com"])
    request = factory.post(
        "/f/some-token",
        data="{}",
        content_type="application/json",
        HTTP_ORIGIN="https://evil.example.com",
    )

    response = error_response(request, "invalid_payload", 422, form=form)

    assert "Access-Control-Allow-Origin" not in response
