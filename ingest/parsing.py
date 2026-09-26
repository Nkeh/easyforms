import json

RESERVED_PREFIX = "_"
_SCALAR_TYPES = (str, int, float, bool, type(None))


class InvalidPayload(Exception):
    pass


class UnsupportedMediaType(Exception):
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


def parse_body(request) -> tuple[dict, dict]:
    content_type = request.content_type

    if content_type == "application/json":
        data = _parse_json(request)
    elif content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
        data = _parse_multipart_or_form(request)
    else:
        raise UnsupportedMediaType(content_type)

    fields, reserved = _split_reserved(data)

    if not fields:
        raise InvalidPayload("empty_payload")

    return fields, reserved
