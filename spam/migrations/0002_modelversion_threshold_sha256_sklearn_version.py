from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("spam", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="modelversion",
            name="threshold",
            field=models.FloatField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="modelversion",
            name="sha256",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="modelversion",
            name="sklearn_version",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
