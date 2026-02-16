"""Project document indexer for ragling.

Indexes arbitrary document folders (PDF, DOCX, TXT, HTML, MD) into named
project collections.
"""

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ragling.chunker import Chunk, chunk_markdown
from ragling.config import Config
from ragling.db import get_or_create_collection
from ragling.doc_store import DocStore
from ragling.docling_convert import DOCLING_FORMATS, convert_and_chunk
from ragling.embeddings import get_embeddings, serialize_float32
from ragling.indexers.base import BaseIndexer, IndexResult
from ragling.parsers.markdown import parse_markdown

logger = logging.getLogger(__name__)

# Extensions mapped to source types
_EXTENSION_MAP: dict[str, str] = {
    # Docling-handled formats
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".epub": "epub",
    ".txt": "plaintext",
    ".tex": "latex",
    ".latex": "latex",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".csv": "csv",
    ".adoc": "asciidoc",
    # Legacy-handled formats
    ".md": "markdown",
    ".json": "plaintext",
    ".yaml": "plaintext",
    ".yml": "plaintext",
}


def _file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def _is_hidden(path: Path) -> bool:
    """Check if any component of the path starts with a dot."""
    return any(part.startswith(".") for part in path.parts)


def _collect_files(paths: list[Path]) -> list[Path]:
    """Collect all indexable files from the given paths.

    Walks directories recursively, skipping hidden files and directories.
    Single files are included directly if they have a supported extension.
    """
    files: list[Path] = []
    for p in paths:
        if p.is_file():
            if not _is_hidden(p) and p.suffix.lower() in _EXTENSION_MAP:
                files.append(p)
            elif p.suffix.lower() not in _EXTENSION_MAP:
                logger.warning("Unsupported file extension, skipping: %s", p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if not child.is_file():
                    continue
                if _is_hidden(child):
                    continue
                if child.suffix.lower() in _EXTENSION_MAP:
                    files.append(child)
                else:
                    logger.debug("Skipping unsupported extension: %s", child)
        else:
            logger.warning("Path does not exist: %s", p)
    return files


def _parse_and_chunk(
    path: Path,
    source_type: str,
    config: Config,
    doc_store: DocStore | None = None,
) -> list[Chunk]:
    """Parse a file and return chunks based on its type."""
    # Route Docling-handled formats through Docling when doc_store is available
    if source_type in DOCLING_FORMATS and doc_store is not None:
        return convert_and_chunk(path, doc_store)

    # Legacy markdown path (Obsidian-flavored, handles wikilinks/frontmatter)
    if source_type == "markdown":
        chunk_size = config.chunk_size_tokens
        overlap = config.chunk_overlap_tokens
        text = path.read_text(encoding="utf-8", errors="replace")
        doc = parse_markdown(text, path.name)
        chunks = chunk_markdown(doc.body_text, doc.title, chunk_size, overlap)
        for chunk in chunks:
            if doc.tags:
                chunk.metadata["tags"] = doc.tags
            if doc.links:
                chunk.metadata["links"] = doc.links
        return chunks

    logger.warning("Unknown source type '%s' for %s", source_type, path)
    return []


class ProjectIndexer(BaseIndexer):
    """Indexes documents from file paths into a named project collection."""

    def __init__(
        self,
        collection_name: str,
        paths: list[Path],
        doc_store: DocStore | None = None,
    ) -> None:
        """Initialize the project indexer.

        Args:
            collection_name: Name for the project collection.
            paths: List of file or directory paths to index.
            doc_store: Optional shared document store for Docling conversion caching.
        """
        self.collection_name = collection_name
        self.paths = paths
        self.doc_store = doc_store

    def index(self, conn: sqlite3.Connection, config: Config, force: bool = False) -> IndexResult:
        """Index all supported files into the project collection.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            force: If True, re-index all files regardless of change detection.

        Returns:
            IndexResult summarizing the indexing run.
        """
        collection_id = get_or_create_collection(conn, self.collection_name, "project")

        files = _collect_files(self.paths)
        total_found = len(files)
        indexed = 0
        skipped = 0
        errors = 0

        logger.info(
            "Project indexer: found %d files for collection '%s'",
            total_found,
            self.collection_name,
        )

        for file_path in files:
            try:
                was_indexed = self._index_file(conn, config, file_path, collection_id, force)
                if was_indexed:
                    indexed += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error("Error indexing %s: %s", file_path, e)
                errors += 1

        logger.info(
            "Project indexer done: %d indexed, %d skipped, %d errors out of %d files",
            indexed,
            skipped,
            errors,
            total_found,
        )

        return IndexResult(indexed=indexed, skipped=skipped, errors=errors, total_found=total_found)

    def _index_file(
        self,
        conn: sqlite3.Connection,
        config: Config,
        file_path: Path,
        collection_id: int,
        force: bool,
    ) -> bool:
        """Index a single file into the collection.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            file_path: Path to the file.
            collection_id: Collection ID to index into.
            force: If True, re-index regardless of change detection.

        Returns:
            True if the file was indexed, False if skipped (unchanged).
        """
        source_path = str(file_path.resolve())
        file_h = _file_hash(file_path)
        ext = file_path.suffix.lower()
        source_type = _EXTENSION_MAP.get(ext, "plaintext")

        # Check if already indexed with same hash
        if not force:
            row = conn.execute(
                "SELECT id, file_hash FROM sources WHERE collection_id = ? AND source_path = ?",
                (collection_id, source_path),
            ).fetchone()
            if row and row["file_hash"] == file_h:
                logger.debug("Unchanged, skipping: %s", file_path)
                return False

        # Parse and chunk
        chunks = _parse_and_chunk(file_path, source_type, config, doc_store=self.doc_store)
        if not chunks:
            logger.warning("No content extracted from %s, skipping", file_path)
            return False

        # Generate embeddings
        texts = [c.text for c in chunks]
        embeddings = get_embeddings(texts, config)

        now = datetime.now(timezone.utc).isoformat()
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).isoformat()

        # Insert/update within a transaction
        # Delete old data for this source if it exists
        existing = conn.execute(
            "SELECT id FROM sources WHERE collection_id = ? AND source_path = ?",
            (collection_id, source_path),
        ).fetchone()

        if existing:
            source_id = existing["id"]
            # Delete old documents (cascade will handle vec_documents via triggers
            # but vec_documents doesn't cascade, so delete explicitly)
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
            conn.execute(
                "UPDATE sources SET file_hash = ?, file_modified_at = ?, "
                "last_indexed_at = ?, source_type = ? WHERE id = ?",
                (file_h, mtime, now, source_type, source_id),
            )
        else:
            cursor = conn.execute(
                "INSERT INTO sources (collection_id, source_type, source_path, "
                "file_hash, file_modified_at, last_indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (collection_id, source_type, source_path, file_h, mtime, now),
            )
            source_id = cursor.lastrowid

        # Insert new documents and embeddings
        for chunk, embedding in zip(chunks, embeddings):
            metadata_json = json.dumps(chunk.metadata) if chunk.metadata else None
            cursor = conn.execute(
                "INSERT INTO documents (source_id, collection_id, chunk_index, "
                "title, content, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    source_id,
                    collection_id,
                    chunk.chunk_index,
                    chunk.title,
                    chunk.text,
                    metadata_json,
                ),
            )
            doc_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO vec_documents (embedding, document_id) VALUES (?, ?)",
                (serialize_float32(embedding), doc_id),
            )

        conn.commit()
        logger.info("Indexed %s (%d chunks)", file_path, len(chunks))
        return True
