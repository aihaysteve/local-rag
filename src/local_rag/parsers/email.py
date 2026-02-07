"""eM Client email parser.

Reads emails from the eM Client SQLite database (mail_data.dat) in read-only
mode and yields structured EmailMessage objects.
"""

import email.utils
import hashlib
import logging
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    """A parsed email message."""

    subject: str
    body_text: str
    sender: str
    recipients: list[str] = field(default_factory=list)
    date: str = ""
    folder: str = ""
    message_id: str = ""


# Patterns for stripping quoted reply chains
_QUOTED_LINE_RE = re.compile(r"^>.*$", re.MULTILINE)
_ON_WROTE_RE = re.compile(
    r"^On\s+.{10,80}\s+wrote:\s*$", re.MULTILINE | re.IGNORECASE
)
# Signature delimiter: "-- " on its own line (RFC 3676)
_SIG_DELIMITER_RE = re.compile(r"^-- $", re.MULTILINE)
# Common signature patterns
_SIG_PATTERNS = [
    re.compile(r"^Sent from my (?:iPhone|iPad|Android|Galaxy).*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Get Outlook for .*$", re.MULTILINE | re.IGNORECASE),
]


def _strip_quoted_replies(text: str) -> str:
    """Remove quoted reply chains from email body text."""
    # Find "On ... wrote:" blocks and remove everything after
    match = _ON_WROTE_RE.search(text)
    if match:
        text = text[: match.start()].rstrip()

    # Remove individual quoted lines (> prefix)
    text = _QUOTED_LINE_RE.sub("", text)

    # Clean up resulting blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_signature(text: str) -> str:
    """Remove email signature from body text."""
    # RFC 3676 signature delimiter
    match = _SIG_DELIMITER_RE.search(text)
    if match:
        text = text[: match.start()].rstrip()

    # Common mobile/app signatures
    for pattern in _SIG_PATTERNS:
        match = pattern.search(text)
        if match:
            text = text[: match.start()].rstrip()

    return text


def _html_to_text(html: str) -> str:
    """Convert HTML email body to plain text."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style elements
    for tag in soup(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_header_blob(header_data: bytes | str) -> dict[str, str]:
    """Parse email headers from raw header data.

    eM Client stores headers in various formats. This function tries to
    parse them as RFC 2822 headers.

    Args:
        header_data: Raw header bytes or string.

    Returns:
        Dictionary of lowercase header name -> value.
    """
    headers: dict[str, str] = {}

    if isinstance(header_data, bytes):
        try:
            header_str = header_data.decode("utf-8", errors="replace")
        except Exception:
            return headers
    else:
        header_str = header_data

    if not header_str:
        return headers

    # Parse RFC 2822 style headers
    current_key: str | None = None
    current_value = ""

    for line in header_str.split("\n"):
        line = line.rstrip("\r")

        # Continuation line (starts with whitespace)
        if line and line[0] in (" ", "\t") and current_key:
            current_value += " " + line.strip()
            continue

        # Save previous header
        if current_key:
            headers[current_key.lower()] = current_value

        # New header line
        if ":" in line:
            key, _, value = line.partition(":")
            current_key = key.strip()
            current_value = value.strip()
        else:
            current_key = None
            current_value = ""

    # Save last header
    if current_key:
        headers[current_key.lower()] = current_value

    return headers


def _discover_schema(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Discover tables and their columns in the eM Client database.

    Returns:
        Dict mapping table name to list of column names.
    """
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()

    schema: dict[str, list[str]] = {}
    for table_row in tables:
        name = table_row[0] if isinstance(table_row, tuple) else table_row["name"]
        try:
            cols = conn.execute(f"PRAGMA table_info([{name}])").fetchall()
            col_names = []
            for col in cols:
                col_name = col[1] if isinstance(col, tuple) else col["name"]
                col_names.append(col_name)
            schema[name] = col_names
        except sqlite3.OperationalError:
            continue

    return schema


def _find_mail_table(schema: dict[str, list[str]]) -> str | None:
    """Identify the primary mail/message table from the schema.

    Returns the table name or None if not found.
    """
    # Known table names used by eM Client
    candidates = [
        "MailItem",
        "mail_item",
        "MailItems",
        "Messages",
        "mail_basicstrings",
    ]

    for name in candidates:
        if name in schema:
            return name

    # Fallback: look for tables with mail-related columns
    for table_name, columns in schema.items():
        col_lower = [c.lower() for c in columns]
        if "subject" in col_lower and ("body" in col_lower or "partheader" in col_lower):
            return table_name

    # Another fallback: tables with "mail" in the name
    for table_name in schema:
        if "mail" in table_name.lower():
            return table_name

    return None


def parse_emails(
    db_path: str, since_date: str | None = None
) -> Iterator[EmailMessage]:
    """Parse emails from the eM Client SQLite database.

    Opens the database in read-only mode to prevent any accidental writes.

    Args:
        db_path: Path to the eM Client mail_data.dat file.
        since_date: Only return emails after this ISO date string (YYYY-MM-DD).
            If None, returns all emails.

    Yields:
        EmailMessage objects for each parsed email.
    """
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError as e:
        logger.error("Cannot open eM Client database at %s: %s", db_path, e)
        return

    try:
        schema = _discover_schema(conn)
        if not schema:
            logger.error("eM Client database has no tables. Is %s the correct file?", db_path)
            return

        mail_table = _find_mail_table(schema)
        if not mail_table:
            logger.error(
                "Could not find a mail table in eM Client database. "
                "Tables found: %s. Run scripts/explore_emclient.py to inspect the schema.",
                list(schema.keys()),
            )
            return

        columns = schema[mail_table]
        col_lower = {c.lower(): c for c in columns}

        logger.info("Using mail table: %s (columns: %s)", mail_table, columns)

        yield from _parse_from_table(conn, mail_table, col_lower, since_date)

    except sqlite3.OperationalError as e:
        logger.error("Error reading eM Client database: %s", e)
    finally:
        conn.close()


