from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.urls import reverse

MAX_FIELD_CHARS = 2000
_REPLY_TO_FIELD_NAMES = {"email", "e-mail", "email_address"}


def send_transactional(to: str, subject: str, template: str, context: dict) -> None:
    """Enqueue send_transactional_job onto the "emails" RQ queue.

    Signature unchanged from before Day 10 (accounts/emails.py and
    accounts/forms.py call this exact shape) — only the body changed, from a
    synchronous send to an enqueue, so every call site stays untouched.
    """
    # Imported here, not at module level: notifications.tasks imports this
    # module at import time, so a top-level import here would be circular.
    from notifications.tasks import enqueue_transactional_job

    enqueue_transactional_job(to=to, subject=subject, template=template, context=context)


def _send_now(to: str, subject: str, template: str, context: dict) -> None:
    """The original synchronous body of send_transactional. Private — only
    notifications.tasks.send_transactional_job (running in the worker) may
    call this.
    """
    text_body = render_to_string(f"notifications/email/{template}.txt", context)
    html_body = render_to_string(f"notifications/email/{template}.html", context)
    message = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [to])
    message.attach_alternative(html_body, "text/html")
    message.send()


def send_submission_email(submission, recipients: list[str]) -> None:
    """Build and send the ham-submission notification (FR-5.2). Called only
    from notifications.tasks.send_submission_notification, in the worker.
    `recipients` is passed in rather than recomputed here so the caller's
    verified-users query stays the single source of truth for who counts.
    """
    form = submission.form
    subject = f"New submission: {form.name}"
    if "model_shadow" in submission.spam_signals:
        subject = f"[Possible spam] {subject}"

    context = {
        "form": form,
        "fields": _submission_fields(submission.payload),
        "created_at": submission.created_at,
        "form_url": _submission_url(submission),
    }
    text_body = render_to_string("notifications/email/submission_notification.txt", context)
    html_body = render_to_string("notifications/email/submission_notification.html", context)

    reply_to = _reply_to(submission.payload)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
        reply_to=[reply_to] if reply_to else None,
    )
    message.attach_alternative(html_body, "text/html")
    message.send()


def _truncate_value(value) -> str:
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    else:
        value = str(value)
    if len(value) > MAX_FIELD_CHARS:
        original_length = len(value)
        return f"{value[:MAX_FIELD_CHARS]}\n[truncated, {original_length} characters total]"
    return value


def _submission_fields(payload: dict) -> list[tuple[str, str]]:
    return [(key, _truncate_value(value)) for key, value in payload.items()]


def _reply_to(payload: dict) -> str | None:
    for key, value in payload.items():
        if key.strip().lower() not in _REPLY_TO_FIELD_NAMES:
            continue
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if "\r" in candidate or "\n" in candidate:
            continue  # header-injection attempt — reject before validate_email
        try:
            validate_email(candidate)
        except ValidationError:
            continue
        return candidate
    return None


def _submission_url(submission) -> str:
    return settings.PUBLIC_BASE_URL + reverse(
        "dashboard:submission_detail", args=[submission.form_id, submission.id]
    )
