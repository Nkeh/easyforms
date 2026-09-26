import json
from urllib.parse import urlencode

import pytest
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from ingest.parsing import (
    InvalidPayload,
    PayloadTooLarge,
    UnsupportedMediaType,
    _cap_body,
    parse_body,
)

factory = RequestFactory()


def _json_request(payload):
    return factory.post("/f/some-token", data=json.dumps(payload), content_type="application/json")


def _form_request(data):
    body = urlencode(data, doseq=True)
    return factory.post(
        "/f/some-token", data=body, content_type="application/x-www-form-urlencoded"
    )


def test_json_scalar_and_list_values_are_accepted():
    request = _json_request(
        {
            "name": "Jane",
            "age": 30,
            "score": 4.5,
            "subscribed": True,
            "middle_name": None,
            "interests": ["a", "b", 1, True, None],
        }
    )

    fields, reserved = parse_body(request)

    assert fields["name"] == "Jane"
    assert fields["interests"] == ["a", "b", 1, True, None]
    assert reserved == {}


def test_json_reserved_fields_are_split_out():
    request = _json_request({"name": "Jane", "_honeypot": "", "_ts": 12345, "_redirect": "x"})

    fields, reserved = parse_body(request)

    assert fields == {"name": "Jane"}
    assert reserved == {"_honeypot": "", "_ts": 12345, "_redirect": "x"}


def test_json_nested_object_value_is_rejected():
    request = _json_request({"name": "Jane", "address": {"city": "NYC"}})

    with pytest.raises(InvalidPayload):
        parse_body(request)


def test_json_list_containing_nested_object_is_rejected():
    request = _json_request({"name": "Jane", "tags": [{"a": 1}]})

    with pytest.raises(InvalidPayload):
        parse_body(request)


def test_json_top_level_list_is_rejected():
    request = factory.post(
        "/f/some-token", data=json.dumps([1, 2, 3]), content_type="application/json"
    )

    with pytest.raises(InvalidPayload):
        parse_body(request)


def test_malformed_json_is_rejected():
    request = factory.post("/f/some-token", data="{not json", content_type="application/json")

    with pytest.raises(InvalidPayload):
        parse_body(request)


def test_form_encoded_single_value_is_a_string():
    request = _form_request({"name": "Jane"})

    fields, reserved = parse_body(request)

    assert fields["name"] == "Jane"


def test_form_encoded_multi_value_is_a_list():
    request = _form_request({"interests": ["a", "b", "c"]})

    fields, reserved = parse_body(request)

    assert fields["interests"] == ["a", "b", "c"]


def test_form_encoded_reserved_fields_are_split_out():
    request = _form_request({"name": "Jane", "_honeypot": ""})

    fields, reserved = parse_body(request)

    assert fields == {"name": "Jane"}
    assert reserved == {"_honeypot": ""}


def test_multipart_file_upload_is_rejected():
    request = factory.post(
        "/f/some-token",
        data={"name": "Jane", "attachment": SimpleUploadedFile("a.txt", b"content")},
    )

    with pytest.raises(InvalidPayload):
        parse_body(request)


def test_multipart_without_file_is_accepted():
    request = factory.post("/f/some-token", data={"name": "Jane"})

    fields, reserved = parse_body(request)

    assert fields == {"name": "Jane"}


def test_unsupported_content_type_is_rejected():
    request = factory.post("/f/some-token", data="hello", content_type="text/plain")

    with pytest.raises(UnsupportedMediaType):
        parse_body(request)


def test_empty_payload_after_stripping_reserved_is_rejected():
    request = _json_request({"_honeypot": "", "_ts": 123})

    with pytest.raises(InvalidPayload):
        parse_body(request)


def test_too_many_fields_raises(settings):
    settings.INGEST_MAX_FIELDS = 2
    request = _json_request({"a": "1", "b": "2", "c": "3"})

    with pytest.raises(PayloadTooLarge):
        parse_body(request)


def test_oversize_field_value_raises(settings):
    settings.INGEST_MAX_FIELD_CHARS = 5
    request = _json_request({"name": "toolongvalue"})

    with pytest.raises(PayloadTooLarge):
        parse_body(request)


def test_oversize_list_item_raises(settings):
    settings.INGEST_MAX_FIELD_CHARS = 5
    request = _json_request({"tags": ["ok", "toolongvalue"]})

    with pytest.raises(PayloadTooLarge):
        parse_body(request)


def test_oversize_key_raises(settings):
    settings.INGEST_MAX_KEY_CHARS = 3
    request = _json_request({"toolongkey": "x"})

    with pytest.raises(PayloadTooLarge):
        parse_body(request)


def test_body_exactly_at_limit_is_accepted(settings):
    body = json.dumps({"name": "Jane"}).encode()
    settings.INGEST_MAX_BODY_BYTES = len(body)
    request = factory.post("/f/some-token", data=body, content_type="application/json")

    fields, reserved = parse_body(request)

    assert fields == {"name": "Jane"}


def test_request_data_too_big_is_mapped_to_payload_too_large(monkeypatch):
    def _raise(request):
        raise RequestDataTooBig()

    monkeypatch.setattr("ingest.parsing._parse_multipart_or_form", _raise)
    request = _form_request({"name": "Jane"})

    with pytest.raises(PayloadTooLarge):
        parse_body(request)


def test_too_many_fields_sent_is_mapped_to_payload_too_large(monkeypatch):
    def _raise(request):
        raise TooManyFieldsSent()

    monkeypatch.setattr("ingest.parsing._parse_multipart_or_form", _raise)
    request = _form_request({"name": "Jane"})

    with pytest.raises(PayloadTooLarge):
        parse_body(request)


class _StubRequest:
    """Minimal stand-in for a chunked request with no Content-Length header.

    A real WSGIRequest can't exercise this branch: Django's WSGIRequest fixes
    content_length=0 at construction time when the Content-Length header is
    absent, capping any request.read() at 0 bytes regardless of what
    _cap_body asks for. This defends against a deployment that behaves
    differently (e.g. a different ASGI/WSGI server), not something reachable
    via RequestFactory or the Django test client today.
    """

    def __init__(self, body: bytes):
        self._chunk = body
        self.META = {}

    def read(self, n=-1):
        return self._chunk[:n]


def test_cap_body_raises_when_no_content_length_and_over_limit():
    request = _StubRequest(b"x" * 10)

    with pytest.raises(PayloadTooLarge):
        _cap_body(request, max_bytes=5)


def test_cap_body_accepts_when_no_content_length_and_within_limit():
    request = _StubRequest(b"x" * 5)

    _cap_body(request, max_bytes=5)

    assert request._body == b"x" * 5
