from django.conf import settings

from core.ratelimit import RateResult, combine, hit


def check_ip_limit(ip_hash: str) -> RateResult:
    return combine(
        hit("ingest_ip_min", ip_hash, settings.INGEST_RATE_LIMIT_IP_PER_MINUTE, 60),
        hit("ingest_ip_hour", ip_hash, settings.INGEST_RATE_LIMIT_IP_PER_HOUR, 3600),
    )


def check_token_limit(token: str) -> RateResult:
    return combine(
        hit("ingest_token_min", token, settings.INGEST_RATE_LIMIT_TOKEN_PER_MINUTE, 60),
        hit("ingest_token_hour", token, settings.INGEST_RATE_LIMIT_TOKEN_PER_HOUR, 3600),
    )
