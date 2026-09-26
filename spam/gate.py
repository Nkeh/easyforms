import json
from pathlib import Path

from spam.features import extract_text

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "form_sanity.json"


class GateFailedError(Exception):
    pass


def evaluate_form_sanity(
    pipeline,
    threshold: float,
    *,
    max_fp: int = 1,
    min_spam_recall: float = 0.70,
    fixture_path: Path = FIXTURE_PATH,
) -> dict:
    """Score spam/fixtures/form_sanity.json through pipeline and report a
    pass/fail gate. Single source of truth for the gate's pass/fail
    arithmetic — used by both spam.training.train_and_save (to decide
    whether an --activate is refused) and the eval_spam_model command (to
    report against the same gate), so the logic is never duplicated.
    """
    entries = json.loads(fixture_path.read_text())

    rows = []
    fp_indices = []
    fn_indices = []
    n_ham = 0
    n_spam = 0
    spam_caught = 0

    for i, entry in enumerate(entries):
        label = entry["label"]
        text = extract_text(entry["fields"])
        p = float(pipeline.predict_proba([text])[0][1])
        predicted = "spam" if p >= threshold else "ham"
        correct = predicted == label

        if label == "ham":
            n_ham += 1
            if not correct:
                fp_indices.append(i)
        else:
            n_spam += 1
            if correct:
                spam_caught += 1
            else:
                fn_indices.append(i)

        rows.append(
            {"index": i, "label": label, "predicted": predicted, "p": p, "correct": correct}
        )

    fp_count = len(fp_indices)
    fn_count = len(fn_indices)
    fp_rate = fp_count / n_ham if n_ham else 0.0
    spam_recall = spam_caught / n_spam if n_spam else 0.0
    passed = fp_count <= max_fp and spam_recall >= min_spam_recall

    return {
        "fp_count": fp_count,
        "fn_count": fn_count,
        "fp_rate": fp_rate,
        "spam_recall": spam_recall,
        "passed": passed,
        "fp_indices": fp_indices,
        "fn_indices": fn_indices,
        "n_ham": n_ham,
        "n_spam": n_spam,
        "rows": rows,
    }
