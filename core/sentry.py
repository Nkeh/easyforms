"""Sentry `before_send` hook (NFR-10). Pure function, no Django imports, so
it's safe to import from settings at process-boot time (before django.setup()
has run) with no app-registry ordering risk.

Scrubs anything that could carry a submission payload or other sensitive
request data out of an event before it leaves the process (CLAUDE.md rule 4:
never log submission payloads). `send_default_pii=False` at init already
keeps Sentry's own automatic PII capture off; this covers what the Django
integration still attaches by default (request body/cookies/query string)
plus a defensive sweep for any `extra` value a future log call might pass
under a `payload`-shaped key, even though no call site does that today.
"""

_SENSITIVE_HEADER_NAMES = {"cookie", "authorization"}


def before_send(event, hint):
    request = event.get("request")
    if request:
        request.pop("data", None)
        request.pop("query_string", None)
        request.pop("cookies", None)
        headers = request.get("headers")
        if headers:
            for name in list(headers):
                if name.lower() in _SENSITIVE_HEADER_NAMES:
                    headers.pop(name, None)

    extra = event.get("extra")
    if extra:
        event["extra"] = _scrub_payload_keys(extra)

    return event


def _scrub_payload_keys(value):
    if isinstance(value, dict):
        return {
            key: "[scrubbed]" if key.lower() == "payload" else _scrub_payload_keys(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_scrub_payload_keys(item) for item in value]
    return value
