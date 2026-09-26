import pytest

from spam.models import ModelVersion

pytestmark = pytest.mark.django_db


def test_activate_from_zero_active_rows():
    mv = ModelVersion.objects.create(version="v1", artifact_key="models/v1.pkl", is_active=False)

    ModelVersion.objects.activate(mv)

    mv.refresh_from_db()
    assert mv.is_active is True
    assert ModelVersion.objects.filter(is_active=True).count() == 1


def test_activate_switches_from_one_preexisting_active_row():
    mv1 = ModelVersion.objects.create(version="v1", artifact_key="models/v1.pkl", is_active=True)
    mv2 = ModelVersion.objects.create(version="v2", artifact_key="models/v2.pkl", is_active=False)

    ModelVersion.objects.activate(mv2)

    mv1.refresh_from_db()
    mv2.refresh_from_db()
    assert mv1.is_active is False
    assert mv2.is_active is True
    assert ModelVersion.objects.filter(is_active=True).count() == 1
