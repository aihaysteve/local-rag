"""Obsidian vault indexer for ragling.

Indexes all supported file types found in Obsidian vaults (markdown, PDF,
DOCX, HTML, plaintext, etc.) into the "obsidian" system collection.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ragling.config import Config
from ragling.db import get_or_create_collection
from ragling.doc_store import DocStore
from ragling.embeddings import get_embeddings
from ragling.indexers.base import (
    BaseIndexer,
    IndexResult,
    file_hash,
    prune_stale_sources,
    upsert_source_with_chunks,
)
from ragling.indexers.project import _EXTENSION_MAP, _parse_and_chunk

logger = logging.getLogger(__name__)

# Directories to skip when walking an Obsidian vault
_SKIP_DIRS = {".obsidian", ".trash", ".git"}


class ObsidianIndexer(BaseIndexer):
    """Indexes all supported files in Obsidian vaults."""

    def __init__(
        self,
        vault_paths: list[Path],
        exclude_folders: list[str] | None = None,
        doc_store: DocStore | None = None,
    ) -> None:
        self.vault_paths = vault_paths
        self.exclude_folders = set(exclude_folders or [])
        self.doc_store = doc_store

    def index(
        self,
        conn: sqlite3.Connection,
        config: Config,
        force: bool = False,
    ) -> IndexResult:
        """Index all configured Obsidian vaults.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            force: If True, re-index all files regardless of hash match.

        Returns:
            IndexResult with counts of indexed/skipped/errored files.
        """
        collection_id = get_or_create_collection(conn, "obsidian", "system")

        total_found = 0
        indexed = 0
        skipped = 0
        errors = 0

        for vault_path in self.vault_paths:
            vault_path = vault_path.expanduser().resolve()
            if not vault_path.is_dir():
                logger.warning("Vault path does not exist or is not a directory: %s", vault_path)
                errors += 1
                continue

            logger.info("Indexing Obsidian vault: %s", vault_path)
            files = _walk_vault(vault_path, self.exclude_folders)
            total_found += len(files)
            logger.info("Found %d supported files in %s", len(files), vault_path)

            for file_path in files:
                try:
                    result = _index_file(
                        conn, config, collection_id, file_path, force, doc_store=self.doc_store
                    )
                    if result == "indexed":
                        indexed += 1
                    elif result == "skipped":
                        skipped += 1
                except Exception:
                    logger.exception("Error indexing %s", file_path)
                    errors += 1

        pruned = prune_stale_sources(conn, collection_id)

        logger.info(
            "Obsidian indexing complete: %d found, %d indexed, %d skipped, %d errors",
            total_found,
            indexed,
            skipped,
            errors,
        )
        return IndexResult(
            indexed=indexed, skipped=skipped, errors=errors, total_found=total_found, pruned=pruned
        )


def _walk_vault(vault_path: Path, exclude_folders: set[str] | None = None) -> list[Path]:
    """Walk an Obsidian vault, yielding all supported files while skipping hidden/system dirs."""
    exclude = exclude_folders or set()
    results: list[Path] = []
    for item in sorted(vault_path.rglob("*")):
        if not item.is_file():
            continue
        # Skip files in hidden, system, or user-excluded directories
        parts = item.relative_to(vault_path).parts
        if any(
            part.startswith(".") or part in _SKIP_DIRS or part in exclude for part in parts[:-1]
        ):
            continue
        # Skip hidden files
        if item.name.startswith("."):
            continue
        # Only include files with supported extensions
        if item.suffix.lower() not in _EXTENSION_MAP:
            logger.debug("Skipping unsupported extension in vault: %s", item.name)
            continue
        results.append(item)
    return results


def _index_file(
    conn: sqlite3.Connection,
    config: Config,
    collection_id: int,
    file_path: Path,
    force: bool,
    doc_store: DocStore | None = None,
) -> str:
    """Index a single file of any supported type.

    Returns:
        'indexed' if the file was processed, 'skipped' if unchanged.
    """
    source_path = str(file_path)
    content_hash = file_hash(file_path)
    source_type = _EXTENSION_MAP.get(file_path.suffix.lower(), "plaintext")
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).isoformat()

    # Check if source already exists with same hash
    if not force:
        row = conn.execute(
            "SELECT id, file_hash FROM sources WHERE collection_id = ? AND source_path = ?",
            (collection_id, source_path),
        ).fetchone()
        if row and row["file_hash"] == content_hash:
            logger.debug("Skipping unchanged file: %s", file_path.name)
            return "skipped"

    # Parse and chunk using the shared dispatch from project indexer
    chunks = _parse_and_chunk(file_path, source_type, config, doc_store=doc_store)
    if not chunks:
        logger.warning("No content extracted from %s, skipping", file_path)
        return "skipped"

    # Embed all chunks in a batch
    chunk_texts = [c.text for c in chunks]
    embeddings = get_embeddings(chunk_texts, config)

    upsert_source_with_chunks(
        conn,
        collection_id=collection_id,
        source_path=source_path,
        source_type=source_type,
        chunks=chunks,
        embeddings=embeddings,
        file_hash=content_hash,
        file_modified_at=mtime,
    )
    logger.info("Indexed %s [%s] (%d chunks)", file_path.name, source_type, len(chunks))
    return "indexed"
