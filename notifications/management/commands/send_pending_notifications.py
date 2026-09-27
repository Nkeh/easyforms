from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from forms_app.models import Submission
from notifications.tasks import enqueue_submission_notification


class Command(BaseCommand):
    help = (
        "Enqueue notification emails for ham submissions still "
        "notification_status=pending, older than 2 minutes and newer than "
        "24 hours (safety net for enqueue failures at ingest time; "
        "scheduling this via cron is Day 13)."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        window_start = now - timedelta(hours=24)
        window_end = now - timedelta(minutes=2)

        submission_ids = Submission.objects.filter(
            status=Submission.Status.HAM,
            notification_status=Submission.NotificationStatus.PENDING,
            created_at__gte=window_start,
            created_at__lte=window_end,
        ).values_list("id", flat=True)

        count = 0
        for submission_id in submission_ids:
            enqueue_submission_notification(submission_id)
            count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Enqueued {count} pending submission notification(s)")
        )
