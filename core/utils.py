import hashlib
import hmac

from django.conf import settings


def hash_ip(ip: str) -> str:
    """HMAC-SHA256 an IP address with IP_HASH_SECRET (CLAUDE.md rule 5: never store raw IPs)."""
    return hmac.new(settings.IP_HASH_SECRET.encode(), ip.encode(), hashlib.sha256).hexdigest()
