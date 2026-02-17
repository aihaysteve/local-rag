"""Abstract base class and shared utilities for indexers."""

import hashlib
import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ragling.chunker import Chunk
from ragling.config import Config
from ragling.embeddings import serialize_float32

logger = logging.getLogger(__name__)


def file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def upsert_source_with_chunks(
    conn: sqlite3.Connection,
    *,
    collection_id: int,
    source_path: str,
    source_type: str,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    file_hash: str | None = None,
    file_modified_at: str | None = None,
) -> int:
    """Upsert a source row with its document chunks and embedding vectors.

    Handles the full persistence cycle shared by all indexers:
    1. Check for existing source
    2. If existing: delete old documents and vectors, update source metadata
    3. If new: insert source row
    4. Insert document rows and vector embeddings
    5. Commit the transaction

    When ``file_hash`` is provided, the UPDATE sets file_hash, file_modified_at,
    source_type, and last_indexed_at. When ``file_hash`` is None (email, RSS,
    git history), only last_indexed_at is updated.

    Args:
        conn: SQLite database connection.
        collection_id: Collection ID to index into.
        source_path: Unique identifier (file path or message ID).
        source_type: Type of source (e.g. 'markdown', 'email', 'code').
        chunks: List of Chunk objects to insert.
        embeddings: List of embedding vectors, parallel to chunks.
        file_hash: Optional content hash for change detection.
        file_modified_at: Optional modification timestamp.

    Returns:
        The source_id of the upserted source.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Check for existing source
    existing = conn.execute(
        "SELECT id FROM sources WHERE collection_id = ? AND source_path = ?",
        (collection_id, source_path),
    ).fetchone()

    if existing:
        source_id = existing["id"]

        # Delete old documents and vectors
        old_doc_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM documents WHERE source_id = ?", (source_id,)
            ).fetchall()
        ]
        if old_doc_ids:
            placeholders = ",".join("?" * len(old_doc_ids))
            conn.execute(
                f"DELETE FROM vec_documents WHERE document_id IN ({placeholders})",
                old_doc_ids,
            )
            conn.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))

        # Update source metadata
        if file_hash is not None:
            conn.execute(
                "UPDATE sources SET file_hash = ?, file_modified_at = ?, "
                "last_indexed_at = ?, source_type = ? WHERE id = ?",
                (file_hash, file_modified_at, now, source_type, source_id),
            )
        else:
            conn.execute(
                "UPDATE sources SET last_indexed_at = ? WHERE id = ?",
                (now, source_id),
            )
    else:
        cursor = conn.execute(
            "INSERT INTO sources (collection_id, source_type, source_path, "
            "file_hash, file_modified_at, last_indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (collection_id, source_type, source_path, file_hash, file_modified_at, now),
        )
        assert cursor.lastrowid is not None
        source_id = cursor.lastrowid

    # Insert new documents and vectors
    for chunk, embedding in zip(chunks, embeddings):
        metadata_json = json.dumps(chunk.metadata) if chunk.metadata else None
        doc_cursor = conn.execute(
            "INSERT INTO documents (source_id, collection_id, chunk_index, "
            "title, content, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, collection_id, chunk.chunk_index, chunk.title, chunk.text, metadata_json),
        )
        assert doc_cursor.lastrowid is not None
        doc_id = doc_cursor.lastrowid
        conn.execute(
            "INSERT INTO vec_documents (embedding, document_id) VALUES (?, ?)",
            (serialize_float32(embedding), doc_id),
        )

    conn.commit()
    return source_id


def delete_source(
    conn: sqlite3.Connection,
    collection_id: int,
    source_path: str,
) -> bool:
    """Delete a source and its documents/vectors from the database.

    Removes the source row, all associated document rows, their FTS entries
    (via trigger), and vector embeddings. No-op if the source doesn't exist.

    Args:
        conn: SQLite database connection.
        collection_id: Collection the source belongs to.
        source_path: The source_path to delete.

    Returns:
        True if a source was deleted, False if it didn't exist.
    """
    existing = conn.execute(
        "SELECT id FROM sources WHERE collection_id = ? AND source_path = ?",
        (collection_id, source_path),
    ).fetchone()

    if not existing:
        return False

    source_id = existing["id"]

    # Delete vectors for all documents of this source
    old_doc_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM documents WHERE source_id = ?", (source_id,)
        ).fetchall()
    ]
    if old_doc_ids:
        placeholders = ",".join("?" * len(old_doc_ids))
        conn.execute(
            f"DELETE FROM vec_documents WHERE document_id IN ({placeholders})",
            old_doc_ids,
        )

    # Delete documents (triggers handle FTS cleanup)
    conn.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))

    # Delete the source row
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    conn.commit()
    logger.info("Deleted source: %s", source_path)
    return True


def prune_stale_sources(conn: sqlite3.Connection, collection_id: int) -> int:
    """Remove sources whose backing files no longer exist on disk.

    Only checks sources that have a file_hash (file-backed) and an absolute
    filesystem path (starts with /). Skips virtual URIs and sources without
    file hashes (email, RSS, git commits).

    Args:
        conn: SQLite database connection.
        collection_id: Collection to prune.

    Returns:
        Number of sources pruned.
    """
    rows = conn.execute(
        "SELECT source_path FROM sources "
        "WHERE collection_id = ? AND file_hash IS NOT NULL AND source_path LIKE '/%'",
        (collection_id,),
    ).fetchall()

    pruned = 0
    for row in rows:
        source_path = row["source_path"]
        if not Path(source_path).exists():
            delete_source(conn, collection_id, source_path)
            pruned += 1

    if pruned:
        logger.info("Pruned %d stale source(s) from collection %d", pruned, collection_id)

    return pruned


@dataclass
class IndexResult:
    """Summary of an indexing run."""

    indexed: int = 0
    skipped: int = 0
    skipped_empty: int = 0
    pruned: int = 0
    errors: int = 0
    total_found: int = 0
    error_messages: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [
            f"Indexed: {self.indexed}",
            f"Skipped: {self.skipped}",
        ]
        if self.skipped_empty:
            parts.append(f"Skipped empty: {self.skipped_empty}")
        if self.pruned:
            parts.append(f"Pruned: {self.pruned}")
        parts.extend(
            [
                f"Errors: {self.errors}",
                f"Total found: {self.total_found}",
            ]
        )
        return ", ".join(parts)


class BaseIndexer(ABC):
    """Abstract base indexer that all source-specific indexers extend."""

    @abstractmethod
    def index(self, conn: sqlite3.Connection, config: Config, force: bool = False) -> IndexResult:
        """Run the indexing process.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            force: If True, re-index all sources regardless of change detection.

        Returns:
            IndexResult summarizing what happened.
        """
