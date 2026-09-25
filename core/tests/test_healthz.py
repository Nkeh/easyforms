import pytest


@pytest.mark.django_db
def test_healthz_returns_200_when_db_and_redis_are_up(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"status": "ok", "db": "ok", "redis": "ok"}
