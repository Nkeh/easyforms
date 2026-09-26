from urllib.parse import urlsplit

from django.urls import reverse

from ingest.origin_policy import normalize_origin

REDIRECT_KEY = "_redirect"


def resolve_redirect_url(form, reserved: dict) -> str:
    """CLAUDE.md rule 8: _redirect, else form.redirect_url, else hosted /thanks."""
    candidate = reserved.get(REDIRECT_KEY)
    if isinstance(candidate, str) and _is_allowed_redirect(form, candidate):
        return candidate
    if form.redirect_url:
        return form.redirect_url
    return reverse("ingest:thanks")


def _is_allowed_redirect(form, url: str) -> bool:
    if not form.allowed_origins:
        # Opposite of allowed_origin()'s CORS default: an empty allow-list
        # means no redirect target is ever considered allowed (no open redirects).
        return False

    try:
        parsed = urlsplit(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False

    candidate_origin = f"{parsed.scheme}://{parsed.netloc}"
    normalized_allowed = {normalize_origin(o) for o in form.allowed_origins}
    return normalize_origin(candidate_origin) in normalized_allowed
