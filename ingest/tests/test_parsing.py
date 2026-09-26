import json
from urllib.parse import urlencode

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from ingest.parsing import InvalidPayload, UnsupportedMediaType, parse_body

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
