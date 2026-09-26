def _normalize(origin: str) -> str:
    return origin.strip().lower().rstrip("/")


def allowed_origin(form, origin: str | None) -> bool:
    allowed = form.allowed_origins

    if not allowed:
        return True
    if not origin:
        return True
    if origin == "null":
        return False

    normalized_allowed = {_normalize(o) for o in allowed}
    return _normalize(origin) in normalized_allowed


def apply_cors_headers(response, origin: str | None) -> None:
    if origin:
        response["Access-Control-Allow-Origin"] = origin
        response["Vary"] = "Origin"
