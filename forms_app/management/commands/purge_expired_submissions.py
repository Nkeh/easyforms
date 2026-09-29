import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from forms_app.models import Form, Submission

logger = logging.getLogger("forms_app")


class Command(BaseCommand):
    help = (
        "Delete submissions past their form's effective retention (NFR-6). "
        "Deletes in batches of --batch-size by primary key, each batch its "
        "own transaction; never touches UsageEvent. Scheduling this via cron "
        "is Day 13."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        now = timezone.now()
        total_deleted = 0

        for form_obj in Form.objects.select_related("account").iterator():
            cutoff = now - timedelta(days=form_obj.effective_retention_days)
            expired_ids = list(
                Submission.objects.filter(form=form_obj, created_at__lt=cutoff)
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            if not expired_ids:
                continue

            for i in range(0, len(expired_ids), batch_size):
                batch_ids = expired_ids[i : i + batch_size]
                if not dry_run:
                    with transaction.atomic():
                        Submission.objects.filter(pk__in=batch_ids).delete()

            total_deleted += len(expired_ids)
            logger.info(
                "purge_expired_submissions form_id=%s deleted=%d dry_run=%s",
                form_obj.id,
                len(expired_ids),
                dry_run,
            )

        verb = "Would delete" if dry_run else "Deleted"
        self.stdout.write(self.style.SUCCESS(f"{verb} {total_deleted} expired submission(s)."))
