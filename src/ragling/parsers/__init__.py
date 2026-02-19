"""Parsers for external data sources (email, RSS, Calibre, etc.)."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def open_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open a SQLite database in read-only mode.

    Returns None if the database cannot be opened.
    """
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        logger.warning("Cannot open %s: %s", db_path, e)
        return None
