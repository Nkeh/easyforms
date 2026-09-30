from core.sentry import before_send


def _event():
    return {
        "request": {
            "url": "https://example.test/f/abc123",
            "data": {"name": "Jane", "message": "buy cheap watches"},
            "query_string": "utm_source=evil",
            "cookies": {"sessionid": "secret"},
            "headers": {
                "Cookie": "sessionid=secret",
                "Authorization": "Bearer secret",
                "User-Agent": "pytest",
            },
        },
        "extra": {
            "payload": {"name": "Jane", "message": "buy cheap watches"},
            "form_id": "abc-123",
            "nested": {"payload": {"email": "jane@example.test"}},
        },
    }


def test_scrubs_request_body_cookies_and_query_string():
    event = before_send(_event(), {})

    request = event["request"]
    assert "data" not in request
    assert "query_string" not in request
    assert "cookies" not in request
    assert request["url"] == "https://example.test/f/abc123"


def test_scrubs_sensitive_headers_but_keeps_others():
    event = before_send(_event(), {})

    headers = event["request"]["headers"]
    assert "Cookie" not in headers
    assert "Authorization" not in headers
    assert headers["User-Agent"] == "pytest"


def test_scrubs_any_extra_key_named_payload_recursively():
    event = before_send(_event(), {})

    extra = event["extra"]
    assert extra["payload"] == "[scrubbed]"
    assert extra["form_id"] == "abc-123"
    assert extra["nested"]["payload"] == "[scrubbed]"


def test_handles_event_with_no_request_or_extra():
    event = before_send({"message": "boom"}, {})

    assert event == {"message": "boom"}
