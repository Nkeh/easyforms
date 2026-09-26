import logging
import time

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.utils import hash_ip
from forms_app.models import Form, Submission
from ingest.ip import get_client_ip
from ingest.origin_policy import allowed_origin, apply_cors_headers
from ingest.parsing import InvalidPayload, UnsupportedMediaType, parse_body

logger = logging.getLogger("ingest")


def _log(form, response, start_time):
    logger.info(
        "ingest submission form_id=%s status=%s duration_ms=%.1f",
        form.id if form else None,
        response.status_code,
        (time.monotonic() - start_time) * 1000,
    )
    return response


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def submit(request, token):
    start_time = time.monotonic()

    form = Form.objects.filter(token=token, is_active=True).first()
    if form is None:
        response = JsonResponse({"ok": False, "error": "not_found"}, status=404)
        return _log(None, response, start_time)

    origin = request.headers.get("Origin")
    if not allowed_origin(form, origin):
        response = JsonResponse({"ok": False, "error": "origin_not_allowed"}, status=403)
        return _log(form, response, start_time)

    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        apply_cors_headers(response, origin)
        response["Access-Control-Allow-Methods"] = "POST"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        response["Access-Control-Max-Age"] = "86400"
        return _log(form, response, start_time)

    try:
        fields, _reserved = parse_body(request)
    except UnsupportedMediaType:
        response = JsonResponse({"ok": False, "error": "unsupported_media_type"}, status=415)
        apply_cors_headers(response, origin)
        return _log(form, response, start_time)
    except InvalidPayload:
        response = JsonResponse({"ok": False, "error": "invalid_payload"}, status=422)
        apply_cors_headers(response, origin)
        return _log(form, response, start_time)

    submission = Submission.objects.create(
        form=form,
        payload=fields,
        status=Submission.Status.HAM,
        spam_score=None,
        model_version=None,
        source_ip_hash=hash_ip(get_client_ip(request)),
    )

    response = JsonResponse({"ok": True, "id": str(submission.id)}, status=200)
    apply_cors_headers(response, origin)
    return _log(form, response, start_time)
