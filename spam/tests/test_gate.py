import json

from spam.gate import evaluate_form_sanity

THRESHOLD = 0.5


class _DictPipeline:
    """Stub pipeline: predict_proba keyed by the exact extract_text() output
    (a single "message" field, so extract_text just returns that string)."""

    def __init__(self, probs_by_text: dict):
        self.probs_by_text = probs_by_text

    def predict_proba(self, texts):
        p = self.probs_by_text[texts[0]]
        return [[1 - p, p]]


def _write_fixture(tmp_path, entries):
    path = tmp_path / "form_sanity.json"
    path.write_text(json.dumps(entries))
    return path


def _entry(label, text):
    return {"label": label, "fields": {"message": text}}


def test_zero_false_positives_passes(tmp_path):
    entries = [
        _entry("ham", "ham0"),
        _entry("ham", "ham1"),
        _entry("ham", "ham2"),
        _entry("spam", "spam0"),
        _entry("spam", "spam1"),
    ]
    probs = {"ham0": 0.1, "ham1": 0.1, "ham2": 0.1, "spam0": 0.9, "spam1": 0.9}
    fixture_path = _write_fixture(tmp_path, entries)

    result = evaluate_form_sanity(
        _DictPipeline(probs), THRESHOLD, max_fp=1, min_spam_recall=0.70, fixture_path=fixture_path
    )

    assert result["fp_count"] == 0
    assert result["spam_recall"] == 1.0
    assert result["passed"] is True


def test_one_false_positive_passes_at_default_max_fp(tmp_path):
    entries = [
        _entry("ham", "ham0"),
        _entry("ham", "ham1"),
        _entry("ham", "ham2"),
        _entry("spam", "spam0"),
        _entry("spam", "spam1"),
    ]
    probs = {"ham0": 0.9, "ham1": 0.1, "ham2": 0.1, "spam0": 0.9, "spam1": 0.9}
    fixture_path = _write_fixture(tmp_path, entries)

    result = evaluate_form_sanity(
        _DictPipeline(probs), THRESHOLD, max_fp=1, min_spam_recall=0.70, fixture_path=fixture_path
    )

    assert result["fp_count"] == 1
    assert result["fp_indices"] == [0]
    assert result["passed"] is True


def test_two_false_positives_fails_at_default_max_fp(tmp_path):
    entries = [
        _entry("ham", "ham0"),
        _entry("ham", "ham1"),
        _entry("ham", "ham2"),
        _entry("spam", "spam0"),
        _entry("spam", "spam1"),
    ]
    probs = {"ham0": 0.9, "ham1": 0.9, "ham2": 0.1, "spam0": 0.9, "spam1": 0.9}
    fixture_path = _write_fixture(tmp_path, entries)

    result = evaluate_form_sanity(
        _DictPipeline(probs), THRESHOLD, max_fp=1, min_spam_recall=0.70, fixture_path=fixture_path
    )

    assert result["fp_count"] == 2
    assert result["passed"] is False


def test_spam_recall_exactly_at_floor_passes(tmp_path):
    spam_entries = [_entry("spam", f"spam{i}") for i in range(10)]
    entries = [_entry("ham", "ham0")] + spam_entries
    probs = {"ham0": 0.1}
    # 7 of 10 caught (p >= threshold), 3 missed -> recall exactly 0.70
    for i in range(10):
        probs[f"spam{i}"] = 0.9 if i < 7 else 0.1
    fixture_path = _write_fixture(tmp_path, entries)

    result = evaluate_form_sanity(
        _DictPipeline(probs), THRESHOLD, max_fp=1, min_spam_recall=0.70, fixture_path=fixture_path
    )

    assert result["spam_recall"] == 0.70
    assert result["passed"] is True


def test_spam_recall_just_below_floor_fails(tmp_path):
    spam_entries = [_entry("spam", f"spam{i}") for i in range(10)]
    entries = [_entry("ham", "ham0")] + spam_entries
    probs = {"ham0": 0.1}
    # 6 of 10 caught -> recall 0.60, below the 0.70 floor
    for i in range(10):
        probs[f"spam{i}"] = 0.9 if i < 6 else 0.1
    fixture_path = _write_fixture(tmp_path, entries)

    result = evaluate_form_sanity(
        _DictPipeline(probs), THRESHOLD, max_fp=1, min_spam_recall=0.70, fixture_path=fixture_path
    )

    assert result["spam_recall"] == 0.60
    assert result["passed"] is False


def test_rows_detail_matches_fixture_length_and_content(tmp_path):
    entries = [_entry("ham", "ham0"), _entry("spam", "spam0")]
    probs = {"ham0": 0.1, "spam0": 0.9}
    fixture_path = _write_fixture(tmp_path, entries)

    result = evaluate_form_sanity(_DictPipeline(probs), THRESHOLD, fixture_path=fixture_path)

    assert len(result["rows"]) == 2
    assert result["rows"][0] == {
        "index": 0,
        "label": "ham",
        "predicted": "ham",
        "p": 0.1,
        "correct": True,
    }
    assert result["rows"][1] == {
        "index": 1,
        "label": "spam",
        "predicted": "spam",
        "p": 0.9,
        "correct": True,
    }
