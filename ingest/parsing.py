import json

from django.conf import settings
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent

RESERVED_PREFIX = "_"
_SCALAR_TYPES = (str, int, float, bool, type(None))


class InvalidPayload(Exception):
    pass


class UnsupportedMediaType(Exception):
    pass


class PayloadTooLarge(Exception):
    pass


def _validate_json_value(value) -> None:
    if isinstance(value, list):
        if not all(isinstance(item, _SCALAR_TYPES) for item in value):
            raise InvalidPayload("invalid_payload")
    elif not isinstance(value, _SCALAR_TYPES):
        raise InvalidPayload("invalid_payload")


def _split_reserved(data: dict) -> tuple[dict, dict]:
    fields = {}
    reserved = {}
    for key, value in data.items():
        if key.startswith(RESERVED_PREFIX):
            reserved[key] = value
        else:
            fields[key] = value
    return fields, reserved


def _parse_json(request) -> dict:
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidPayload("invalid_json") from exc

    if not isinstance(data, dict):
        raise InvalidPayload("invalid_payload")

    for value in data.values():
        _validate_json_value(value)

    return data


def _parse_multipart_or_form(request) -> dict:
    if request.FILES:
        raise InvalidPayload("file_upload_not_supported")

    data = {}
    for key in request.POST:
        values = request.POST.getlist(key)
        data[key] = values[0] if len(values) == 1 else values
    return data


def _cap_body(request, max_bytes: int) -> None:
    """Guarantee request.body/.POST never buffer more than max_bytes+1 bytes,
    even if Content-Length is absent or lying (e.g. a chunked request)."""
    try:
        declared = int(request.META.get("CONTENT_LENGTH"))
    except (TypeError, ValueError):
        declared = None

    if declared is not None and declared <= max_bytes:
        return

    chunk = request.read(max_bytes + 1)
    if len(chunk) > max_bytes:
        raise PayloadTooLarge("body_too_large")
    request._body = chunk


def _check_field_limits(data: dict) -> None:
    if len(data) > settings.INGEST_MAX_FIELDS:
        raise PayloadTooLarge("too_many_fields")

    for key, value in data.items():
        if len(key) > settings.INGEST_MAX_KEY_CHARS:
            raise PayloadTooLarge("key_too_long")

        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, str) and len(item) > settings.INGEST_MAX_FIELD_CHARS:
                raise PayloadTooLarge("field_too_long")


def parse_body(request) -> tuple[dict, dict]:
    content_type = request.content_type

    if content_type not in (
        "application/json",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    ):
        raise UnsupportedMediaType(content_type)

    try:
        _cap_body(request, settings.INGEST_MAX_BODY_BYTES)
        if content_type == "application/json":
            data = _parse_json(request)
        else:
            data = _parse_multipart_or_form(request)
    except (RequestDataTooBig, TooManyFieldsSent) as exc:
        raise PayloadTooLarge("body_too_large") from exc

    _check_field_limits(data)

    fields, reserved = _split_reserved(data)

    if not fields:
        raise InvalidPayload("empty_payload")

    return fields, reserved
