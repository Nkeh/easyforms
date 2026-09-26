from django.core.management.base import BaseCommand, CommandError

from spam.gate import evaluate_form_sanity
from spam.loading import load_model_version
from spam.models import ModelVersion


class Command(BaseCommand):
    help = (
        "Score spam/fixtures/form_sanity.json through the active (or given) "
        "model and report accuracy plus the pass/fail gate. Informational "
        "only, not a pass/fail test."
    )

    def add_arguments(self, parser):
        # Named --model-version, not --version: Django's BaseCommand already
        # reserves a global --version flag (prints the Django version) on
        # every management command's parser.
        parser.add_argument("--model-version", default=None)
        parser.add_argument("--gate-max-fp", type=int, default=1)
        parser.add_argument("--gate-min-spam-recall", type=float, default=0.70)

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

        result = evaluate_form_sanity(
            pipeline,
            threshold,
            max_fp=options["gate_max_fp"],
            min_spam_recall=options["gate_min_spam_recall"],
        )

        for row in result["rows"]:
            match = "OK" if row["correct"] else "MISMATCH"
            self.stdout.write(
                f"[{row['index']}] label={row['label']} predicted={row['predicted']} "
                f"p={row['p']:.3f} {match}"
            )

        self.stdout.write(self.style.SUCCESS(f"model version={mv.version} threshold={threshold}"))
        self.stdout.write(f"false positives (ham predicted spam): {result['fp_indices']}")
        self.stdout.write(f"false negatives (spam predicted ham): {result['fn_indices']}")

        style = self.style.SUCCESS if result["passed"] else self.style.WARNING
        self.stdout.write(
            style(
                f"gate: passed={result['passed']} fp_count={result['fp_count']} "
                f"(max {options['gate_max_fp']}) spam_recall={result['spam_recall']:.3f} "
                f"(min {options['gate_min_spam_recall']:.2f})"
            )
        )
