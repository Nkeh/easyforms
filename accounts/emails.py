from django.urls import reverse

from accounts.tokens import make_verification_token
from notifications.email import send_transactional


def send_verification_email(user, request) -> None:
    token = make_verification_token(user)
    verify_url = request.build_absolute_uri(reverse("accounts:verify", args=[token]))
    send_transactional(
        to=user.email,
        subject="Verify your EasyForms email",
        template="verify_email",
        context={"verify_url": verify_url, "user": user},
    )
