import hashlib
import logging
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import sklearn
from django.utils import timezone
from joblib import dump
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import StandardScaler

from spam.features import TextStatsExtractor
from spam.models import ModelVersion
from spam.storage import ArtifactStore, get_artifact_store

logger = logging.getLogger("spam")

RANDOM_STATE = 42

DATASET_URL = (
    "https://archive.ics.uci.edu/ml/machine-learning-databases/00228/smsspamcollection.zip"
)
# Computed by downloading DATASET_URL once and hashing the zip; pinned so a
# corrupted or unexpectedly-changed download is rejected rather than trained on.
DATASET_SHA256 = "1587ea43e58e82b14ff1f5425c88e17f8496bfcdb67a583dbff9eefaf9963ce3"

DATASET_MEMBER = "SMSSpamCollection"


class SpamDatasetError(Exception):
    pass


@dataclass
class TrainingResult:
    version: str
    metrics: dict
    threshold: float
    sklearn_version: str
    sha256: str | None
    model_version: ModelVersion | None


def download_dataset(dest_dir: Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted_path = dest_dir / DATASET_MEMBER
    if extracted_path.exists():
        return extracted_path

    zip_path = dest_dir / "sms_spam_collection.zip"
    with urllib.request.urlopen(DATASET_URL) as response, open(zip_path, "wb") as f:
        shutil.copyfileobj(response, f)

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if digest != DATASET_SHA256:
        zip_path.unlink()
        raise SpamDatasetError(
            f"checksum mismatch for {DATASET_URL}: expected {DATASET_SHA256}, got {digest}"
        )

    with zipfile.ZipFile(zip_path) as zf:
        zf.extract(DATASET_MEMBER, dest_dir)
    zip_path.unlink()

    return extracted_path


def load_dataset(path: Path) -> list[tuple[str, str]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            label, _, text = line.partition("\t")
            rows.append((label, text))
    return rows


def build_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "features",
                FeatureUnion(
                    [
                        (
                            "tfidf_word",
                            TfidfVectorizer(analyzer="word", ngram_range=(1, 2)),
                        ),
                        (
                            "tfidf_char",
                            TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)),
                        ),
                        (
                            "numeric",
                            Pipeline(
                                [
                                    ("stats", TextStatsExtractor()),
                                    ("scale", StandardScaler()),
                                ]
                            ),
                        ),
                    ]
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    class_weight="balanced", random_state=RANDOM_STATE, max_iter=1000
                ),
            ),
        ]
    )


def select_threshold(
    y_true, probs, *, min_precision: float, fallback: float = 0.9
) -> tuple[float, bool]:
    precisions, _recalls, thresholds = precision_recall_curve(y_true, probs, pos_label=1)
    candidates = [t for t, p in zip(thresholds, precisions[:-1], strict=True) if p >= min_precision]
    if candidates:
        return float(min(candidates)), False

    logger.warning(
        "no threshold reached min_precision=%.3f; falling back to %.3f", min_precision, fallback
    )
    return fallback, True


def _metrics_at_threshold(y_true, probs, threshold: float) -> dict:
    y_pred = (probs >= threshold).astype(int)
    return {
        "precision": float(precision_score(y_true, y_pred, pos_label=1, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, pos_label=1, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, pos_label=1, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, probs)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist(),
    }


def train_and_save(
    rows: list[tuple[str, str]],
    *,
    activate: bool = False,
    dry_run: bool = False,
    min_precision: float = 0.98,
    dataset_name: str = "uci_sms_spam_collection",
    store: ArtifactStore | None = None,
) -> TrainingResult:
    y = [1 if label == "spam" else 0 for label, _ in rows]
    texts = [text for _, text in rows]

    x_train, x_test, y_train, y_test = train_test_split(
        texts, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )

    pipeline = build_pipeline()
    pipeline.fit(x_train, y_train)

    spam_idx = list(pipeline.named_steps["clf"].classes_).index(1)
    probs = pipeline.predict_proba(x_test)[:, spam_idx]

    threshold, used_fallback = select_threshold(y_test, probs, min_precision=min_precision)

    metrics = {
        **_metrics_at_threshold(y_test, probs, threshold),
        "threshold": threshold,
        "threshold_used_fallback": used_fallback,
        "dataset": dataset_name,
        "n_rows": len(rows),
        "n_train": len(x_train),
        "n_test": len(x_test),
        "class_balance": {"ham": y.count(0), "spam": y.count(1)},
    }

    version = timezone.now().strftime("%Y%m%dT%H%M%SZ")

    if dry_run:
        return TrainingResult(
            version=version,
            metrics=metrics,
            threshold=threshold,
            sklearn_version=sklearn.__version__,
            sha256=None,
            model_version=None,
        )

    store = store or get_artifact_store()
    artifact_key = f"spam/models/{version}.joblib"

    tmp = tempfile.NamedTemporaryFile(suffix=".joblib", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        dump(pipeline, tmp_path)
        sha256 = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        store.put(artifact_key, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    model_version = ModelVersion.objects.create(
        version=version,
        artifact_key=artifact_key,
        metrics=metrics,
        threshold=threshold,
        sha256=sha256,
        sklearn_version=sklearn.__version__,
        is_active=False,
    )

    if activate:
        ModelVersion.objects.activate(model_version)
        model_version.refresh_from_db()

    return TrainingResult(
        version=version,
        metrics=metrics,
        threshold=threshold,
        sklearn_version=sklearn.__version__,
        sha256=sha256,
        model_version=model_version,
    )
