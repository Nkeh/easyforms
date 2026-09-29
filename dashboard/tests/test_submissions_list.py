import datetime

import pytest
from django.utils import timezone

from accounts.models import Account, User
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


def test_lists_submissions_newest_first(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    oldest = _make_submission(form_obj)
    middle = _make_submission(form_obj)
    newest = _make_submission(form_obj)

    now = timezone.now()
    Submission.objects.filter(pk=oldest.pk).update(created_at=now - datetime.timedelta(days=2))
    Submission.objects.filter(pk=middle.pk).update(created_at=now - datetime.timedelta(days=1))
    Submission.objects.filter(pk=newest.pk).update(created_at=now)

    response = client.get(f"/forms/{form_obj.pk}/submissions")

    ids = [row["submission"].id for row in response.context["rows"]]
    assert ids == [newest.id, middle.id, oldest.id]


def test_paginates_25_per_page(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    for _ in range(30):
        _make_submission(form_obj)

    page1 = client.get(f"/forms/{form_obj.pk}/submissions")
    page2 = client.get(f"/forms/{form_obj.pk}/submissions", {"page": 2})

    assert len(page1.context["page_obj"].object_list) == 25
    assert len(page2.context["page_obj"].object_list) == 5


@pytest.mark.parametrize(
    "status_param,expected_statuses",
    [
        ("all", {"ham", "spam"}),
        ("ham", {"ham"}),
        ("spam", {"spam"}),
    ],
)
def test_status_filter(client, status_param, expected_statuses):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, status=Submission.Status.HAM)
    _make_submission(form_obj, status=Submission.Status.SPAM)

    response = client.get(f"/forms/{form_obj.pk}/submissions", {"status": status_param})

    statuses = {row["submission"].status for row in response.context["rows"]}
    assert statuses == expected_statuses


def test_preview_is_truncated_to_120_chars(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, payload={"message": "x" * 500})

    response = client.get(f"/forms/{form_obj.pk}/submissions")

    preview = response.context["rows"][0]["preview"]
    assert len(preview) == 120


def test_other_accounts_form_404s(client):
    _login(client)
    other_account = Account.objects.create(name="Other Co")
    other_form = Form.objects.create(account=other_account, name="Not mine")

    response = client.get(f"/forms/{other_form.pk}/submissions")

    assert response.status_code == 404


def test_failed_notification_status_is_highlighted(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, notification_status=Submission.NotificationStatus.FAILED)

    response = client.get(f"/forms/{form_obj.pk}/submissions")
    content = response.content.decode()

    assert '<span class="pill pill-bad">&#9888; Failed</span>' in content


def test_possible_spam_filter_only_matches_shadow_flagged_ham(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    shadow = _make_submission(form_obj, spam_signals=["model_shadow"])
    _make_submission(form_obj, status=Submission.Status.HAM)
    _make_submission(form_obj, status=Submission.Status.SPAM, spam_signals=["honeypot"])

    response = client.get(f"/forms/{form_obj.pk}/submissions", {"status": "possible_spam"})

    ids = {row["submission"].id for row in response.context["rows"]}
    assert ids == {shadow.id}


def test_possible_spam_pill_renders_for_shadow_flagged_ham(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, spam_signals=["model_shadow"])

    response = client.get(f"/forms/{form_obj.pk}/submissions")

    assert '<span class="pill pill-warn">Possible spam</span>' in response.content.decode()


def test_possible_spam_pill_absent_for_plain_ham(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, status=Submission.Status.HAM)

    response = client.get(f"/forms/{form_obj.pk}/submissions")

    assert '<span class="pill pill-warn">Possible spam</span>' not in response.content.decode()
