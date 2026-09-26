from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("forms_app", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="submission",
            name="spam_signals",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
