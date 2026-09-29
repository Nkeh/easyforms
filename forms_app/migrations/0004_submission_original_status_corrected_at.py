from django.db import migrations, models


def backfill_original_status(apps, schema_editor):
    Submission = apps.get_model("forms_app", "Submission")
    Submission.objects.update(original_status=models.F("status"))


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("forms_app", "0003_submission_notification_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="submission",
            name="original_status",
            field=models.CharField(
                choices=[("ham", "Ham"), ("spam", "Spam")],
                default="ham",
                max_length=10,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="submission",
            name="corrected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_original_status, noop_reverse),
    ]