def _parse_from_table(
    conn: sqlite3.Connection,
    table_name: str,
    col_lower: dict[str, str],
    since_date: str | None,
) -> Iterator[EmailMessage]:
    """Parse emails from the discovered mail table.

    Adapts to whatever columns are available in the table.
    """
    # Map expected fields to actual column names
    field_candidates = {
        "subject": ["subject"],
        "body": ["body", "bodytext", "body_text", "textbody"],
        "html_body": ["htmlbody", "html_body", "bodyhtml", "body_html"],
        "sender": ["sender", "from", "fromaddress", "from_address", "senderaddress"],
        "recipients": ["to", "recipients", "toaddress", "to_address"],
        "cc": ["cc", "ccaddress", "cc_address"],
        "date": ["date", "datereceived", "date_received", "sentdate", "sent_date", "receiveddate"],
        "folder": ["folder", "foldername", "folder_name", "folderid", "folder_id"],
        "message_id": [
            "messageid", "message_id", "internetmessageid", "internet_message_id",
        ],
        "header": ["partheader", "part_header", "header", "headers", "internetheader"],
    }

    select_cols: list[str] = []
    col_mapping: dict[str, str] = {}  # our_name -> actual_col_name

    for our_name, candidates in field_candidates.items():
        for candidate in candidates:
            if candidate in col_lower:
                actual = col_lower[candidate]
                col_mapping[our_name] = actual
                select_cols.append(f"[{actual}]")
                break

    if not select_cols:
        logger.error("No usable columns found in table %s", table_name)
        return

    # Build query
    query = f"SELECT {', '.join(select_cols)} FROM [{table_name}]"
    params: list[str] = []

    # Date filtering if we have a date column and a filter
    if since_date and "date" in col_mapping:
        date_col = col_mapping["date"]
        query += f" WHERE [{date_col}] > ?"
        params.append(since_date)

    if "date" in col_mapping:
        date_col = col_mapping["date"]
        query += f" ORDER BY [{date_col}] ASC"

    logger.debug("Email query: %s", query)

    try:
        cursor = conn.execute(query, params)
    except sqlite3.OperationalError as e:
        logger.error("Failed to query mail table %s: %s", table_name, e)
        return

    row_count = 0
    error_count = 0

    for row in cursor:
        try:
            msg = _row_to_email(row, col_mapping)
            if msg:
                row_count += 1
                yield msg
        except Exception as e:
            error_count += 1
            if error_count <= 10:
                logger.warning("Error parsing email row: %s", e)
            elif error_count == 11:
                logger.warning("Suppressing further row parse errors...")

    logger.info("Parsed %d emails (%d errors)", row_count, error_count)


def _row_to_email(
    row: sqlite3.Row, col_mapping: dict[str, str]
) -> EmailMessage | None:
    """Convert a database row to an EmailMessage."""

    def get(field_name: str) -> str:
        if field_name not in col_mapping:
            return ""
        actual_col = col_mapping[field_name]
        val = row[actual_col]
        if val is None:
            return ""
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="replace")
        return str(val)

    # Try to get fields from direct columns
    subject = get("subject")
    sender = get("sender")
    recipients_str = get("recipients")
    cc_str = get("cc")
    date_str = get("date")
    folder = get("folder")
    message_id = get("message_id")

    # Parse headers if available and we're missing fields
    header_data = get("header")
    if header_data and (not subject or not sender or not message_id):
        headers = _parse_header_blob(header_data.encode("utf-8", errors="replace"))
        if not subject:
            subject = headers.get("subject", "")
        if not sender:
            sender = headers.get("from", "")
        if not message_id:
            message_id = headers.get("message-id", "")
        if not date_str:
            date_str = headers.get("date", "")
        if not recipients_str:
            recipients_str = headers.get("to", "")
        if not cc_str:
            cc_str = headers.get("cc", "")

    # Get body text
    body = get("body")
    html_body = get("html_body")

    if not body and html_body:
        body = _html_to_text(html_body)
    elif html_body and not body.strip():
        body = _html_to_text(html_body)

    if not body and not subject:
        return None

    # Clean body
    body = _strip_quoted_replies(body)
    body = _strip_signature(body)

    # Parse recipients
    recipients: list[str] = []
    for addr_str in [recipients_str, cc_str]:
        if addr_str:
            parsed = email.utils.getaddresses([addr_str])
            recipients.extend(
                addr if not name else f"{name} <{addr}>"
                for name, addr in parsed
                if addr
            )

    # Normalize date to ISO format if possible
    if date_str:
        try:
            parsed_date = email.utils.parsedate_to_datetime(date_str)
            date_str = parsed_date.isoformat()
        except (ValueError, TypeError):
            pass  # Keep the original string

    # Generate a message_id if we don't have one
    if not message_id:
        id_source = f"{sender}|{subject}|{date_str}"
        message_id = hashlib.sha256(id_source.encode()).hexdigest()[:32]

    return EmailMessage(
        subject=subject,
        body_text=body,
        sender=sender,
        recipients=recipients,
        date=date_str,
        folder=folder,
        message_id=message_id,
    )
