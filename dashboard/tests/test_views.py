import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import Account, User
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _make_submission(form_obj, status=Submission.Status.HAM):
    return Submission.objects.create(
        form=form_obj, payload={}, status=status, source_ip_hash="a" * 64
    )


def test_dashboard_redirects_anonymous_to_login(client):
    response = client.get("/dashboard")

    assert response.status_code == 302
    assert response.url.startswith("/login")


def test_dashboard_shows_empty_state_with_no_forms(client):
    User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    client.login(username="owner@example.com", password="s3cret-pass123")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Create your first form" in response.content.decode()


def test_dashboard_lists_only_own_accounts_forms(client):
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    Form.objects.create(account=user.account, name="My Form")

    other_account = Account.objects.create(name="Other Co")
    Form.objects.create(account=other_account, name="Someone Else's Form")

    client.login(username="owner@example.com", password="s3cret-pass123")
    response = client.get("/dashboard")
    content = response.content.decode()

    assert "My Form" in content
    assert "Someone Else's Form" not in content


def test_dashboard_shows_usage_and_create_link_below_limit(client):
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    Form.objects.create(account=user.account, name="My Form")

    client.login(username="owner@example.com", password="s3cret-pass123")
    response = client.get("/dashboard")
    content = response.content.decode()

    assert '<span class="tabular-nums">1 / 3</span>' in content
    assert "forms/new" in content


def test_dashboard_hides_create_link_at_limit(client):
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    for i in range(3):
        Form.objects.create(account=user.account, name=f"Form {i}")

    client.login(username="owner@example.com", password="s3cret-pass123")
    response = client.get("/dashboard")
    content = response.content.decode()

    assert '<span class="tabular-nums">3 / 3</span>' in content
    assert "forms/new" not in content
    assert "reached your plan's limit of 3 active forms" in content


def test_dashboard_shows_per_form_ham_spam_and_month_counts(client):
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj)
    _make_submission(form_obj)
    _make_submission(form_obj, status=Submission.Status.SPAM)

    client.login(username="owner@example.com", password="s3cret-pass123")
    response = client.get("/dashboard")

    result = response.context["forms"].get(pk=form_obj.pk)
    assert result.ham_count == 2
    assert result.spam_count == 1
    assert result.ham_this_month == 2


def test_dashboard_home_query_count_does_not_scale_with_form_count(client):
    user = User.objects.create_user(email="owner@example.com", password="s3cret-pass123")
    form_obj = Form.objects.create(account=user.account, name="Form 1")
    for _ in range(3):
        _make_submission(form_obj)

    client.login(username="owner@example.com", password="s3cret-pass123")

    with CaptureQueriesContext(connection) as one_form_queries:
        client.get("/dashboard")

    for i in range(4):
        extra_form = Form.objects.create(account=user.account, name=f"Form extra {i}")
        _make_submission(extra_form)
        _make_submission(extra_form, status=Submission.Status.SPAM)

    with CaptureQueriesContext(connection) as many_forms_queries:
        client.get("/dashboard")

    assert len(many_forms_queries) == len(one_form_queries)
