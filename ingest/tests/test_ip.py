from django.test import RequestFactory

from ingest.ip import get_client_ip

factory = RequestFactory()


def _request(remote_addr="203.0.113.9", xff=None):
    extra = {"REMOTE_ADDR": remote_addr}
    if xff is not None:
        extra["HTTP_X_FORWARDED_FOR"] = xff
    return factory.post("/f/some-token", **extra)


def test_zero_trusted_proxies_uses_remote_addr(settings):
    settings.TRUSTED_PROXY_COUNT = 0
    request = _request(remote_addr="203.0.113.9", xff="9.9.9.9, 203.0.113.5")

    assert get_client_ip(request) == "203.0.113.9"


def test_one_trusted_proxy_uses_last_xff_entry(settings):
    settings.TRUSTED_PROXY_COUNT = 1
    request = _request(xff="203.0.113.5")

    assert get_client_ip(request) == "203.0.113.5"


def test_spoofed_extra_xff_entry_is_ignored(settings):
    settings.TRUSTED_PROXY_COUNT = 1
    # Client prepends a fake IP; only the proxy-appended rightmost entry is trusted.
    request = _request(xff="9.9.9.9, 203.0.113.5")

    assert get_client_ip(request) == "203.0.113.5"


def test_two_trusted_proxies_uses_second_from_right(settings):
    settings.TRUSTED_PROXY_COUNT = 2
    request = _request(xff="198.51.100.1, 203.0.113.5, 203.0.113.6")

    assert get_client_ip(request) == "203.0.113.5"


def test_missing_xff_falls_back_to_remote_addr(settings):
    settings.TRUSTED_PROXY_COUNT = 1
    request = _request(remote_addr="203.0.113.9", xff=None)

    assert get_client_ip(request) == "203.0.113.9"


def test_short_xff_falls_back_to_remote_addr(settings):
    settings.TRUSTED_PROXY_COUNT = 2
    request = _request(remote_addr="203.0.113.9", xff="203.0.113.5")

    assert get_client_ip(request) == "203.0.113.9"
