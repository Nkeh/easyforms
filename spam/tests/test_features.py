import math

from spam.features import TextStatsExtractor, extract_text, normalize_text


def test_extract_text_joins_string_fields_in_sorted_key_order():
    payload = {"zebra": "last", "apple": "first", "mango": "middle"}
    assert extract_text(payload) == "first middle last"


def test_extract_text_includes_string_list_items_in_list_order():
    payload = {"tags": ["third", "first", "second"]}
    assert extract_text(payload) == "third first second"


def test_extract_text_skips_reserved_keys():
    payload = {"name": "Jane", "_ts": "12345", "_honeypot": "", "_redirect": "https://x.example"}
    assert extract_text(payload) == "Jane"


def test_extract_text_ignores_non_string_non_list_values():
    payload = {
        "name": "Jane",
        "age": 30,
        "subscribed": True,
        "missing": None,
        "meta": {"nested": "dict"},
        "numbers": [1, 2, "three"],
    }
    assert extract_text(payload) == "Jane three"


def test_extract_text_empty_payload_is_empty_string():
    assert extract_text({}) == ""


def test_text_stats_extractor_known_values():
    texts = [
        "",
        "HELLO WORLD",
        "call 12345 now",
        "visit http://free-prize.example now www.also-here.example",
    ]
    features = TextStatsExtractor().transform(texts)

    # empty string: everything zero, log1p(0) == 0
    assert list(features[0]) == [0, 0.0, 0.0, 0.0, 0.0]

    # all-uppercase, no digits, no url
    link_count, has_url, upper_ratio, log_len, digit_ratio = features[1]
    assert link_count == 0
    assert has_url == 0.0
    assert upper_ratio == 1.0
    assert digit_ratio == 0.0
    assert log_len == math.log1p(len("HELLO WORLD"))

    # digits present, lowercase
    link_count, has_url, upper_ratio, log_len, digit_ratio = features[2]
    assert link_count == 0
    assert has_url == 0.0
    assert upper_ratio == 0.0
    assert digit_ratio == 5 / len("call 12345 now")

    # two url-like substrings
    link_count, has_url, upper_ratio, log_len, digit_ratio = features[3]
    assert link_count == 2
    assert has_url == 1.0


def test_text_stats_extractor_is_sklearn_compatible():
    extractor = TextStatsExtractor()
    assert extractor.fit(["a", "b"]) is extractor
    result = extractor.fit_transform(["hello", "WORLD 123"])
    assert result.shape == (2, 5)


def test_text_stats_extractor_operates_on_raw_text_not_normalized_text():
    # If this were normalized first, "NOW" would be lowercased (uppercase_ratio
    # would be 0) and "12345" would become the word "numtoken" (digit_ratio
    # would be 0). Neither happens: TextStatsExtractor sees the raw text.
    features = TextStatsExtractor().transform(["Visit http://x.example NOW 12345"])
    link_count, has_url, upper_ratio, _log_len, digit_ratio = features[0]
    assert link_count == 1
    assert has_url == 1.0
    assert upper_ratio > 0
    assert digit_ratio > 0


def test_normalize_text_lowercases():
    assert normalize_text("HELLO World") == "hello world"


def test_normalize_text_replaces_url_with_urltoken():
    result = normalize_text("Check out https://Example.com/Page?x=1 NOW")
    assert result == "check out urltoken now"


def test_normalize_text_replaces_www_url_with_urltoken():
    result = normalize_text("see www.Example.com/deal for details")
    assert result == "see urltoken for details"


def test_normalize_text_replaces_email_with_emailtoken():
    result = normalize_text("Contact me at John.Doe+test@Example.co.uk please")
    assert result == "contact me at emailtoken please"


def test_normalize_text_replaces_phone_like_digits_with_phonetoken():
    result = normalize_text("Call me at 555-0134 today")
    assert result == "call me at phonetoken today"


def test_normalize_text_replaces_generic_digit_run_with_numtoken():
    result = normalize_text("Order #4821 shipped")
    assert result == "order # numtoken shipped"


def test_normalize_text_collapses_whitespace():
    assert normalize_text("  Hello   World  ") == "hello world"


def test_normalize_text_order_url_before_email_before_phone_before_digits():
    # A URL containing digits, an email, a phone number, and a bare number,
    # all in one string -- each substitution should only see what's left
    # after the prior one, so nothing is double-tokenized or mis-tokenized.
    text = "See http://shop.example/item123 or email sales@example.com or call 555-0134, order #77"
    result = normalize_text(text)
    assert "urltoken" in result
    assert "emailtoken" in result
    assert "phonetoken" in result
    assert "numtoken" in result
    assert "item123" not in result
    assert "555-0134" not in result
    assert "sales@example.com" not in result
