from django.conf import settings


def get_client_ip(request) -> str:
    proxy_count = settings.TRUSTED_PROXY_COUNT

    if proxy_count > 0:
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            parts = [part.strip() for part in forwarded_for.split(",") if part.strip()]
            if len(parts) >= proxy_count:
                return parts[-proxy_count]

    return request.META.get("REMOTE_ADDR", "")
