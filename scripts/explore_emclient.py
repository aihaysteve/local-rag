#!/usr/bin/env python3
"""Explore the eM Client SQLite database schema.

Discovers eM Client account directories and explores the per-account
database files (mail_index.dat, mail_fti.dat, folders.dat, mail_data.dat).
Opens all databases in read-only mode to prevent any accidental writes.

Usage:
    python scripts/explore_emclient.py [/path/to/eM Client dir]

If no path is given, looks in ~/Library/Application Support/eM Client/.
"""

import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# .NET ticks epoch: 0001-01-01
_DOTNET_EPOCH = datetime(1, 1, 1)

# UUID4 pattern for account/sub directories
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Database files we care about, in order of importance
_DAT_FILES = ["mail_index.dat", "mail_fti.dat", "folders.dat", "mail_data.dat"]


def _ticks_to_datetime(ticks: int) -> str:
    """Convert .NET ticks to an ISO datetime string."""
    try:
        dt = _DOTNET_EPOCH + timedelta(microseconds=ticks / 10)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, ValueError, OSError):
        return f"<ticks:{ticks}>"


def find_account_dirs(base_path: Path) -> list[Path]:
    """Find eM Client account directories containing mail databases.

    eM Client stores data in nested UUID directories:
      <base>/<account-uuid>/<sub-uuid>/mail_index.dat

    Returns list of directories that contain at least mail_index.dat.
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


def _open_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open a SQLite database in read-only mode."""
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        print(f"  WARNING: Cannot open {db_path.name}: {e}")
        return None


def _print_schema(conn: sqlite3.Connection, db_name: str) -> None:
    """Print table schemas and row counts for a database."""
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    print(f"  === {db_name}: {len(tables)} tables ===")
    for t in tables:
        table_name = t["name"]
        columns = conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()
        try:
            count = conn.execute(f"SELECT COUNT(*) as cnt FROM [{table_name}]").fetchone()  # noqa: S608 — table_name from PRAGMA table_list, not user input
            row_count = count["cnt"]
        except sqlite3.OperationalError:
            row_count = "?"

        col_list = ", ".join(col["name"] for col in columns)
        print(f"    {table_name} ({row_count} rows): [{col_list}]")

    print()


def _explore_mail_index(conn: sqlite3.Connection) -> None:
    """Print sample data from mail_index.dat."""
    # Sample MailItems
    print("  --- MailItems (sample) ---")
    rows = conn.execute(
        "SELECT id, folder, date, subject, messageId, preview "
        "FROM MailItems ORDER BY date DESC LIMIT 5"
    ).fetchall()
    for r in rows:
        date_str = _ticks_to_datetime(r["date"]) if r["date"] else "?"
        subject = (r["subject"] or "")[:80]
        preview = (r["preview"] or "")[:100]
        print(f"    id={r['id']}, folder={r['folder']}, date={date_str}")
        print(f"      subject: {subject}")
        print(f"      preview: {preview}")
        print()

    # Address type distribution
    print("  --- MailAddresses type distribution ---")
    rows = conn.execute(
        "SELECT type, COUNT(*) as cnt FROM MailAddresses GROUP BY type ORDER BY type"
    ).fetchall()
    type_labels = {1: "From", 2: "Sender", 3: "Reply-To", 4: "To", 5: "CC", 6: "BCC"}
    for r in rows:
        label = type_labels.get(r["type"], "Unknown")
        print(f"    type={r['type']} ({label}): {r['cnt']} entries")

    # Sample addresses for one email
    print()
    print("  --- MailAddresses sample (first email) ---")
    first = conn.execute("SELECT id FROM MailItems LIMIT 1").fetchone()
    if first:
        addrs = conn.execute(
            "SELECT type, displayName, address FROM MailAddresses "
            "WHERE parentId=? ORDER BY type, position",
            (first["id"],),
        ).fetchall()
        for a in addrs:
            label = type_labels.get(a["type"], "?")
            print(f"    {label}: {a['displayName']} <{a['address']}>")

    print()


def _explore_fti(conn: sqlite3.Connection) -> None:
    """Print sample data from mail_fti.dat."""
    print("  --- LocalMailsIndex3 (sample) ---")
    rows = conn.execute(
        "SELECT id, partName, length(content) as content_len, "
        "substr(content, 1, 150) as preview "
        "FROM LocalMailsIndex3 LIMIT 6"
    ).fetchall()
    for r in rows:
        print(f"    id={r['id']}, partName={r['partName']}, len={r['content_len']}")
        print(f"      {(r['preview'] or '')[:120]}")
        print()


def _explore_folders(conn: sqlite3.Connection) -> None:
    """Print folder tree from folders.dat."""
    print("  --- Folders ---")
    rows = conn.execute("SELECT id, name, path FROM Folders ORDER BY id").fetchall()
    for r in rows:
        print(f"    id={r['id']}: {r['path'] or '/'} ({r['name']})")
    print()


def explore_account(account_dir: Path) -> None:
    """Explore all database files in a single account directory."""
    print(f"\n{'=' * 70}")
    print(f"Account directory: {account_dir}")
    print(f"{'=' * 70}")

    # List which .dat files exist and their sizes
    print("\n  Database files:")
    for name in _DAT_FILES:
        p = account_dir / name
        if p.is_file():
            size = p.stat().st_size
            print(f"    {name}: {size:,} bytes")
        else:
            print(f"    {name}: NOT FOUND")
    print()

    # Explore each database
    for db_name in _DAT_FILES:
        db_path = account_dir / db_name
        if not db_path.is_file():
            continue

        conn = _open_ro(db_path)
        if not conn:
            continue

        try:
            _print_schema(conn, db_name)

            if db_name == "mail_index.dat":
                _explore_mail_index(conn)
            elif db_name == "mail_fti.dat":
                _explore_fti(conn)
            elif db_name == "folders.dat":
                _explore_folders(conn)
        except sqlite3.OperationalError as e:
            print(f"  ERROR reading {db_name}: {e}")
        finally:
            conn.close()


def main() -> None:
    """Entry point."""
    custom_path = sys.argv[1] if len(sys.argv) > 1 else None

    if custom_path:
        base = Path(custom_path).expanduser()
    else:
        base = Path.home() / "Library" / "Application Support" / "eM Client"

    if not base.is_dir():
        print(f"ERROR: Directory not found: {base}")
        sys.exit(1)

    print(f"eM Client data directory: {base}")

    account_dirs = find_account_dirs(base)

    if not account_dirs:
        print("No account directories with mail databases found.")
        print("Expected structure: <base>/<uuid>/<uuid>/mail_index.dat")
        sys.exit(1)

    print(f"Found {len(account_dirs)} account(s)")

    for account_dir in account_dirs:
        try:
            explore_account(account_dir)
        except sqlite3.OperationalError as e:
            err_str = str(e).lower()
            if "locked" in err_str or "busy" in err_str:
                print(f"  ERROR: Database locked (eM Client may be running): {e}")
            else:
                print(f"  ERROR: SQLite error: {e}")
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
