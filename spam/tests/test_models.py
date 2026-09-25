import pytest
from django.db import IntegrityError, transaction

from spam.models import ModelVersion

pytestmark = pytest.mark.django_db


def test_second_active_model_version_raises_integrity_error():
    ModelVersion.objects.create(version="v1", artifact_key="models/v1.pkl", is_active=True)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ModelVersion.objects.create(version="v2", artifact_key="models/v2.pkl", is_active=True)


def test_multiple_inactive_model_versions_are_allowed():
    ModelVersion.objects.create(version="v1", artifact_key="models/v1.pkl", is_active=False)
    ModelVersion.objects.create(version="v2", artifact_key="models/v2.pkl", is_active=False)

    assert ModelVersion.objects.count() == 2
