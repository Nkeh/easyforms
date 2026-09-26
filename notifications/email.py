from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_transactional(to: str, subject: str, template: str, context: dict) -> None:
    """Render notifications/email/{template}.txt and .html and send synchronously.

    Day 10 wraps this call in an RQ job without changing the signature or any
    call site, so nothing here may depend on RQ.
    """
    text_body = render_to_string(f"notifications/email/{template}.txt", context)
    html_body = render_to_string(f"notifications/email/{template}.html", context)
    message = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [to])
    message.attach_alternative(html_body, "text/html")
    message.send()
