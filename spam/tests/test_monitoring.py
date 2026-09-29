import pytest
from django.test import override_settings
from django.utils import timezone

from accounts.models import Account
from forms_app.models import Form, Submission
from spam.models import ModelVersion
from spam.monitoring import build_report, check_fp_alert

pytestmark = pytest.mark.django_db


def _make_form():
    account = Account.objects.create(name="Acme Inc")
    return Form.objects.create(account=account, name="Contact form")


def _make_submission(form_obj, age_hours=0, **kwargs):
    kwargs.setdefault("payload", {})
    kwargs.setdefault("status", Submission.Status.HAM)
    kwargs.setdefault("original_status", kwargs["status"])
    kwargs.setdefault("source_ip_hash", "a" * 64)
    submission = Submission.objects.create(form=form_obj, **kwargs)
    if age_hours:
        Submission.objects.filter(pk=submission.pk).update(
            created_at=timezone.now() - timezone.timedelta(hours=age_hours)
        )
    return submission


def test_build_report_counts_scored_and_spam_rate():
    form_obj = _make_form()
    _make_submission(form_obj, status=Submission.Status.HAM, spam_score=0.1)
    _make_submission(form_obj, status=Submission.Status.SPAM, spam_score=0.9)
    _make_submission(form_obj, status=Submission.Status.SPAM, spam_score=None)

    report = build_report(days=7)

    assert report.overall.submissions_scored == 3
    assert report.overall.unscored == 1
    assert report.overall.spam_count == 2
    assert report.overall.spam_rate == pytest.approx(2 / 3)


def test_build_report_false_positives_and_negatives():
    form_obj = _make_form()
    # false positive: system said spam, owner corrected to ham
    fp = _make_submission(form_obj, status=Submission.Status.SPAM)
    fp.status = Submission.Status.HAM
    fp.corrected = True
    fp.save(update_fields=["status", "corrected"])
    # false negative: system said ham, owner corrected to spam
    fn = _make_submission(form_obj, status=Submission.Status.HAM)
    fn.status = Submission.Status.SPAM
    fn.corrected = True
    fn.save(update_fields=["status", "corrected"])
    # untouched rows
    _make_submission(form_obj, status=Submission.Status.HAM)
    _make_submission(form_obj, status=Submission.Status.SPAM)

    report = build_report(days=7)

    assert report.overall.false_positives == 1
    assert report.overall.false_negatives == 1
    assert report.overall.original_spam_count == 2
    assert report.overall.original_ham_count == 2


def test_build_report_correction_rate():
    form_obj = _make_form()
    corrected = _make_submission(form_obj, status=Submission.Status.HAM)
    corrected.status = Submission.Status.SPAM
    corrected.corrected = True
    corrected.save(update_fields=["status", "corrected"])
    _make_submission(form_obj, status=Submission.Status.HAM)
    _make_submission(form_obj, status=Submission.Status.HAM)
    _make_submission(form_obj, status=Submission.Status.HAM)

    report = build_report(days=7)

    assert report.overall.corrections == 1
    assert report.overall.labelled_rows == 4
    assert report.overall.correction_rate == pytest.approx(0.25)


def test_build_report_groups_by_model_version_and_heuristics_only():
    form_obj = _make_form()
    version = ModelVersion.objects.create(version="v1", artifact_key="k")
    _make_submission(form_obj, model_version=version, spam_score=0.5)
    _make_submission(form_obj, model_version=version, spam_score=0.6)
    _make_submission(form_obj, model_version=None, spam_score=None)

    report = build_report(days=7)

    labels = {stats.label for stats in report.by_version}
    assert labels == {"v1", "heuristics-only"}
    v1_stats = next(s for s in report.by_version if s.label == "v1")
    assert v1_stats.submissions_scored == 2
    heuristics_stats = next(s for s in report.by_version if s.label == "heuristics-only")
    assert heuristics_stats.submissions_scored == 1


