import pytest

from accounts.models import Account
from billing.models import UsageEvent
from forms_app.models import Form, Submission

pytestmark = pytest.mark.django_db


def _make_form(**kwargs):
    account = kwargs.pop("account", None) or Account.objects.create(name="Acme Inc")
    kwargs.setdefault("name", "Contact form")
    return Form.objects.create(account=account, **kwargs)


def test_ip_rate_limit_returns_429_with_retry_after(client, settings):
    settings.INGEST_RATE_LIMIT_IP_PER_MINUTE = 2
    settings.INGEST_RATE_LIMIT_IP_PER_HOUR = 1000
    form = _make_form()

    for _ in range(2):
        response = client.post(f"/f/{form.token}", {"name": "Jane"})
        assert response.status_code == 200

    response = client.post(f"/f/{form.token}", {"name": "Jane"})

    assert response.status_code == 429
    assert response.json()["error"] == "rate_limited"
    assert int(response["Retry-After"]) > 0


def test_token_rate_limit_returns_429_with_retry_after(client, settings):
    settings.INGEST_RATE_LIMIT_IP_PER_MINUTE = 1000
    settings.INGEST_RATE_LIMIT_IP_PER_HOUR = 1000
    settings.INGEST_RATE_LIMIT_TOKEN_PER_MINUTE = 2
    settings.INGEST_RATE_LIMIT_TOKEN_PER_HOUR = 1000
    form = _make_form()

    for i in range(2):
        response = client.post(f"/f/{form.token}", {"name": "Jane"}, REMOTE_ADDR=f"203.0.113.{i}")
        assert response.status_code == 200

    response = client.post(f"/f/{form.token}", {"name": "Jane"}, REMOTE_ADDR="203.0.113.99")

    assert response.status_code == 429
    assert response.json()["error"] == "rate_limited"
    assert int(response["Retry-After"]) > 0


def test_spoofed_xff_does_not_dodge_ip_limit(client, settings):
    settings.TRUSTED_PROXY_COUNT = 0
    settings.INGEST_RATE_LIMIT_IP_PER_MINUTE = 2
    settings.INGEST_RATE_LIMIT_IP_PER_HOUR = 1000
    form = _make_form()

    for i in range(2):
        response = client.post(
            f"/f/{form.token}", {"name": "Jane"}, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}"
        )
        assert response.status_code == 200

    response = client.post(f"/f/{form.token}", {"name": "Jane"}, HTTP_X_FORWARDED_FOR="10.0.0.99")

    assert response.status_code == 429


def test_preflight_then_post_consumes_one_unit_of_ip_and_token_budget(client, settings):
    settings.INGEST_RATE_LIMIT_IP_PER_MINUTE = 1
    settings.INGEST_RATE_LIMIT_IP_PER_HOUR = 1000
    settings.INGEST_RATE_LIMIT_TOKEN_PER_MINUTE = 1
    settings.INGEST_RATE_LIMIT_TOKEN_PER_HOUR = 1000
    form = _make_form()

    preflight = client.options(f"/f/{form.token}", HTTP_ORIGIN="https://example.com")
    assert preflight.status_code == 204

    response = client.post(f"/f/{form.token}", {"name": "Jane"}, HTTP_ORIGIN="https://example.com")

    assert response.status_code == 200


def test_many_preflights_do_not_block_a_subsequent_post(client, settings):
    settings.INGEST_RATE_LIMIT_IP_PER_MINUTE = 1
    settings.INGEST_RATE_LIMIT_IP_PER_HOUR = 1000
    settings.INGEST_RATE_LIMIT_TOKEN_PER_MINUTE = 1
    settings.INGEST_RATE_LIMIT_TOKEN_PER_HOUR = 1000
    form = _make_form()

    for _ in range(20):
        preflight = client.options(f"/f/{form.token}", HTTP_ORIGIN="https://example.com")
        assert preflight.status_code == 204

    response = client.post(f"/f/{form.token}", {"name": "Jane"}, HTTP_ORIGIN="https://example.com")

    assert response.status_code == 200


def test_quota_accepts_250th_ham_and_rejects_251st(client):
    form = _make_form()

    for _ in range(249):
        UsageEvent.objects.create(account=form.account, kind="submission", quantity=1)

    accepted = client.post(f"/f/{form.token}", {"name": "Jane"})
    assert accepted.status_code == 200
    assert Submission.objects.count() == 1

    rejected = client.post(f"/f/{form.token}", {"name": "Jane"})
    assert rejected.status_code == 429
    assert rejected.json()["error"] == "quota_exceeded"
    assert Submission.objects.count() == 1


def test_usage_event_created_alongside_submission(client):
    form = _make_form()

    client.post(f"/f/{form.token}", {"name": "Jane"})

    submission = Submission.objects.get()
    assert UsageEvent.objects.filter(account=form.account, kind="submission").count() == 1
    assert submission.form == form


def test_submission_rolled_back_if_usage_event_creation_fails(client, monkeypatch):
    form = _make_form()

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(UsageEvent.objects, "create", _raise)

    with pytest.raises(RuntimeError):
        client.post(f"/f/{form.token}", {"name": "Jane"})

    assert Submission.objects.count() == 0
