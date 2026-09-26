import logging
import threading
import time
from dataclasses import dataclass

from django.conf import settings

from spam.features import extract_text
from spam.loading import load_model_version
from spam.models import ModelVersion

logger = logging.getLogger("spam")


@dataclass
class Verdict:
    # "ham"/"spam" — matches forms_app.models.Submission.Status values by
    # convention; this module doesn't import forms_app to avoid inverting the
    # existing one-way dependency (forms_app -> spam, never the reverse).
    status: str
    spam_score: float | None
    model_version: ModelVersion | None
    signals: list[str]
    duration_ms: float


def _parse_ts(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _resolve_threshold(model_version: ModelVersion) -> float:
    return model_version.threshold if model_version.threshold is not None else 0.5


class Scorer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pipeline = None
        self._model_version: ModelVersion | None = None
        self._last_checked: float | None = None
        self._failure_logged = False

    def warm(self) -> None:
        self._refresh()

    def score(self, fields: dict, reserved: dict, now) -> Verdict:
        start = time.monotonic()

        honeypot = reserved.get("_honeypot")
        if isinstance(honeypot, str) and honeypot.strip():
            return Verdict("spam", None, None, ["honeypot"], self._elapsed_ms(start))

        self._refresh()
        # Snapshot once; never re-read self._pipeline/self._model_version below,
        # so a concurrent refresh mid-call can't produce an inconsistent Verdict.
        pipeline = self._pipeline
        model_version = self._model_version

        signals: list[str] = []
        effective_threshold = _resolve_threshold(model_version) if model_version else None

        ts_ms = _parse_ts(reserved.get("_ts"))
        if ts_ms is not None:
            elapsed_seconds = now.timestamp() - (ts_ms / 1000.0)
            fast = (
                elapsed_seconds < settings.SPAM_MIN_SUBMIT_SECONDS
                if elapsed_seconds >= 0
                else elapsed_seconds < -60
            )
            if fast:
                signals.append("fast_submit")
                if model_version is not None:
                    effective_threshold = max(
                        _resolve_threshold(model_version) - settings.SPAM_FAST_SUBMIT_MARGIN,
                        0.05,
                    )

        if pipeline is None:
            return Verdict("ham", None, None, signals, self._elapsed_ms(start))

        text = extract_text(fields)
        p = float(pipeline.predict_proba([text])[0][1])
        if p >= effective_threshold:
            signals.append("model")
            status = "spam"
        else:
            status = "ham"
        return Verdict(status, p, model_version, signals, self._elapsed_ms(start))

    def _elapsed_ms(self, start: float) -> float:
        return (time.monotonic() - start) * 1000

    def _refresh(self) -> None:
        refresh_seconds = settings.SPAM_MODEL_REFRESH_SECONDS
        now_mono = time.monotonic()
        if self._last_checked is not None and (now_mono - self._last_checked) < refresh_seconds:
            return
        with self._lock:
            now_mono = time.monotonic()
            if self._last_checked is not None and (now_mono - self._last_checked) < refresh_seconds:
                return
            self._last_checked = now_mono
            self._do_refresh_locked()

    def _do_refresh_locked(self) -> None:
        """Called with self._lock held. Never raises."""
        try:
            active_id = (
                ModelVersion.objects.filter(is_active=True).values_list("id", flat=True).first()
            )
            if active_id is None:
                self._pipeline = None
                self._model_version = None
                self._note_failure("no active ModelVersion")
                return
            if self._model_version is not None and self._model_version.id == active_id:
                return  # already serving the current active version
            mv = ModelVersion.objects.get(id=active_id)
            pipeline = load_model_version(mv)
        except Exception as exc:
            # Broad on purpose: a cold R2 fetch failure surfaces as a raw
            # boto3/network exception, not spam.loading.SpamModelLoadError
            # (which only covers sha256/sklearn-version mismatches on an
            # already-downloaded file) — this must never propagate (warm()
            # calls this at worker boot; CLAUDE.md rule 10).
            if self._pipeline is None:
                # never had a good model — heuristics-only
                self._model_version = None
                self._note_failure(f"no usable model available: {exc}")
            else:
                # already serving a good version — keep it, don't blank the
                # fleet over one bad rollout
                self._note_failure(
                    f"reload of {active_id} failed, continuing to serve "
                    f"{self._model_version.id}: {exc}",
                    level=logging.WARNING,
                )
            return

        self._pipeline = pipeline
        self._model_version = mv
        self._failure_logged = False

    def _note_failure(self, reason: str, level: int = logging.ERROR) -> None:
        if not self._failure_logged:
            logger.log(level, "spam scorer: %s", reason)
            self._failure_logged = True


_default_scorer = Scorer()


def warm() -> None:
    _default_scorer.warm()


def score(fields: dict, reserved: dict, now) -> Verdict:
    return _default_scorer.score(fields, reserved, now)
