import hashlib
from pathlib import Path

import sklearn
from django.conf import settings
from joblib import load

from spam.models import ModelVersion
from spam.storage import get_artifact_store


class SpamModelLoadError(Exception):
    pass


def load_model_version(mv: ModelVersion):
    """Load a trained pipeline for mv, verifying integrity before deserializing.

    Not called from app startup yet (Day 9 wires that in) — CLAUDE.md rule 10
    requires boot to survive R2 being unreachable, which this function alone
    does not guarantee.
    """
    cache_path = Path(settings.MODEL_ARTIFACT_DIR) / mv.artifact_key
    if not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        get_artifact_store().get(mv.artifact_key, cache_path)

    digest = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    if mv.sha256 and digest != mv.sha256:
        raise SpamModelLoadError(
            f"artifact {mv.artifact_key} sha256 mismatch: expected {mv.sha256}, got {digest}"
        )

    if mv.sklearn_version:
        expected = tuple(mv.sklearn_version.split(".")[:2])
        actual = tuple(sklearn.__version__.split(".")[:2])
        if expected != actual:
            raise SpamModelLoadError(
                f"artifact {mv.artifact_key} was trained with scikit-learn "
                f"{mv.sklearn_version}, this environment has {sklearn.__version__}"
            )

    return load(cache_path)
