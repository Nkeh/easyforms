import pytest

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
    kwargs.setdefault("source_ip_hash", "a" * 64)
    return Submission.objects.create(form=form_obj, **kwargs)


def _detail_url(form_obj, submission):
    return f"/forms/{form_obj.pk}/submissions/{submission.pk}"


def _delete_url(form_obj, submission):
    return f"/forms/{form_obj.pk}/submissions/{submission.pk}/delete"


def test_shows_every_payload_field(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, payload={"name": "Jane", "message": "Hello there"})

    response = client.get(_detail_url(form_obj, submission))
    content = response.content.decode()

    assert "name" in content
    assert "Jane" in content
    assert "message" in content
    assert "Hello there" in content


def test_script_value_is_escaped_not_executed(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, payload={"name": "<script>alert(1)</script>"})

    response = client.get(_detail_url(form_obj, submission))
    content = response.content.decode()

    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content


def test_url_value_is_not_linkified(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj, payload={"website": "https://example.com/x"})

    response = client.get(_detail_url(form_obj, submission))
    content = response.content.decode()

    assert "https://example.com/x" in content
    assert 'href="https://example.com/x"' not in content


def test_other_accounts_submission_404s(client):
    _login(client)
    other_account = Account.objects.create(name="Other Co")
    other_form = Form.objects.create(account=other_account, name="Not mine")
    other_submission = _make_submission(other_form)

    response = client.get(_detail_url(other_form, other_submission))

    assert response.status_code == 404


def test_submission_from_a_different_form_of_same_account_404s(client):
    user = _login(client)
    form_a = Form.objects.create(account=user.account, name="Form A")
    form_b = Form.objects.create(account=user.account, name="Form B")
    submission_on_b = _make_submission(form_b)

    response = client.get(_detail_url(form_a, submission_on_b))

    assert response.status_code == 404


def test_delete_get_renders_confirm_and_does_not_delete(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    submission = _make_submission(form_obj)

    response = client.get(_delete_url(form_obj, submission))

    assert response.status_code == 200
    assert "Delete this submission?" in response.content.decode()
    assert Submission.objects.filter(pk=submission.pk).exists()


def test_delete_post_removes_only_that_row_and_redirects(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    to_delete = _make_submission(form_obj)
    to_keep = _make_submission(form_obj)

    response = client.post(_delete_url(form_obj, to_delete), follow=True)

    assert response.status_code == 200
    assert not Submission.objects.filter(pk=to_delete.pk).exists()
    assert Submission.objects.filter(pk=to_keep.pk).exists()
    assert "Submission deleted." in response.content.decode()
    assert response.redirect_chain[0][0] == f"/forms/{form_obj.pk}/submissions"
