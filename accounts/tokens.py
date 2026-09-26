from django.core import signing

VERIFY_EMAIL_SALT = "accounts.verify-email"
VERIFY_EMAIL_MAX_AGE = 60 * 60 * 24 * 3  # 3 days


def make_verification_token(user) -> str:
    return signing.dumps({"user_id": str(user.id)}, salt=VERIFY_EMAIL_SALT)


def read_verification_token(token: str, max_age: int = VERIFY_EMAIL_MAX_AGE) -> str | None:
    """Return the encoded user_id if `token` is well-formed and unexpired, else None."""
    try:
        payload = signing.loads(token, salt=VERIFY_EMAIL_SALT, max_age=max_age)
    except signing.BadSignature:
        return None
    return payload.get("user_id")
