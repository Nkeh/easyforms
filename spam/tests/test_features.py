import math

from spam.features import TextStatsExtractor, extract_text


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
