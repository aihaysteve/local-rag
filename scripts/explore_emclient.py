#!/usr/bin/env python3
"""Explore the eM Client SQLite database schema.

Standalone script to discover the eM Client mail_data.dat schema.
Opens the database in read-only mode to prevent any accidental writes.

Usage:
    python scripts/explore_emclient.py [/path/to/mail_data.dat]

If no path is given, looks in ~/Library/Application Support/eM Client/.
"""

import sqlite3
import sys
from pathlib import Path


def find_db_path(custom_path: str | None = None) -> Path:
    """Locate the eM Client database file."""
    if custom_path:
        p = Path(custom_path).expanduser()
        if p.is_file():
            return p
        # Maybe they gave the directory
        candidate = p / "mail_data.dat"
        if candidate.is_file():
            return candidate
        print(f"ERROR: Cannot find database at {p}")
        sys.exit(1)

    default_dir = Path.home() / "Library" / "Application Support" / "eM Client"
    candidate = default_dir / "mail_data.dat"
    if candidate.is_file():
        return candidate

    print(f"ERROR: Cannot find eM Client database at {candidate}")
    print("Provide the path as an argument: python scripts/explore_emclient.py /path/to/mail_data.dat")
    sys.exit(1)


def explore(db_path: Path) -> None:
    """Open the database and print schema information."""
    uri = f"file:{db_path}?mode=ro"
    print(f"Opening database: {db_path}")
    print(f"URI: {uri}")
    print()

    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    # List all tables
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    print(f"=== TABLES ({len(tables)}) ===")
    for t in tables:
        print(f"  {t['name']}")
    print()

    # For each table, print schema
    for t in tables:
        table_name = t["name"]
        print(f"--- TABLE: {table_name} ---")

        columns = conn.execute(f"PRAGMA table_info([{table_name}])").fetchall()
        for col in columns:
            nullable = "NULL" if not col["notnull"] else "NOT NULL"
            pk = " PRIMARY KEY" if col["pk"] else ""
            default = f" DEFAULT {col['dflt_value']}" if col["dflt_value"] else ""
            print(f"  {col['name']}: {col['type']} {nullable}{pk}{default}")

        # Count rows
        try:
            count = conn.execute(f"SELECT COUNT(*) as cnt FROM [{table_name}]").fetchone()
            print(f"  Row count: {count['cnt']}")
        except sqlite3.OperationalError as e:
            print(f"  Could not count rows: {e}")

        print()

    # Print sample rows from tables that look mail-related
    mail_keywords = ["mail", "message", "folder", "contact", "header", "body", "account"]
    mail_tables = [
        t["name"]
        for t in tables
        if any(kw in t["name"].lower() for kw in mail_keywords)
    ]

    if mail_tables:
        print("=== SAMPLE DATA FROM MAIL-RELATED TABLES ===")
        for table_name in mail_tables:
            print(f"\n--- SAMPLES FROM: {table_name} (LIMIT 3) ---")
            try:
                rows = conn.execute(f"SELECT * FROM [{table_name}] LIMIT 3").fetchall()
                if not rows:
                    print("  (empty table)")
                    continue

                col_names = rows[0].keys()
                for i, row in enumerate(rows):
                    print(f"  Row {i + 1}:")
                    for col in col_names:
                        value = row[col]
                        # Truncate long values
                        if isinstance(value, str) and len(value) > 200:
                            value = value[:200] + "..."
                        elif isinstance(value, bytes) and len(value) > 100:
                            value = f"<BLOB {len(value)} bytes>"
                        print(f"    {col}: {value}")
                    print()
            except sqlite3.OperationalError as e:
                print(f"  Error reading table: {e}")
    else:
        print("No obvious mail-related tables found.")

    conn.close()
    print("Done.")


def main() -> None:
    """Entry point."""
    custom_path = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        db_path = find_db_path(custom_path)
        explore(db_path)
    except sqlite3.OperationalError as e:
        err_str = str(e).lower()
        if "locked" in err_str or "busy" in err_str:
            print(f"ERROR: Database is locked (eM Client may have an exclusive lock): {e}")
            print("Try closing eM Client and running again.")
        elif "unable to open" in err_str or "no such file" in err_str:
            print(f"ERROR: Cannot open database: {e}")
        else:
            print(f"ERROR: SQLite error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
