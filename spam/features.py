import math
import re

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin

from ingest.parsing import RESERVED_PREFIX

_URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)

# Column order produced by TextStatsExtractor.transform — fixed, since
# StandardScaler and tests both depend on these positions.
FEATURE_NAMES = ("link_count", "has_url", "uppercase_ratio", "log_length", "digit_ratio")


def extract_text(payload: dict) -> str:
    """Join a submission payload's string content into one text blob.

    Single source of truth for train/serve input (SRS section 7): the same
    function turns both corpus rows and live payloads into the string the
    TF-IDF/feature pipeline consumes. Keys are visited in sorted order so the
    result is stable regardless of the payload's original (client-supplied,
    unordered) key order; reserved keys (leading underscore) are never
    included even though ingest.parsing already strips them before storage.
    """
    parts = []
    for key in sorted(payload):
        if key.startswith(RESERVED_PREFIX):
            continue
        value = payload[key]
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(item for item in value if isinstance(item, str))
    return " ".join(parts)


def _link_count(text: str) -> int:
    return len(_URL_RE.findall(text))


def _has_url(text: str) -> float:
    return 1.0 if _link_count(text) > 0 else 0.0


def _uppercase_ratio(text: str) -> float:
    alpha_count = sum(c.isalpha() for c in text)
    upper_count = sum(c.isupper() for c in text)
    return upper_count / (alpha_count or 1)


def _digit_ratio(text: str) -> float:
    digit_count = sum(c.isdigit() for c in text)
    return digit_count / (len(text) or 1)


def _log_length(text: str) -> float:
    return math.log1p(len(text))


class TextStatsExtractor(BaseEstimator, TransformerMixin):
    """Engineered numeric features computed directly from submission text.

    Operates on the same text strings the TF-IDF vectorizers consume, so it
    plugs into the training FeatureUnion alongside them with no separate
    input type.
    """

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        rows = [
            [
                _link_count(text),
                _has_url(text),
                _uppercase_ratio(text),
                _log_length(text),
                _digit_ratio(text),
            ]
            for text in X
        ]
        return np.asarray(rows, dtype=float)
