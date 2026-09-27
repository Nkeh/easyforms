from urllib.parse import urlsplit

from django import forms
from django.core.exceptions import ValidationError

from core.forms import TailwindStyledForm
from forms_app.models import Form


def _normalize_origin(raw_line: str, line_no: int) -> str:
    candidate = raw_line.strip().lower()

    if "*" in candidate:
        raise ValidationError(f"Line {line_no}: '{raw_line}' must not contain a wildcard.")

    parsed = urlsplit(candidate)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValidationError(
            f"Line {line_no}: '{raw_line}' is not a valid origin (expected scheme://host[:port])."
        )

    if parsed.path or parsed.query or parsed.fragment:
        raise ValidationError(
            f"Line {line_no}: '{raw_line}' must not include a path, query, or trailing slash."
        )

    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise ValidationError(
            f"Line {line_no}: '{raw_line}' must use https "
            "(http is only allowed for localhost/127.0.0.1)."
        )

    return f"{parsed.scheme}://{parsed.netloc}"


class FormCreateForm(TailwindStyledForm, forms.ModelForm):
    class Meta:
        model = Form
        fields = ["name"]


class FormEditForm(TailwindStyledForm, forms.ModelForm):
    allowed_origins = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="One origin per line, e.g. https://example.com",
    )

    class Meta:
        model = Form
        fields = ["name", "allowed_origins", "redirect_url", "spam_action"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["allowed_origins"] = "\n".join(self.instance.allowed_origins)

    def clean_allowed_origins(self):
        raw = self.cleaned_data.get("allowed_origins") or ""
        lines = [line for line in raw.splitlines() if line.strip()]

        normalized = []
        seen = set()
        errors = []
        for line_no, line in enumerate(lines, start=1):
            try:
                origin = _normalize_origin(line, line_no)
            except ValidationError as exc:
                errors.extend(exc.messages)
                continue
            if origin not in seen:
                seen.add(origin)
                normalized.append(origin)

        if errors:
            raise ValidationError(errors)

        return normalized

    def clean_redirect_url(self):
        url = self.cleaned_data.get("redirect_url")
        if url and urlsplit(url).scheme not in ("http", "https"):
            raise ValidationError("Redirect URL must start with http:// or https://.")
        return url
