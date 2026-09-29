import csv
import io

import pytest

from accounts.models import User
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


def _csv_url(form_obj):
    return f"/forms/{form_obj.pk}/submissions.csv"


def _content(response):
    return b"".join(response.streaming_content)


def test_header_is_union_of_payload_keys(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, payload={"a": "1"})
    _make_submission(form_obj, payload={"b": "2"})

    response = client.get(_csv_url(form_obj))
    text = _content(response).decode("utf-8-sig")
    header = next(csv.reader(io.StringIO(text)))

    assert header == ["id", "created_at", "status", "spam_score", "a", "b"]


def test_status_filter_respected_in_rows_and_header(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, status=Submission.Status.HAM, payload={"x": "ham-value"})
    _make_submission(form_obj, status=Submission.Status.SPAM, payload={"y": "spam-value"})

    response = client.get(_csv_url(form_obj), {"status": "ham"})
    text = _content(response).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    assert rows[0] == ["id", "created_at", "status", "spam_score", "x"]
    assert len(rows) == 2
    assert "ham" in rows[1]
    assert "ham-value" in rows[1]


def test_possible_spam_filter_matches_only_shadow_flagged_ham(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(
        form_obj, status=Submission.Status.HAM, spam_signals=["model_shadow"], payload={"z": "1"}
    )
    _make_submission(form_obj, status=Submission.Status.HAM, payload={"w": "2"})
    _make_submission(form_obj, status=Submission.Status.SPAM, payload={"v": "3"})

    response = client.get(_csv_url(form_obj), {"status": "possible_spam"})
    text = _content(response).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    assert rows[0] == ["id", "created_at", "status", "spam_score", "z"]
    assert len(rows) == 2


def test_csv_injection_cell_is_prefixed(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, payload={"name": "=cmd|calc"})

    response = client.get(_csv_url(form_obj))
    text = _content(response).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    header = rows[0]
    data_row = rows[1]
    assert data_row[header.index("name")] == "'=cmd|calc"


def test_list_valued_cell_is_joined_with_semicolon(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")
    _make_submission(form_obj, payload={"tags": ["a", "b"]})

    response = client.get(_csv_url(form_obj))
    text = _content(response).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    header = rows[0]
    data_row = rows[1]
    assert data_row[header.index("tags")] == "a; b"


def test_response_is_streaming(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")

    response = client.get(_csv_url(form_obj))

    assert response.streaming is True
    assert response["Content-Type"] == "text/csv; charset=utf-8"


def test_content_starts_with_utf8_bom(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Form")

    response = client.get(_csv_url(form_obj))
    raw = _content(response)

    assert raw.startswith(b"\xef\xbb\xbf")


def test_filename_matches_expected_pattern(client):
    user = _login(client)
    form_obj = Form.objects.create(account=user.account, name="My Cool Form!")

    response = client.get(_csv_url(form_obj))

    disposition = response["Content-Disposition"]
    assert disposition.startswith('attachment; filename="my-cool-form-submissions-')
    assert disposition.endswith('.csv"')
