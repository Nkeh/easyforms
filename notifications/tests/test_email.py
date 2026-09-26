import pytest
from django.core import mail
from django.template import TemplateDoesNotExist

from notifications.email import send_transactional


def test_send_transactional_sends_text_and_html_alternative():
    send_transactional(
        to="owner@example.com",
        subject="Verify your EasyForms email",
        template="verify_email",
        context={"verify_url": "https://example.com/verify/abc", "user": None},
    )

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["owner@example.com"]
    assert message.subject == "Verify your EasyForms email"
    assert "https://example.com/verify/abc" in message.body
    assert len(message.alternatives) == 1
    html_body, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    assert "https://example.com/verify/abc" in html_body


def test_send_transactional_raises_for_missing_template():
    with pytest.raises(TemplateDoesNotExist):
        send_transactional(
            to="owner@example.com",
            subject="Subject",
            template="does_not_exist",
            context={},
        )
