from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.template import loader

from accounts.models import User
from core.forms import TailwindStyledForm
from notifications.email import send_transactional


class SignupForm(TailwindStyledForm, forms.Form):
    email = forms.EmailField(label="Email")
    password = forms.CharField(label="Password", widget=forms.PasswordInput, strip=False)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise ValidationError("This email is already registered.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password, user=User(email=self.data.get("email", "")))
        return password


class EmailAuthenticationForm(TailwindStyledForm, AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )


class StyledSetPasswordForm(TailwindStyledForm, SetPasswordForm):
    pass


class TransactionalPasswordResetForm(TailwindStyledForm, PasswordResetForm):
    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        subject = loader.render_to_string(subject_template_name, context)
        subject = "".join(subject.splitlines()).strip()
        send_transactional(to=to_email, subject=subject, template="password_reset", context=context)
