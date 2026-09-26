import csv
import email
import email.policy
import hashlib
import logging
import re
import shutil
import tarfile
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path

logger = logging.getLogger("spam")

MAX_BODY_CHARS = 2000

# (url, sha256, member_dir_name, label) — SHA-256 values computed once
# against the real downloads, same pattern as spam.training.DATASET_SHA256.
_SPAMASSASSIN_ARCHIVES = [
    (
        "https://spamassassin.apache.org/old/publiccorpus/20030228_easy_ham.tar.bz2",
        "2b7b65904bcfcc31d2b5f51946f2d261370b257402cbbd62930b46ab83367438",
        "easy_ham",
        "ham",
    ),
    (
        "https://spamassassin.apache.org/old/publiccorpus/20030228_hard_ham.tar.bz2",
        "ce2ce67880643dbde65ea7f85bffbfe4417349c4bd80b6b0de56262ae6b0a9c9",
        "hard_ham",
        "ham",
    ),
    (
        "https://spamassassin.apache.org/old/publiccorpus/20050311_spam_2.tar.bz2",
        "44280a0e28bf7645b2279e8e42659271ad82c6f40bf8d364dbda7f1df344a765",
        "spam_2",
        "spam",
    ),
]

ENRON_URL = "https://github.com/MWiechmann/enron_spam_data/raw/master/enron_spam_data.zip"
ENRON_SHA256 = "e994ad3c09fd7528b397e1f921742da5dd59f19695bc25cdb3617eb3ded17634"

_QUOTE_WROTE_RE = re.compile(r"^on .+ wrote:$", re.IGNORECASE)


class EmailCorpusError(Exception):
    pass


def download_email_corpus(dest_dir: Path) -> tuple[list[tuple[str, str]], str]:
    """Try the SpamAssassin public corpus; on ANY failure (network or
    checksum) for any of its three archives, fall back entirely to
    Enron-Spam. Returns (rows, source_name)."""
    dest_dir = Path(dest_dir)
    try:
        return _download_spamassassin(dest_dir), "spamassassin"
    except Exception as exc:
        logger.warning("SpamAssassin corpus unavailable (%s); falling back to Enron-Spam", exc)
        return _download_enron(dest_dir), "enron"


def count_labels(rows: list[tuple[str, str]]) -> dict[str, int]:
    return {
        "ham": sum(1 for label, _ in rows if label == "ham"),
        "spam": sum(1 for label, _ in rows if label == "spam"),
    }


def _download_spamassassin(dest_dir: Path) -> list[tuple[str, str]]:
    rows = []
    for url, sha256, member_dir_name, label in _SPAMASSASSIN_ARCHIVES:
        extracted_dir = _download_and_extract_tarbz2(url, sha256, dest_dir, member_dir_name)
        dir_rows, n_skipped = _load_email_dir(extracted_dir, label)
        if n_skipped:
            logger.warning("skipped %d unparseable files in %s", n_skipped, member_dir_name)
        rows.extend(dir_rows)
    return rows


def _download_and_extract_tarbz2(
    url: str, sha256: str, dest_dir: Path, member_dir_name: str
) -> Path:
    extracted_dir = dest_dir / "spamassassin" / member_dir_name
    if extracted_dir.exists() and any(extracted_dir.iterdir()):
        return extracted_dir

    dest_dir.mkdir(parents=True, exist_ok=True)
    archive_path = dest_dir / f"spamassassin_{member_dir_name}.tar.bz2"
    with urllib.request.urlopen(url) as response, open(archive_path, "wb") as f:
        shutil.copyfileobj(response, f)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if digest != sha256:
        archive_path.unlink()
        raise EmailCorpusError(f"checksum mismatch for {url}: expected {sha256}, got {digest}")

    extracted_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:bz2") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            if not name:
                continue
            src = tf.extractfile(member)
            if src is None:
                continue
            (extracted_dir / name).write_bytes(src.read())
    archive_path.unlink()

    return extracted_dir


def _load_email_dir(dir_path: Path, label: str) -> tuple[list[tuple[str, str]], int]:
    rows = []
    n_skipped = 0
    for path in sorted(dir_path.iterdir()):
        if not path.is_file() or path.name == "cmds":
            continue
        text = _parse_email_file(path)
        if text is None:
            n_skipped += 1
            continue
        rows.append((label, text))
    return rows, n_skipped


def _parse_email_file(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        subject = msg.get("Subject", "") or ""
        body_part = msg.get_body(preferencelist=("plain", "html"))
        if body_part is None:
            body = ""
        else:
            content = body_part.get_content()
            body = strip_html(content) if body_part.get_content_type() == "text/html" else content
        combined = _strip_quotes_and_signature(f"{subject} {body}")
        return combined[:MAX_BODY_CHARS]
    except Exception:
        return None


class _TextExtractingHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)


def strip_html(html_text: str) -> str:
    parser = _TextExtractingHTMLParser()
    try:
        parser.feed(html_text)
    except Exception:
        pass
    return " ".join(part.strip() for part in parser._parts if part.strip())


def _strip_quotes_and_signature(text: str) -> str:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if _QUOTE_WROTE_RE.match(stripped):
            continue
        if stripped == "--":
            break
        kept.append(line)
    return " ".join(kept)


def _download_enron(dest_dir: Path) -> list[tuple[str, str]]:
    dest_dir = Path(dest_dir)
    csv_path = dest_dir / "enron_spam_data.csv"
    if not csv_path.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
        zip_path = dest_dir / "enron_spam_data.zip"
        with urllib.request.urlopen(ENRON_URL) as response, open(zip_path, "wb") as f:
            shutil.copyfileobj(response, f)

        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        if digest != ENRON_SHA256:
            zip_path.unlink()
            raise EmailCorpusError(
                f"checksum mismatch for {ENRON_URL}: expected {ENRON_SHA256}, got {digest}"
            )

        with zipfile.ZipFile(zip_path) as zf:
            csv_member = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
            if csv_member is None:
                zip_path.unlink()
                raise EmailCorpusError(f"no .csv file found in {ENRON_URL}")
            with zf.open(csv_member) as src, open(csv_path, "wb") as dest:
                shutil.copyfileobj(src, dest)
        zip_path.unlink()

    rows = []
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = (row.get("Spam/Ham") or "").strip().lower()
            if label not in ("ham", "spam"):
                continue
            combined = _strip_quotes_and_signature(
                f"{row.get('Subject') or ''} {row.get('Message') or ''}"
            )
            rows.append((label, combined[:MAX_BODY_CHARS]))
    return rows
