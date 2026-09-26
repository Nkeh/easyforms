import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from spam.training import download_dataset, load_dataset, train_and_save


class Command(BaseCommand):
    help = (
        "Train the spam-detection model on the UCI SMS Spam Collection corpus "
        "and store a new ModelVersion."
    )

    def add_arguments(self, parser):
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--min-precision", type=float, default=0.98)
        parser.add_argument("--data-dir", default=settings.SPAM_DATASET_DIR)

    def handle(self, *args, **options):
        dataset_path = download_dataset(Path(options["data_dir"]))
        rows = load_dataset(dataset_path)

        result = train_and_save(
            rows,
            activate=options["activate"],
            dry_run=options["dry_run"],
            min_precision=options["min_precision"],
        )

        self.stdout.write(json.dumps(result.metrics, indent=2))

        if result.model_version is None:
            self.stdout.write(self.style.WARNING("Dry run: nothing stored."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Saved ModelVersion {result.version} (active={result.model_version.is_active})"
                )
            )
