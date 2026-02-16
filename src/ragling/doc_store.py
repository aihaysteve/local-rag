"""Content-addressed SQLite store for caching document conversions.

Multiple MCP instances share this DB via WAL mode. Documents are keyed
by SHA-256 hash of file contents so identical files are never converted twice.
"""

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size INTEGER,
    file_modified_at TEXT,
    discovered_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_path)
);

CREATE TABLE IF NOT EXISTS converted_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    docling_json TEXT NOT NULL,
    format TEXT NOT NULL,
    page_count INTEGER,
    conversion_time_ms INTEGER,
    converted_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);
CREATE INDEX IF NOT EXISTS idx_converted_source ON converted_documents(source_id);
"""


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class DocStore:
    """Content-addressed document conversion cache backed by SQLite.

    The store tracks source files by path and content hash. When a file
    is requested via ``get_or_convert``, the store checks whether the
    current file hash matches the cached version. On a cache hit the
    stored JSON is returned directly; on a miss the supplied converter
    callable is invoked, and the result is serialised and stored.
    """

    def __init__(self, db_path: Path) -> None:
        """Open or create the shared document store with WAL mode.

        Args:
            db_path: Path to the SQLite database file. Parent directories
                     are created automatically if they don't exist.
        """
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

        logger.info("DocStore opened at %s", db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_convert(self, path: Path, converter: Callable[[Path], Any]) -> Any:
        """Content-addressed lookup with lazy conversion.

        If the file at *path* has already been converted and its content
        hash has not changed, the cached result is returned without
        invoking *converter*. Otherwise *converter(path)* is called, the
        result is JSON-serialised and stored, and then returned.

        Args:
            path: Filesystem path to the source document.
            converter: A callable that accepts a ``Path`` and returns an
                       arbitrary JSON-serialisable value.

        Returns:
            The (possibly cached) conversion result.
        """
        content_hash = _file_hash(path)

        # Check for existing source row
        row = self._conn.execute(
            "SELECT id, content_hash FROM sources WHERE source_path = ?",
            (str(path),),
        ).fetchone()

        if row is not None:
            source_id = row["id"]
            cached_hash = row["content_hash"]

            if cached_hash == content_hash:
                # Hash matches -- look up cached conversion
                doc_row = self._conn.execute(
                    "SELECT docling_json FROM converted_documents "
                    "WHERE source_id = ? AND content_hash = ?",
                    (source_id, content_hash),
                ).fetchone()
                if doc_row is not None:
                    logger.debug("Cache hit for %s", path)
                    return json.loads(doc_row["docling_json"])

            # Hash changed -- remove stale conversion data
            self._conn.execute(
                "DELETE FROM converted_documents WHERE source_id = ?",
                (source_id,),
            )
        else:
            source_id = None

        # Cache miss or stale -- run conversion
        logger.info("Converting %s (hash %s)", path, content_hash)
        start = time.monotonic_ns()
        result = converter(path)
        elapsed_ms = (time.monotonic_ns() - start) // 1_000_000

        stat = path.stat()
        file_size = stat.st_size
        file_mtime = stat.st_mtime

        if source_id is not None:
            # Update existing source row with new hash
            self._conn.execute(
                "UPDATE sources SET content_hash = ?, file_size = ?, "
                "file_modified_at = ? WHERE id = ?",
                (content_hash, file_size, str(file_mtime), source_id),
            )
        else:
            cursor = self._conn.execute(
                "INSERT INTO sources (source_path, content_hash, file_size, file_modified_at) "
                "VALUES (?, ?, ?, ?)",
                (str(path), content_hash, file_size, str(file_mtime)),
            )
            source_id = cursor.lastrowid

        # Determine format from file extension
        fmt = path.suffix.lstrip(".") or "unknown"

        self._conn.execute(
            "INSERT INTO converted_documents "
            "(source_id, content_hash, docling_json, format, conversion_time_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, content_hash, json.dumps(result), fmt, elapsed_ms),
        )
        self._conn.commit()

        return result

    def get_document(self, source_path: str) -> Any | None:
        """Retrieve a cached conversion by source path.

        Args:
            source_path: The original filesystem path of the source.

        Returns:
            The deserialised conversion result, or ``None`` if not cached.
        """
        row = self._conn.execute(
            "SELECT cd.docling_json "
            "FROM converted_documents cd "
            "JOIN sources s ON s.id = cd.source_id "
            "WHERE s.source_path = ?",
            (source_path,),
        ).fetchone()

        if row is None:
            return None
        return json.loads(row["docling_json"])

    def invalidate(self, source_path: str) -> None:
        """Remove a cached conversion and its source record.

        If *source_path* is not in the store this is a no-op.

        Args:
            source_path: The original filesystem path of the source.
        """
        row = self._conn.execute(
            "SELECT id FROM sources WHERE source_path = ?",
            (source_path,),
        ).fetchone()

        if row is None:
            return

        source_id = row["id"]
        self._conn.execute(
            "DELETE FROM converted_documents WHERE source_id = ?",
            (source_id,),
        )
        self._conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        self._conn.commit()
        logger.info("Invalidated cached conversion for %s", source_path)

    def list_sources(self) -> list[dict[str, Any]]:
        """List all known sources with their conversion metadata.

        Returns:
            A list of dicts, each containing at least ``source_path`` and
            ``content_hash`` keys.
        """
        rows = self._conn.execute(
            "SELECT source_path, content_hash, file_size, "
            "file_modified_at, discovered_at FROM sources"
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
        logger.debug("DocStore connection closed")
