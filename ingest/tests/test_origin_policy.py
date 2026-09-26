from types import SimpleNamespace

from django.http import HttpResponse

from ingest.origin_policy import allowed_origin, apply_cors_headers


def _form(allowed_origins):
    return SimpleNamespace(allowed_origins=allowed_origins)


def test_empty_allow_list_accepts_any_origin():
    form = _form([])

    assert allowed_origin(form, "https://anything.example.com") is True


def test_empty_allow_list_accepts_missing_origin():
    form = _form([])

    assert allowed_origin(form, None) is True


def test_empty_allow_list_accepts_null_origin():
    form = _form([])

    assert allowed_origin(form, "null") is True


def test_non_empty_allow_list_accepts_missing_origin():
    form = _form(["https://good.example.com"])

    assert allowed_origin(form, None) is True


def test_non_empty_allow_list_rejects_null_origin():
    form = _form(["https://good.example.com"])

    assert allowed_origin(form, "null") is False


def test_exact_match_is_accepted():
    form = _form(["https://good.example.com"])

    assert allowed_origin(form, "https://good.example.com") is True


def test_match_is_case_insensitive():
    form = _form(["https://good.example.com"])

    assert allowed_origin(form, "HTTPS://GOOD.example.com") is True


def test_match_ignores_trailing_slash():
    form = _form(["https://good.example.com"])

    assert allowed_origin(form, "https://good.example.com/") is True


def test_non_matching_origin_is_rejected():
    form = _form(["https://good.example.com"])

    assert allowed_origin(form, "https://evil.example.com") is False


def test_apply_cors_headers_echoes_origin_and_sets_vary():
    response = HttpResponse()
    apply_cors_headers(response, "https://good.example.com")

    assert response["Access-Control-Allow-Origin"] == "https://good.example.com"
    assert response["Vary"] == "Origin"
    assert "Access-Control-Allow-Credentials" not in response


def test_apply_cors_headers_noop_without_origin():
    response = HttpResponse()
    apply_cors_headers(response, None)

    assert "Access-Control-Allow-Origin" not in response
    assert "Vary" not in response
