import pytest

from accounts.models import Account, User
from billing.models import UsageEvent
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _login(client):
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    client.login(username="owner@example.com", password="s3cret-pass123")
    return user


def _make_submission(form_obj, **kwargs):
    kwargs.setdefault("payload", {})
    kwargs.setdefault("status", Submission.Status.HAM)
    kwargs.setdefault("original_status", kwargs["status"])
    kwargs.setdefault("source_ip_hash", "a" * 64)
    return Submission.objects.create(form=form_obj, **kwargs)


def _label_url(form_obj, submission):
    return f"/forms/{form_obj.pk}/submissions/{submission.pk}/label"


def test_get_is_rejected(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj)

    response = client.get(_label_url(form_obj, submission))

    assert response.status_code == 405


def test_other_accounts_submission_404s(client):
    _login(client)
    other_account = Account.objects.create(name="Other Co")
    other_form = Form.objects.create(account=other_account, name="Not mine")
    other_submission = _make_submission(other_form)

    response = client.post(_label_url(other_form, other_submission), {"status": "spam"})

    assert response.status_code == 404


def test_submission_from_different_form_of_same_account_404s(client):
    user = _login(client)
    form_a = Form.objects.create(account=user.account, name="Form A")
    form_b = Form.objects.create(account=user.account, name="Form B")
    submission_on_b = _make_submission(form_b)

    response = client.post(
        f"/forms/{form_a.pk}/submissions/{submission_on_b.pk}/label", {"status": "spam"}
    )

    assert response.status_code == 404


def test_flip_ham_to_spam_sets_corrected(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    client.post(_label_url(form_obj, submission), {"status": "spam", "fragment": "status"})

    submission.refresh_from_db()
    assert submission.status == Submission.Status.SPAM
    assert submission.original_status == Submission.Status.HAM
    assert submission.corrected is True
    assert submission.corrected_at is not None


def test_flip_back_to_original_clears_corrected(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    client.post(_label_url(form_obj, submission), {"status": "spam", "fragment": "status"})
    client.post(_label_url(form_obj, submission), {"status": "ham", "fragment": "status"})

    submission.refresh_from_db()
    assert submission.status == Submission.Status.HAM
    assert submission.original_status == Submission.Status.HAM
    assert submission.corrected is False
    assert submission.corrected_at is None


def test_original_status_never_changes_across_flips(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.SPAM)

    client.post(_label_url(form_obj, submission), {"status": "ham", "fragment": "status"})
    client.post(_label_url(form_obj, submission), {"status": "spam", "fragment": "status"})

    submission.refresh_from_db()
    assert submission.original_status == Submission.Status.SPAM


def test_flip_to_same_status_is_a_noop(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    response = client.post(
        _label_url(form_obj, submission), {"status": "ham", "fragment": "status"}
    )

    submission.refresh_from_db()
    assert response.status_code in (200, 302)
    assert submission.corrected is False
    assert submission.corrected_at is None


def test_invalid_status_is_rejected(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj)

    response = client.post(_label_url(form_obj, submission), {"status": "bogus"})

    assert response.status_code == 400
    submission.refresh_from_db()
    assert submission.status == Submission.Status.HAM


def test_never_creates_or_removes_usage_event(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)
    UsageEvent.objects.create(account=user.account, kind="submission", quantity=1)
    count_before = UsageEvent.objects.count()

    client.post(_label_url(form_obj, submission), {"status": "spam"})
    client.post(_label_url(form_obj, submission), {"status": "ham"})

    assert UsageEvent.objects.count() == count_before


def test_never_touches_notification_status(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(
        form_obj,
        status=Submission.Status.HAM,
        notification_status=Submission.NotificationStatus.SENT,
    )

    client.post(_label_url(form_obj, submission), {"status": "spam"})

    submission.refresh_from_db()
    assert submission.notification_status == Submission.NotificationStatus.SENT


def test_htmx_request_returns_status_fragment_not_redirect(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    response = client.post(
        _label_url(form_obj, submission),
        {"status": "spam", "fragment": "status"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="submission-status"' in content
    assert "pill-bad" in content
    assert "Not spam" in content


def test_htmx_row_fragment_visible_under_all_filter(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    response = client.post(
        _label_url(form_obj, submission),
        {"status": "spam", "fragment": "row", "filter": "all"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert "submission-row" in response.content.decode()


def test_htmx_row_fragment_empty_when_filtered_out(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.SPAM)

    response = client.post(
        _label_url(form_obj, submission),
        {"status": "ham", "fragment": "row", "filter": "spam"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "submission-row" not in content
    # the OOB toast is still present even though the row itself collapsed
    assert "toast" in content


def test_htmx_response_includes_toast_with_undo(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    response = client.post(
        _label_url(form_obj, submission),
        {"status": "spam", "fragment": "status"},
        HTTP_HX_REQUEST="true",
    )

    content = response.content.decode()
    assert "Marked as spam." in content
    assert "Undo" in content
    assert 'id="toast-container" hx-swap-oob="beforeend"' in content
    assert '<div class="toast ' in content


def test_non_htmx_redirects_to_next_preserving_filter_and_page(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)
    next_url = f"/forms/{form_obj.pk}/submissions?status=ham&page=2"

    response = client.post(_label_url(form_obj, submission), {"status": "spam", "next": next_url})

    assert response.status_code == 302
    assert response.url == next_url


def test_non_htmx_falls_back_to_submission_list_with_no_next(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    response = client.post(_label_url(form_obj, submission), {"status": "spam"})

    assert response.status_code == 302
    assert response.url == f"/forms/{form_obj.pk}/submissions"


def test_non_htmx_open_redirect_next_is_rejected(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    response = client.post(
        _label_url(form_obj, submission),
        {"status": "spam", "next": "https://evil.example.com/steal"},
    )

    assert response.status_code == 302
    assert response.url == f"/forms/{form_obj.pk}/submissions"


def test_non_htmx_shows_toast_message_on_next_page(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, status=Submission.Status.HAM)

    response = client.post(_label_url(form_obj, submission), {"status": "spam"}, follow=True)

    assert "Marked as spam." in response.content.decode()
