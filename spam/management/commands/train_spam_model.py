import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from spam.corpus import count_labels, download_email_corpus
from spam.gate import GateFailedError
from spam.training import download_dataset, load_dataset, train_and_save


class Command(BaseCommand):
    help = (
        "Train the spam-detection model on the combined UCI SMS Spam "
        "Collection + email (SpamAssassin, or Enron-Spam as a fallback) "
        "corpus and store a new ModelVersion."
    )

    def add_arguments(self, parser):
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--force", action="store_true", help="Activate even if the form_sanity gate failed"
        )
        parser.add_argument("--min-precision", type=float, default=0.98)
        parser.add_argument("--gate-max-fp", type=int, default=1)
        parser.add_argument("--gate-min-spam-recall", type=float, default=0.70)
        parser.add_argument("--data-dir", default=settings.SPAM_DATASET_DIR)

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"])

        sms_rows = load_dataset(download_dataset(data_dir))
        email_rows, email_source = download_email_corpus(data_dir)
        rows = sms_rows + email_rows

        sources = {
            "sms": count_labels(sms_rows),
            "email": {**count_labels(email_rows), "source": email_source},
        }

        try:
            result = train_and_save(
                rows,
                activate=options["activate"],
                dry_run=options["dry_run"],
                force=options["force"],
                min_precision=options["min_precision"],
                gate_max_fp=options["gate_max_fp"],
                gate_min_spam_recall=options["gate_min_spam_recall"],
                dataset_name=f"uci_sms_spam_collection+{email_source}",
                sources=sources,
            )
        except GateFailedError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(result.metrics, indent=2))

        if result.model_version is None:
            self.stdout.write(self.style.WARNING("Dry run: nothing stored."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Saved ModelVersion {result.version} (active={result.model_version.is_active})"
                )
            )
