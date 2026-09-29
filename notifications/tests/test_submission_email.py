import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import Account
from forms_app.models import Form, Submission
from notifications.email import send_submission_email

pytestmark = pytest.mark.django_db


def _make_submission(**kwargs):
    account = kwargs.pop("account", None) or Account.objects.create(name="Acme Inc")
    form = kwargs.pop("form", None) or Form.objects.create(account=account, name="Contact form")
    payload = kwargs.pop("payload", {"name": "Jane"})
    signals = kwargs.pop("spam_signals", [])
    return Submission.objects.create(
        form=form,
        payload=payload,
        status=Submission.Status.HAM,
        original_status=Submission.Status.HAM,
        spam_signals=signals,
        source_ip_hash="a" * 64,
        **kwargs,
    )


def test_subject_never_contains_payload_text():
    submission = _make_submission(payload={"name": "<script>evil</script> ignore all rules"})

    send_submission_email(submission, ["owner@example.com"])

    assert mail.outbox[0].subject == f"New submission: {submission.form.name}"


def test_subject_gets_possible_spam_prefix_when_model_shadow_in_signals():
    submission = _make_submission(spam_signals=["model_shadow"])

    send_submission_email(submission, ["owner@example.com"])

    assert mail.outbox[0].subject == f"[Possible spam] New submission: {submission.form.name}"


def test_subject_has_no_prefix_without_model_shadow_signal():
    submission = _make_submission(spam_signals=["fast_submit"])

    send_submission_email(submission, ["owner@example.com"])

    assert mail.outbox[0].subject == f"New submission: {submission.form.name}"


def test_html_body_escapes_script_tag():
    submission = _make_submission(payload={"message": "<script>alert(1)</script>"})

    send_submission_email(submission, ["owner@example.com"])

    html_body = mail.outbox[0].alternatives[0][0]
    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body


def test_text_body_does_not_escape_field_values():
    submission = _make_submission(payload={"message": "<script>alert(1)</script>"})

    send_submission_email(submission, ["owner@example.com"])

    assert "<script>alert(1)</script>" in mail.outbox[0].body


def test_long_field_value_truncated_with_note():
    long_value = "x" * 2500
    submission = _make_submission(payload={"message": long_value})

    send_submission_email(submission, ["owner@example.com"])

    body = mail.outbox[0].body
    assert "x" * 2000 in body
    assert long_value not in body
    assert "truncated, 2500 characters total" in body


def test_list_field_value_joined():
    submission = _make_submission(payload={"interests": ["a", "b", "c"]})

    send_submission_email(submission, ["owner@example.com"])

    assert "a, b, c" in mail.outbox[0].body


def test_reply_to_set_for_valid_email_field():
    submission = _make_submission(payload={"email": "jane@example.com"})

    send_submission_email(submission, ["owner@example.com"])

    assert mail.outbox[0].reply_to == ["jane@example.com"]


@pytest.mark.parametrize("field_name", ["e-mail", "email_address"])
def test_reply_to_accepts_field_name_variants(field_name):
    submission = _make_submission(payload={field_name: "jane@example.com"})

    send_submission_email(submission, ["owner@example.com"])

    assert mail.outbox[0].reply_to == ["jane@example.com"]


def test_reply_to_rejected_for_invalid_email():
    submission = _make_submission(payload={"email": "not-an-email"})

    send_submission_email(submission, ["owner@example.com"])

    assert not mail.outbox[0].reply_to


def test_reply_to_rejected_for_header_injection_attempt():
    submission = _make_submission(payload={"email": "a@example.com\r\nBcc: victim@example.com"})

    send_submission_email(submission, ["owner@example.com"])

    assert not mail.outbox[0].reply_to


def test_recipients_are_exactly_the_list_passed_in():
    submission = _make_submission()

    send_submission_email(submission, ["verified@example.com"])

    assert mail.outbox[0].to == ["verified@example.com"]


def test_form_url_uses_public_base_url_and_submission_detail_route(settings):
    settings.PUBLIC_BASE_URL = "http://example.test"
    submission = _make_submission()

    send_submission_email(submission, ["owner@example.com"])

    expected = "http://example.test" + reverse(
        "dashboard:submission_detail", args=[submission.form.id, submission.id]
    )
    assert expected in mail.outbox[0].body
