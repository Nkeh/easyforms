"""Spam feedback-loop monitoring (SRS section 7, Day 12).

Aggregate-query only: every function here works off Submission.status /
original_status / corrected / spam_score / spam_signals / model_version.
Never reads payload or source_ip_hash (CLAUDE.md rule 4).
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from forms_app.models import Submission
from spam.models import ModelVersion

logger = logging.getLogger("spam")

HISTOGRAM_BUCKETS = 10
SHADOW_MATURITY = timedelta(hours=48)
_SHADOW_SIGNAL = "model_shadow"


@dataclass
class VersionStats:
    label: str
    submissions_scored: int
    unscored: int
    spam_count: int
    spam_rate: float
    histogram: list[int]
    original_spam_count: int
    original_ham_count: int
    false_positives: int
    false_negatives: int
    corrections: int
    labelled_rows: int
    correction_rate: float


@dataclass
class ShadowEvidence:
    total: int
    confirmed_spam: int
    left_ham: int
    observed_precision: float | None


@dataclass
class MonitoringReport:
    days: int
    overall: VersionStats
    by_version: list[VersionStats]
    shadow: ShadowEvidence
    fp_alert: bool


def _histogram(scores) -> list[int]:
    buckets = [0] * HISTOGRAM_BUCKETS
    for score in scores:
        index = min(HISTOGRAM_BUCKETS - 1, max(0, int(score * HISTOGRAM_BUCKETS)))
        buckets[index] += 1
    return buckets


def _version_stats(label, qs) -> VersionStats:
    total = qs.count()
    scores = list(qs.exclude(spam_score=None).values_list("spam_score", flat=True))
    spam_count = qs.filter(status=Submission.Status.SPAM).count()
    original_spam_count = qs.filter(original_status=Submission.Status.SPAM).count()
    original_ham_count = total - original_spam_count
    false_positives = qs.filter(
        original_status=Submission.Status.SPAM, status=Submission.Status.HAM
    ).count()
    false_negatives = qs.filter(
        original_status=Submission.Status.HAM, status=Submission.Status.SPAM
    ).count()
    corrections = qs.filter(corrected=True).count()
    return VersionStats(
        label=label,
        submissions_scored=total,
        unscored=total - len(scores),
        spam_count=spam_count,
        spam_rate=(spam_count / total) if total else 0.0,
        histogram=_histogram(scores),
        original_spam_count=original_spam_count,
        original_ham_count=original_ham_count,
        false_positives=false_positives,
        false_negatives=false_negatives,
        corrections=corrections,
        labelled_rows=total,
        correction_rate=(corrections / total) if total else 0.0,
    )


def check_fp_alert(overall: VersionStats) -> bool:
    """False-positive rate among spam-labelled rows crossing the alert
    threshold means the model needs retraining. Only fires with enough
    spam-labelled rows to trust the rate (SPAM_ALERT_MIN_ROWS)."""
    if overall.original_spam_count < settings.SPAM_ALERT_MIN_ROWS:
        return False

    fp_rate = overall.false_positives / overall.original_spam_count
    if fp_rate <= settings.SPAM_FP_ALERT_RATE:
        return False

    logger.warning(
        "spam monitoring: false-positive rate %.3f exceeds alert threshold %.3f "
        "(%d/%d spam-labelled rows) — model may need retraining",
        fp_rate,
        settings.SPAM_FP_ALERT_RATE,
        overall.false_positives,
        overall.original_spam_count,
    )
    return True


def build_report(days: int = 7) -> MonitoringReport:
    now = timezone.now()
    window_start = now - timedelta(days=days)
    base_qs = Submission.objects.filter(created_at__gte=window_start)

    overall = _version_stats("overall", base_qs)

    version_ids = sorted(
        base_qs.values_list("model_version_id", flat=True).distinct(),
        key=lambda v: (v is None, v),
    )
    by_version = []
    for version_id in version_ids:
        if version_id is None:
            heuristics_qs = base_qs.filter(model_version__isnull=True)
            by_version.append(_version_stats("heuristics-only", heuristics_qs))
        else:
            version = ModelVersion.objects.filter(pk=version_id).first()
            label = version.version if version else str(version_id)
            by_version.append(_version_stats(label, base_qs.filter(model_version_id=version_id)))

    shadow_cutoff = now - SHADOW_MATURITY
    shadow_qs = Submission.objects.filter(
        created_at__gte=window_start,
        created_at__lte=shadow_cutoff,
        spam_signals__contains=[_SHADOW_SIGNAL],
    )
    shadow_total = shadow_qs.count()
    shadow_confirmed = shadow_qs.filter(status=Submission.Status.SPAM).count()
    shadow = ShadowEvidence(
        total=shadow_total,
        confirmed_spam=shadow_confirmed,
        left_ham=shadow_total - shadow_confirmed,
        observed_precision=(shadow_confirmed / shadow_total) if shadow_total else None,
    )

    fp_alert = check_fp_alert(overall)

    return MonitoringReport(
        days=days, overall=overall, by_version=by_version, shadow=shadow, fp_alert=fp_alert
    )
