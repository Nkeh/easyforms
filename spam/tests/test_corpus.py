from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import spam.corpus as corpus


def test_strip_html_extracts_text_and_skips_script_style():
    html = (
        "<html><body><p>Hello <b>World</b></p>"
        "<script>bad()</script><style>.x{color:red}</style></body></html>"
    )
    result = corpus.strip_html(html)

    assert "Hello" in result
    assert "World" in result
    assert "bad()" not in result
    assert "color:red" not in result


def test_strip_quotes_and_signature_drops_quoted_lines_and_stops_at_signature_delimiter():
    text = (
        "Real reply text\n> quoted original message\nMore real text\n"
        "--\nJohn Doe\nSent from my phone"
    )

    result = corpus._strip_quotes_and_signature(text)

    assert "Real reply text" in result
    assert "More real text" in result
    assert "quoted original message" not in result
    assert "John Doe" not in result
    assert "Sent from my phone" not in result


def test_strip_quotes_and_signature_drops_on_wrote_lines():
    text = "Sure, sounds good.\nOn Tuesday, Jan 5, 2026, Jane Doe wrote:\n> original message here"

    result = corpus._strip_quotes_and_signature(text)

    assert "Sure, sounds good." in result
    assert "Jane Doe wrote" not in result
    assert "original message here" not in result


def test_parse_email_file_prefers_plain_text_part_in_multipart_alternative(tmp_path):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Meeting Tomorrow"
    msg["From"] = "sender@example.com"
    msg.attach(MIMEText("See you at noon.", "plain"))
    msg.attach(
        MIMEText(
            "<html><body>See you at <b>noon</b>. <script>track()</script></body></html>", "html"
        )
    )
    path = tmp_path / "email1"
    path.write_bytes(msg.as_bytes())

    result = corpus._parse_email_file(path)

    assert "Meeting Tomorrow" in result
    assert "See you at noon." in result
    assert "track()" not in result
    assert "<b>" not in result


def test_parse_email_file_falls_back_to_stripped_html_when_only_html_part_exists(tmp_path):
    msg = MIMEText(
        "<html><body><p>Special offer <b>today</b></p><script>evil()</script></body></html>",
        "html",
    )
    msg["Subject"] = "Offer"
    msg["From"] = "sender@example.com"
    path = tmp_path / "email2"
    path.write_bytes(msg.as_bytes())

    result = corpus._parse_email_file(path)

    assert "Offer" in result
    assert "Special offer" in result
    assert "today" in result
    assert "evil()" not in result
    assert "<b>" not in result


def test_parse_email_file_returns_none_for_unparseable_bytes_without_raising(tmp_path, monkeypatch):
    path = tmp_path / "bad_email"
    path.write_bytes(b"whatever")

    def _raise(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(corpus.email, "message_from_bytes", _raise)

    assert corpus._parse_email_file(path) is None


def test_load_email_dir_skips_cmds_file_and_counts_skipped_files(tmp_path, monkeypatch):
    d = tmp_path / "easy_ham"
    d.mkdir()
    (d / "0001").write_bytes(b"placeholder")
    (d / "0002").write_bytes(b"placeholder")
    (d / "cmds").write_bytes(b"some build script, not an email")

    def fake_parse(path):
        # cmds should never reach here at all -- if it does, it'll return
        # None too (since its name != "0001"), inflating n_skipped to 2.
        return "parsed body" if path.name == "0001" else None

    monkeypatch.setattr(corpus, "_parse_email_file", fake_parse)

    rows, n_skipped = corpus._load_email_dir(d, "ham")

    assert rows == [("ham", "parsed body")]
    assert n_skipped == 1


def test_download_email_corpus_falls_back_to_enron_when_spamassassin_unreachable(
    tmp_path, monkeypatch
):
    def _raise(dest_dir):
        raise corpus.EmailCorpusError("network down")

    monkeypatch.setattr(corpus, "_download_spamassassin", _raise)
    monkeypatch.setattr(
        corpus, "_download_enron", lambda dest_dir: [("ham", "hi"), ("spam", "buy now")]
    )

    rows, source = corpus.download_email_corpus(tmp_path)

    assert source == "enron"
    assert rows == [("ham", "hi"), ("spam", "buy now")]


def test_count_labels_counts_ham_and_spam():
    rows = [("ham", "a"), ("spam", "b"), ("ham", "c")]
    assert corpus.count_labels(rows) == {"ham": 2, "spam": 1}
