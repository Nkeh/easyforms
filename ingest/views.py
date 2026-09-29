import logging
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
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
from notifications.tasks import enqueue_submission_notification
from spam import scoring as spam_scoring

logger = logging.getLogger("ingest")


def _enqueue_notification(form_id, submission_id) -> None:
    try:
        enqueue_submission_notification(submission_id)
    except Exception:
        # Redis down or similar at enqueue time (NFR-3: the response must be
        # unaffected). Leave notification_status=pending — never "failed"
        # here, since the job itself never ran; send_pending_notifications
        # is the safety net that will pick this row up later.
        logger.warning(
            "ingest: failed to enqueue submission notification form_id=%s submission_id=%s",
            form_id,
            submission_id,
            exc_info=True,
        )


def _log(form, response, start_time, verdict=None):
    duration_ms = (time.monotonic() - start_time) * 1000
    if verdict is None:
        logger.info(
            "ingest submission form_id=%s status=%s duration_ms=%.1f",
            form.id if form else None,
            response.status_code,
            duration_ms,
        )
    else:
        logger.info(
            "ingest submission form_id=%s status=%s duration_ms=%.1f "
            "verdict=%s signals=%s score_ms=%.1f",
            form.id if form else None,
            response.status_code,
            duration_ms,
            verdict.status,
            ",".join(verdict.signals) or "-",
            verdict.duration_ms,
        )
    return response


def _build_success_response(request, form, reserved, origin, submission_id):
    if wants_json(request):
        response = JsonResponse({"ok": True, "id": str(submission_id)}, status=200)
    else:
        response = HttpResponse(status=303)
        response["Location"] = resolve_redirect_url(form, reserved)
    apply_cors_headers(response, origin)
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

    verdict = spam_scoring.score(fields, reserved, timezone.now())

    if verdict.status == Submission.Status.HAM:
        submission_limit = check_limit(form.account, "submissions")
        if not submission_limit.allowed:
            response = error_response(request, "quota_exceeded", 429, form=form)
            return _log(form, response, start_time, verdict=verdict)

        has_verified_recipient = form.account.users.filter(is_verified=True).exists()

        with transaction.atomic():
            submission = Submission.objects.create(
                form=form,
                payload=fields,
                status=Submission.Status.HAM,
                original_status=Submission.Status.HAM,
                spam_score=verdict.spam_score,
                spam_signals=verdict.signals,
                model_version=verdict.model_version,
                source_ip_hash=ip_hash,
                notification_status=(
                    Submission.NotificationStatus.PENDING
                    if has_verified_recipient
                    else Submission.NotificationStatus.SKIPPED
                ),
            )
            # check-then-insert can overshoot slightly under concurrency (two
            # requests both pass check_limit before either commits); accepted.
            UsageEvent.objects.create(account=form.account, kind="submission", quantity=1)

            if has_verified_recipient:
                # ids only across the commit boundary — never the ORM objects.
                submission_id = submission.id
                transaction.on_commit(lambda: _enqueue_notification(form.id, submission_id))

        response = _build_success_response(request, form, reserved, origin, submission.id)
        return _log(form, response, start_time, verdict=verdict)

    # Spam: never quota-checked, never metered (CLAUDE.md rule 7), never
    # notified (FR-5.1).
    if form.spam_action == Form.SpamAction.FLAG:
        submission = Submission.objects.create(
            form=form,
            payload=fields,
            status=Submission.Status.SPAM,
            original_status=Submission.Status.SPAM,
            spam_score=verdict.spam_score,
            spam_signals=verdict.signals,
            model_version=verdict.model_version,
            source_ip_hash=ip_hash,
            notification_status=Submission.NotificationStatus.SKIPPED,
        )
        submission_id = submission.id
    else:  # Form.SpamAction.DROP
        submission_id = uuid.uuid4()

    response = _build_success_response(request, form, reserved, origin, submission_id)
    return _log(form, response, start_time, verdict=verdict)