def test_build_report_histogram_buckets_scores():
    form_obj = _make_form()
    _make_submission(form_obj, spam_score=0.05)
    _make_submission(form_obj, spam_score=0.95)
    _make_submission(form_obj, spam_score=0.95)

    report = build_report(days=7)

    assert report.overall.histogram[0] == 1
    assert report.overall.histogram[9] == 2
    assert sum(report.overall.histogram) == 3


def test_build_report_excludes_rows_outside_days_window():
    form_obj = _make_form()
    _make_submission(form_obj, age_hours=24 * 30)

    report = build_report(days=7)

    assert report.overall.submissions_scored == 0


def test_shadow_evidence_splits_confirmed_and_left_ham_after_48h():
    form_obj = _make_form()
    confirmed = _make_submission(
        form_obj, age_hours=72, status=Submission.Status.HAM, spam_signals=["model_shadow"]
    )
    confirmed.status = Submission.Status.SPAM
    confirmed.corrected = True
    confirmed.save(update_fields=["status", "corrected"])
    _make_submission(
        form_obj, age_hours=72, status=Submission.Status.HAM, spam_signals=["model_shadow"]
    )

    report = build_report(days=7)

    assert report.shadow.total == 2
    assert report.shadow.confirmed_spam == 1
    assert report.shadow.left_ham == 1
    assert report.shadow.observed_precision == pytest.approx(0.5)


def test_shadow_evidence_excludes_rows_younger_than_48h():
    form_obj = _make_form()
    _make_submission(
        form_obj, age_hours=1, status=Submission.Status.HAM, spam_signals=["model_shadow"]
    )

    report = build_report(days=7)

    assert report.shadow.total == 0
    assert report.shadow.observed_precision is None


@override_settings(SPAM_FP_ALERT_RATE=0.1, SPAM_ALERT_MIN_ROWS=3)
def test_check_fp_alert_fires_above_threshold_with_enough_rows(caplog):
    form_obj = _make_form()
    for _ in range(3):
        s = _make_submission(form_obj, status=Submission.Status.SPAM)
        s.status = Submission.Status.HAM
        s.corrected = True
        s.save(update_fields=["status", "corrected"])

    with caplog.at_level("WARNING", logger="spam"):
        report = build_report(days=7)

    assert report.fp_alert is True
    assert "false-positive rate" in caplog.text


@override_settings(SPAM_FP_ALERT_RATE=0.1, SPAM_ALERT_MIN_ROWS=50)
def test_check_fp_alert_does_not_fire_below_min_rows():
    form_obj = _make_form()
    for _ in range(3):
        s = _make_submission(form_obj, status=Submission.Status.SPAM)
        s.status = Submission.Status.HAM
        s.corrected = True
        s.save(update_fields=["status", "corrected"])

    report = build_report(days=7)

    assert report.fp_alert is False


@override_settings(SPAM_FP_ALERT_RATE=0.9, SPAM_ALERT_MIN_ROWS=2)
def test_check_fp_alert_does_not_fire_below_rate_threshold():
    form_obj = _make_form()
    s = _make_submission(form_obj, status=Submission.Status.SPAM)
    s.status = Submission.Status.HAM
    s.corrected = True
    s.save(update_fields=["status", "corrected"])
    _make_submission(form_obj, status=Submission.Status.SPAM)

    report = build_report(days=7)

    assert report.fp_alert is False


def test_check_fp_alert_is_a_pure_function_of_overall_stats():
    form_obj = _make_form()
    _make_submission(form_obj, status=Submission.Status.SPAM)
    report = build_report(days=7)

    assert check_fp_alert(report.overall) == report.fp_alert


def test_report_never_includes_payload_content():
    form_obj = _make_form()
    _make_submission(form_obj, payload={"secret": "do-not-leak-me-12345"})

    report = build_report(days=7)

    assert "do-not-leak-me-12345" not in repr(report)
