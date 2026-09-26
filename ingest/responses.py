from django.http import JsonResponse
from django.shortcuts import render

from ingest.origin_policy import allowed_origin, apply_cors_headers

_MESSAGES = {
    "origin_not_allowed": "This origin is not allowed to submit to this form.",
    "not_found": "This form does not exist or is no longer accepting submissions.",
    "method_not_allowed": "This endpoint only accepts POST requests.",
    "payload_too_large": "The submission is too large.",
    "unsupported_media_type": (
        "Unsupported content type. Use application/json, "
        "application/x-www-form-urlencoded, or multipart/form-data."
    ),
    "invalid_payload": "The submitted data could not be processed.",
    "rate_limited": "Too many requests. Please slow down.",
    "quota_exceeded": "This form is not accepting new submissions right now.",
}


def wants_json(request) -> bool:
    if request.content_type == "application/json":
        return True
    accept = request.headers.get("Accept", "")
    return "text/html" not in accept


def error_response(request, code: str, status: int, *, form=None):
    message = _MESSAGES[code]

    if wants_json(request):
        response = JsonResponse({"ok": False, "error": code, "message": message}, status=status)
    else:
        response = render(
            request,
            "ingest/error.html",
            {"error": code, "message": message, "status": status},
            status=status,
        )

    if form is not None:
        origin = request.headers.get("Origin")
        if allowed_origin(form, origin):
            apply_cors_headers(response, origin)

    return response
