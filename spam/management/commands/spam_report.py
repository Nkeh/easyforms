from django.core.management.base import BaseCommand

from spam.monitoring import build_report


class Command(BaseCommand):
    help = (
        "Print spam-scoring and feedback-loop monitoring numbers (SRS section "
        "7): score distribution, spam rate, owner-correction rate, and shadow "
        "evidence, per model version and overall. Scheduling this via cron is "
        "Day 13."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)

    def _write_version(self, stats):
        self.stdout.write(f"  submissions scored: {stats.submissions_scored}")
        self.stdout.write(f"  unscored (heuristics only): {stats.unscored}")
        self.stdout.write(f"  spam rate: {stats.spam_rate:.3f} ({stats.spam_count} spam)")
        self.stdout.write(f"  score histogram (10 buckets, 0.0-1.0): {stats.histogram}")
        self.stdout.write(
            f"  false positives (spam -> ham): {stats.false_positives}"
            f" / {stats.original_spam_count} spam-labelled"
        )
        self.stdout.write(
            f"  false negatives (ham -> spam): {stats.false_negatives}"
            f" / {stats.original_ham_count} ham-labelled"
        )
        self.stdout.write(
            f"  corrections: {stats.corrections} / {stats.labelled_rows} "
            f"(rate={stats.correction_rate:.3f})"
        )

    def handle(self, *args, **options):
        report = build_report(days=options["days"])

        self.stdout.write(self.style.SUCCESS(f"Spam report — last {report.days} day(s)"))
        self.stdout.write("")
        self.stdout.write("Overall:")
        self._write_version(report.overall)

        for stats in report.by_version:
            self.stdout.write("")
            self.stdout.write(f"Model version: {stats.label}")
            self._write_version(stats)

        self.stdout.write("")
        self.stdout.write("Shadow evidence (model_shadow rows older than 48h):")
        if report.shadow.total == 0:
            self.stdout.write("  no mature shadow rows in this window")
        else:
            precision = report.shadow.observed_precision
            self.stdout.write(
                f"  {report.shadow.confirmed_spam} confirmed spam, "
                f"{report.shadow.left_ham} left as ham, "
                f"out of {report.shadow.total} (observed precision={precision:.3f})"
            )

        self.stdout.write("")
        if report.fp_alert:
            self.stdout.write(
                self.style.WARNING(
                    "ALERT: false-positive rate among spam-labelled rows exceeds threshold "
                    "— see logs"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("No alert threshold crossed."))
