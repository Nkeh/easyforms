import logging
import time

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from billing.limits import check_limit
from billing.models import UsageEvent
from core.utils import hash_ip
from forms_app.models import Form, Submission
from ingest.ip import get_client_ip
from ingest.origin_policy import allowed_origin, apply_cors_headers
from ingest.parsing import InvalidPayload, PayloadTooLarge, UnsupportedMediaType, parse_body
from ingest.rate_limit import check_ip_limit, check_token_limit
from ingest.redirects import resolve_redirect_url
from ingest.responses import error_response, wants_json

logger = logging.getLogger("ingest")


def _log(form, response, start_time):
    logger.info(
        "ingest submission form_id=%s status=%s duration_ms=%.1f",
        form.id if form else None,
        response.status_code,
        (time.monotonic() - start_time) * 1000,
    )
    return response


def thanks(request):
    return render(request, "ingest/thanks.html")


@csrf_exempt
def submit(request, token):
    start_time = time.monotonic()

    if request.method not in ("POST", "OPTIONS"):
        response = error_response(request, "method_not_allowed", 405, form=None)
        response["Allow"] = "POST, OPTIONS"
        return _log(None, response, start_time)

    if request.method == "POST":
        content_length = request.META.get("CONTENT_LENGTH")
        if content_length is not None:
            try:
                over_limit = int(content_length) > settings.INGEST_MAX_BODY_BYTES
            except ValueError:
                over_limit = False
            if over_limit:
                response = error_response(request, "payload_too_large", 413, form=None)
                return _log(None, response, start_time)

    ip_hash = hash_ip(get_client_ip(request))
    if request.method == "POST":
        ip_limit = check_ip_limit(ip_hash)
        if not ip_limit.allowed:
            response = error_response(request, "rate_limited", 429, form=None)
            response["Retry-After"] = str(ip_limit.retry_after)
            return _log(None, response, start_time)

    form = Form.objects.filter(token=token, is_active=True).first()
    if form is None:
        response = error_response(request, "not_found", 404, form=None)
        return _log(None, response, start_time)

    if request.method == "POST":
        token_limit = check_token_limit(form.token)
        if not token_limit.allowed:
            response = error_response(request, "rate_limited", 429, form=form)
            response["Retry-After"] = str(token_limit.retry_after)
            return _log(form, response, start_time)

    origin = request.headers.get("Origin")
    if not allowed_origin(form, origin):
        response = error_response(request, "origin_not_allowed", 403, form=form)
        return _log(form, response, start_time)

    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        apply_cors_headers(response, origin)
        response["Access-Control-Allow-Methods"] = "POST"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        response["Access-Control-Max-Age"] = "86400"
        return _log(form, response, start_time)

    try:
        fields, reserved = parse_body(request)
    except UnsupportedMediaType:
        response = error_response(request, "unsupported_media_type", 415, form=form)
        return _log(form, response, start_time)
    except PayloadTooLarge:
        response = error_response(request, "payload_too_large", 413, form=form)
        return _log(form, response, start_time)
    except InvalidPayload:
        response = error_response(request, "invalid_payload", 422, form=form)
        return _log(form, response, start_time)

    # Day 9 will insert spam scoring here and only meter/limit-check ham
    # submissions (CLAUDE.md rule 7); every submission is ham until then.
    submission_limit = check_limit(form.account, "submissions")
    if not submission_limit.allowed:
        response = error_response(request, "quota_exceeded", 429, form=form)
        return _log(form, response, start_time)

    with transaction.atomic():
        submission = Submission.objects.create(
            form=form,
            payload=fields,
            status=Submission.Status.HAM,
            spam_score=None,
            model_version=None,
            source_ip_hash=ip_hash,
        )
        # check-then-insert can overshoot slightly under concurrency (two
        # requests both pass check_limit before either commits); accepted.
        UsageEvent.objects.create(account=form.account, kind="submission", quantity=1)

    if wants_json(request):
        response = JsonResponse({"ok": True, "id": str(submission.id)}, status=200)
    else:
        response = HttpResponse(status=303)
        response["Location"] = resolve_redirect_url(form, reserved)

    apply_cors_headers(response, origin)
    return _log(form, response, start_time)
