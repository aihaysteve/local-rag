"""eM Client email parser.

Reads emails from the eM Client per-account SQLite databases in read-only
mode and yields structured EmailMessage objects.

eM Client stores data across multiple .dat files per account, in nested
UUID directories:

    <eM Client dir>/<account-uuid>/<sub-uuid>/
        mail_index.dat   — MailItems table (subject, date, messageId, etc.)
                           MailAddresses table (From, To, CC, BCC)
        mail_fti.dat     — LocalMailsIndex3 table (pre-extracted body text)
        folders.dat      — Folders table (folder id → name/path)
        mail_data.dat    — LocalMailContents (raw MIME parts, fallback)

Dates in MailItems are stored as .NET ticks (100-nanosecond intervals
since 0001-01-01).
"""

import logging
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# .NET ticks epoch: 0001-01-01
_DOTNET_EPOCH = datetime(1, 1, 1)

# UUID4 directory pattern
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# eM Client address type codes
_ADDR_TYPE_FROM = 1
_ADDR_TYPE_TO = 4
_ADDR_TYPE_CC = 5

# Patterns for stripping quoted reply chains
_QUOTED_LINE_RE = re.compile(r"^>.*$", re.MULTILINE)
_ON_WROTE_RE = re.compile(
    r"^On\s+.{10,80}\s+wrote:\s*$", re.MULTILINE | re.IGNORECASE
)
# Signature delimiter: "-- " on its own line (RFC 3676)
_SIG_DELIMITER_RE = re.compile(r"^-- $", re.MULTILINE)
# Common signature patterns
_SIG_PATTERNS = [
    re.compile(
        r"^Sent from my (?:iPhone|iPad|Android|Galaxy).*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(r"^Get Outlook for .*$", re.MULTILINE | re.IGNORECASE),
]


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


def _ticks_to_iso(ticks: int | None) -> str:
    """Convert .NET ticks to an ISO datetime string.

    Returns empty string if ticks is None or conversion fails.
    """
    if not ticks:
        return ""
    try:
        dt = _DOTNET_EPOCH + timedelta(microseconds=ticks / 10)
        return dt.isoformat()
    except (OverflowError, ValueError, OSError):
        return ""


def _strip_quoted_replies(text: str) -> str:
    """Remove quoted reply chains from email body text."""
    match = _ON_WROTE_RE.search(text)
    if match:
        text = text[: match.start()].rstrip()

    text = _QUOTED_LINE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_signature(text: str) -> str:
    """Remove email signature from body text."""
    match = _SIG_DELIMITER_RE.search(text)
    if match:
        text = text[: match.start()].rstrip()

    for pattern in _SIG_PATTERNS:
        match = pattern.search(text)
        if match:
            text = text[: match.start()].rstrip()

    return text


def _open_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open a SQLite database in read-only mode."""
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        logger.warning("Cannot open %s: %s", db_path, e)
        return None


def find_account_dirs(base_path: Path) -> list[Path]:
    """Find eM Client account directories containing mail databases.

    eM Client stores data in nested UUID directories:
      <base>/<account-uuid>/<sub-uuid>/mail_index.dat

    Args:
        base_path: The eM Client data directory.

    Returns:
        List of directories that contain at least mail_index.dat.
    """
    account_dirs: list[Path] = []

    if not base_path.is_dir():
        return account_dirs

    for child in sorted(base_path.iterdir()):
        if not child.is_dir() or not _UUID_RE.match(child.name):
            continue
        for subdir in sorted(child.iterdir()):
            if not subdir.is_dir() or not _UUID_RE.match(subdir.name):
                continue
            if (subdir / "mail_index.dat").is_file():
                account_dirs.append(subdir)

    return account_dirs


def _load_folders(account_dir: Path) -> dict[int, str]:
    """Load folder ID → path mapping from folders.dat.

    Returns:
        Dict mapping folder ID to folder path string.
    """
    folders_path = account_dir / "folders.dat"
    conn = _open_ro(folders_path)
    if not conn:
        return {}

    try:
        rows = conn.execute("SELECT id, path, name FROM Folders").fetchall()
        return {
            row["id"]: row["path"] or row["name"] or ""
            for row in rows
        }
    except sqlite3.OperationalError as e:
        logger.warning("Cannot read folders.dat: %s", e)
        return {}
    finally:
        conn.close()


def _load_fti_content(account_dir: Path) -> dict[int, str]:
    """Load pre-extracted text content from mail_fti.dat.

    Prefers partName='1' (plain text) over partName='2' (HTML-extracted).

    Returns:
        Dict mapping email ID to body text.
    """
    fti_path = account_dir / "mail_fti.dat"
    conn = _open_ro(fti_path)
    if not conn:
        return {}

    try:
        # Fetch all content, ordered so partName=1 comes first per id
        rows = conn.execute(
            "SELECT id, partName, content FROM LocalMailsIndex3 "
            "ORDER BY id, partName"
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("Cannot read mail_fti.dat: %s", e)
        return {}
    finally:
        conn.close()

    content: dict[int, str] = {}
    for row in rows:
        mail_id = row["id"]
        text = row["content"] or ""
        if not text.strip():
            continue
        # Keep the first non-empty content per id (partName=1 preferred)
        if mail_id not in content:
            content[mail_id] = text

    return content


def _load_addresses(
    conn: sqlite3.Connection,
) -> dict[int, dict[str, list[str]]]:
    """Load all addresses grouped by email ID.

    Returns:
        Dict mapping email ID to {"from": [...], "to": [...], "cc": [...]}.
    """
    rows = conn.execute(
        "SELECT parentId, type, displayName, address "
        "FROM MailAddresses ORDER BY parentId, type, position"
    ).fetchall()

    addresses: dict[int, dict[str, list[str]]] = {}
    for row in rows:
        mail_id = row["parentId"]
        if mail_id not in addresses:
            addresses[mail_id] = {"from": [], "to": [], "cc": []}

        name = row["displayName"] or ""
        addr = row["address"] or ""
        if not addr:
            continue

        formatted = f"{name} <{addr}>" if name else addr

        addr_type = row["type"]
        if addr_type == _ADDR_TYPE_FROM:
            addresses[mail_id]["from"].append(formatted)
        elif addr_type == _ADDR_TYPE_TO:
            addresses[mail_id]["to"].append(formatted)
        elif addr_type == _ADDR_TYPE_CC:
            addresses[mail_id]["cc"].append(formatted)

    return addresses


def parse_emails(
    account_dir: str | Path, since_date: str | None = None
) -> Iterator[EmailMessage]:
    """Parse emails from an eM Client account directory.

    Opens databases in read-only mode to prevent any accidental writes.

    Args:
        account_dir: Path to the account directory containing .dat files.
        since_date: Only return emails after this ISO date string.
            If None, returns all emails.

    Yields:
        EmailMessage objects for each parsed email.
    """
    account_dir = Path(account_dir)
    mail_index_path = account_dir / "mail_index.dat"

    if not mail_index_path.is_file():
        logger.error("mail_index.dat not found in %s", account_dir)
        return

    conn = _open_ro(mail_index_path)
    if not conn:
        return

    try:
        # Load supporting data
        folders = _load_folders(account_dir)
        fti_content = _load_fti_content(account_dir)
        addresses = _load_addresses(conn)

        logger.info(
            "Loaded %d folders, %d body texts, %d address sets",
            len(folders),
            len(fti_content),
            len(addresses),
        )

        # Build query
        query = "SELECT id, folder, date, subject, messageId, preview FROM MailItems"
        params: list[str] = []

        if since_date:
            # Convert ISO date to .NET ticks for comparison
            since_ticks = _iso_to_ticks(since_date)
            if since_ticks:
                query += " WHERE date > ?"
                params.append(str(since_ticks))

        query += " ORDER BY date ASC"

        cursor = conn.execute(query, params)
        row_count = 0
        error_count = 0

        for row in cursor:
            try:
                msg = _row_to_email(row, folders, fti_content, addresses)
                if msg:
                    row_count += 1
                    yield msg
            except Exception as e:
                error_count += 1
                if error_count <= 10:
                    logger.warning("Error parsing email row id=%s: %s", row["id"], e)
                elif error_count == 11:
                    logger.warning("Suppressing further row parse errors...")

        logger.info("Parsed %d emails (%d errors)", row_count, error_count)

    except sqlite3.OperationalError as e:
        logger.error("Error reading mail_index.dat: %s", e)
    finally:
        conn.close()


def _iso_to_ticks(iso_date: str) -> int | None:
    """Convert an ISO date/datetime string to .NET ticks."""
    try:
        if "T" in iso_date:
            dt = datetime.fromisoformat(iso_date)
        else:
            dt = datetime.fromisoformat(iso_date + "T00:00:00")
        delta = dt - _DOTNET_EPOCH
        return int(delta.total_seconds() * 10_000_000)
    except (ValueError, OverflowError):
        return None


def _row_to_email(
    row: sqlite3.Row,
    folders: dict[int, str],
    fti_content: dict[int, str],
    addresses: dict[int, dict[str, list[str]]],
) -> EmailMessage | None:
    """Convert a MailItems row to an EmailMessage."""
    mail_id = row["id"]
    subject = row["subject"] or ""
    message_id = row["messageId"] or ""
    date_str = _ticks_to_iso(row["date"])

    # Folder
    folder_id = row["folder"]
    folder = folders.get(folder_id, "")

    # Addresses
    addr_data = addresses.get(mail_id, {"from": [], "to": [], "cc": []})
    sender = addr_data["from"][0] if addr_data["from"] else ""
    recipients = addr_data["to"] + addr_data["cc"]

    # Body text from FTI, fallback to preview
    body = fti_content.get(mail_id, "")
    if not body:
        body = row["preview"] or ""

    if not body and not subject:
        return None

    # Clean body
    body = _strip_quoted_replies(body)
    body = _strip_signature(body)

    if not body.strip() and not subject:
        return None

    # Generate a stable message_id if we don't have one
    if not message_id:
        import hashlib

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
