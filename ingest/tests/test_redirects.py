from types import SimpleNamespace

from ingest.redirects import resolve_redirect_url


def _form(allowed_origins=None, redirect_url=None):
    return SimpleNamespace(allowed_origins=allowed_origins or [], redirect_url=redirect_url)


def test_allowed_redirect_is_honored():
    form = _form(allowed_origins=["https://good.example.com"])
    reserved = {"_redirect": "https://good.example.com/thank-you"}

    assert resolve_redirect_url(form, reserved) == "https://good.example.com/thank-you"


def test_disallowed_origin_redirect_falls_back_to_redirect_url():
    form = _form(
        allowed_origins=["https://good.example.com"],
        redirect_url="https://good.example.com/fallback",
    )
    reserved = {"_redirect": "https://evil.example.com/x"}

    assert resolve_redirect_url(form, reserved) == "https://good.example.com/fallback"


def test_empty_allow_list_ignores_redirect():
    form = _form(allowed_origins=[], redirect_url="https://good.example.com/fallback")
    reserved = {"_redirect": "https://good.example.com/x"}

    assert resolve_redirect_url(form, reserved) == "https://good.example.com/fallback"


def test_javascript_scheme_redirect_is_ignored():
    form = _form(
        allowed_origins=["https://good.example.com"],
        redirect_url="https://good.example.com/fallback",
    )
    reserved = {"_redirect": "javascript:alert(1)"}

    assert resolve_redirect_url(form, reserved) == "https://good.example.com/fallback"


def test_malformed_redirect_url_is_ignored():
    form = _form(
        allowed_origins=["https://good.example.com"],
        redirect_url="https://good.example.com/fallback",
    )
    reserved = {"_redirect": "https://[::1"}

    assert resolve_redirect_url(form, reserved) == "https://good.example.com/fallback"


def test_non_string_redirect_is_ignored():
    form = _form(
        allowed_origins=["https://good.example.com"],
        redirect_url="https://good.example.com/fallback",
    )
    reserved = {"_redirect": ["https://good.example.com/x"]}

    assert resolve_redirect_url(form, reserved) == "https://good.example.com/fallback"


def test_falls_back_to_thanks_page_when_nothing_set():
    form = _form(allowed_origins=[], redirect_url=None)

    assert resolve_redirect_url(form, {}) == "/thanks"
