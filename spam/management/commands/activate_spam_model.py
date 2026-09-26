from django.core.management.base import BaseCommand, CommandError

from spam.models import ModelVersion


class Command(BaseCommand):
    help = "Activate an existing ModelVersion by its version tag, deactivating all others."

    def add_arguments(self, parser):
        parser.add_argument("version")

    def handle(self, *args, **options):
        try:
            mv = ModelVersion.objects.get(version=options["version"])
        except ModelVersion.DoesNotExist as exc:
            raise CommandError(f"no ModelVersion with version={options['version']!r}") from exc

        ModelVersion.objects.activate(mv)
        self.stdout.write(self.style.SUCCESS(f"Activated ModelVersion {mv.version}"))
