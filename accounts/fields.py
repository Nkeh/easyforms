from django.db import models


class CITextField(models.TextField):
    """Case-insensitive text, backed by Postgres' citext extension.

    Django's own contrib.postgres.fields.CITextField was removed in 5.x
    (usable only in historical migrations) in favor of collation-based
    case-insensitivity, but CLAUDE.md rule 1 requires the citext extension
    specifically, so this is the same one-line shim Django's field used
    internally.
    """

    def db_type(self, connection):
        return "citext"
