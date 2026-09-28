from django import forms

_DEFAULT_CLASS = "field-input"
_WIDGET_CLASSES = {
    forms.CheckboxInput: "field-checkbox",
}


class TailwindStyledForm:
    """Mixin: gives every field's widget a Tailwind class by widget type,
    so individual field definitions never need to repeat the class string.
    Must come before the real Form base in the class's bases, e.g.
    `class MyForm(TailwindStyledForm, forms.Form)`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = _DEFAULT_CLASS
            for widget_type, widget_css in _WIDGET_CLASSES.items():
                if isinstance(field.widget, widget_type):
                    css = widget_css
                    break
            field.widget.attrs.setdefault("class", css)
