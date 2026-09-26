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


_URL_TOKEN_RE = re.compile(r"(?:https?://|www\.)\S+")
_EMAIL_TOKEN_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_TOKEN_RE = re.compile(r"\+?\d[\d().\-\s]{6,}\d")
_DIGIT_RUN_RE = re.compile(r"\d+")


def normalize_text(text: str) -> str:
    """Pipeline preprocessor (wired into the TF-IDF vectorizers, not called
    by extract_text): lowercase, then replace URLs/emails/phone-like number
    sequences/other digit runs with placeholder tokens, in that order so
    each substitution only sees what's left after the prior one (a URL's
    query string shouldn't read as an email; an email's digits shouldn't be
    eaten by the phone pattern; "555-0134" should become one phonetoken, not
    three numtokens split by punctuation).
    """
    text = text.lower()
    text = _URL_TOKEN_RE.sub(" urltoken ", text)
    text = _EMAIL_TOKEN_RE.sub(" emailtoken ", text)
    text = _PHONE_TOKEN_RE.sub(" phonetoken ", text)
    text = _DIGIT_RUN_RE.sub(" numtoken ", text)
    return re.sub(r"\s+", " ", text).strip()


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
