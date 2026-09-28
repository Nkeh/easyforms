from django.conf import settings


def _read_built_css():
    css_path = settings.STATICFILES_DIRS[0] / "css" / "app.css"
    assert css_path.exists(), (
        f"{css_path} is missing — run the Tailwind build "
        "(`docker compose build web` or `docker compose run --rm tailwind`) first."
    )
    return css_path.read_text(encoding="utf-8")


def test_built_css_contains_widget_component_classes():
    css = _read_built_css()
    # core/forms.py sets these as widget classes in Python, which Tailwind's
    # content scanner (templates only) never sees — they only survive the
    # build because they're @layer components classes in input.css, not
    # scanned-for utilities. This is the regression the purge bug caused.
    assert ".field-input" in css
    assert ".field-checkbox" in css


def test_built_css_contains_design_tokens():
    css = _read_built_css()
    for utility_class in [
        "bg-ink",
        "bg-paper",
        "bg-signal",
        "text-signal-deep",
        "border-line",
        "bg-danger-soft",
        "text-danger",
    ]:
        assert f".{utility_class}" in css, f"expected {utility_class!r} in built app.css"
