import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from spam.features import extract_text
from spam.loading import load_model_version
from spam.models import ModelVersion

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "form_sanity.json"


class Command(BaseCommand):
    help = (
        "Score spam/fixtures/form_sanity.json through the active (or given) "
        "model and report accuracy. Informational only, not a pass/fail gate."
    )

    def add_arguments(self, parser):
        # Named --model-version, not --version: Django's BaseCommand already
        # reserves a global --version flag (prints the Django version) on
        # every management command's parser.
        parser.add_argument("--model-version", default=None)

    def handle(self, *args, **options):
        if options["model_version"]:
            try:
                mv = ModelVersion.objects.get(version=options["model_version"])
            except ModelVersion.DoesNotExist as exc:
                raise CommandError(
                    f"no ModelVersion with version={options['model_version']!r}"
                ) from exc
        else:
            mv = ModelVersion.objects.filter(is_active=True).first()
            if mv is None:
                raise CommandError("no active ModelVersion and no --model-version given")

        pipeline = load_model_version(mv)
        threshold = mv.threshold if mv.threshold is not None else 0.5
        entries = json.loads(FIXTURE_PATH.read_text())

        false_positives = []
        false_negatives = []
        for i, entry in enumerate(entries):
            text = extract_text(entry["fields"])
            p = float(pipeline.predict_proba([text])[0][1])
            predicted = "spam" if p >= threshold else "ham"
            match = "OK" if predicted == entry["label"] else "MISMATCH"
            self.stdout.write(
                f"[{i}] label={entry['label']} predicted={predicted} p={p:.3f} {match}"
            )
            if entry["label"] == "ham" and predicted == "spam":
                false_positives.append(i)
            elif entry["label"] == "spam" and predicted == "ham":
                false_negatives.append(i)

        self.stdout.write(self.style.SUCCESS(f"model version={mv.version} threshold={threshold}"))
        self.stdout.write(f"false positives (ham predicted spam): {false_positives}")
        self.stdout.write(f"false negatives (spam predicted ham): {false_negatives}")
