from core.utils import hash_ip


def test_hash_ip_is_deterministic(settings):
    settings.IP_HASH_SECRET = "test-secret"
    assert hash_ip("1.2.3.4") == hash_ip("1.2.3.4")


def test_hash_ip_differs_by_input(settings):
    settings.IP_HASH_SECRET = "test-secret"
    assert hash_ip("1.2.3.4") != hash_ip("5.6.7.8")


def test_hash_ip_differs_by_secret(settings):
    settings.IP_HASH_SECRET = "secret-a"
    digest_a = hash_ip("1.2.3.4")

    settings.IP_HASH_SECRET = "secret-b"
    digest_b = hash_ip("1.2.3.4")

    assert digest_a != digest_b


def test_hash_ip_is_hex_sha256(settings):
    settings.IP_HASH_SECRET = "test-secret"
    digest = hash_ip("1.2.3.4")

    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex
