"""Project document indexer for ragling.

Indexes arbitrary document folders (PDF, DOCX, TXT, HTML, MD) into named
project collections using flat file collection and format-based routing.

Note: For directory-based sources (home, global, obsidian, code groups, watch),
the unified DFS walker pipeline in walker.py / walk_processor.py is the primary
path. ProjectIndexer remains as a fallback for queue-based "directory" jobs
and the CLI ``ragling index project`` command.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ragling.config import Config

if TYPE_CHECKING:
    from ragling.doc_store import DocStore
    from ragling.indexing_status import IndexingStatus

# Pre-load document tree before indexers.base to break circular import:
# indexers.base → document.chunker → document.__init__ → docling_convert → doc_store → indexers.base
from ragling.document.chunker import Chunk as _Chunk  # noqa: F401

from ragling.db import get_or_create_collection
from ragling.embeddings import get_embeddings
from ragling.indexers.base import (
    BaseIndexer,
    IndexResult,
    file_hash,
    prune_stale_sources,
    upsert_source_with_chunks,
)
from ragling.indexers.format_routing import (
    EXTENSION_MAP,
    SUPPORTED_EXTENSIONS as _SUPPORTED_EXTENSIONS,  # noqa: F401 — re-exported for watcher.py
    is_supported_extension,  # noqa: F401 — re-exported public API
    parse_and_chunk,
)
from ragling.parsers.code import is_code_file
from ragling.parsers.spec import is_spec_file

logger = logging.getLogger(__name__)

# Re-export under the old private name for backward compatibility.
# _SUPPORTED_EXTENSIONS is used by watcher.py (imported at runtime inside a function).
# is_supported_extension is used by test_project_indexer.py and external callers.
_EXTENSION_MAP = EXTENSION_MAP


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
            if not _is_hidden(p) and p.suffix.lower() in EXTENSION_MAP:
                files.append(p)
            elif p.suffix.lower() not in EXTENSION_MAP:
                logger.warning("Unsupported file extension, skipping: %s", p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if not child.is_file():
                    continue
                if _is_hidden(child):
                    continue
                if child.suffix.lower() in EXTENSION_MAP:
                    files.append(child)
                else:
                    logger.debug("Skipping unsupported extension: %s", child)
        else:
            logger.warning("Path does not exist: %s", p)
    return files


class ProjectIndexer(BaseIndexer):
    """Indexes documents from file paths into a named project collection.

    Uses flat file collection — walks directories, indexes all supported files.
    For smarter context-aware indexing (vault/repo detection, exclusions),
    use the unified walker pipeline instead.
    """

    def __init__(
        self,
        collection_name: str,
        paths: list[Path],
        doc_store: DocStore | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.paths = paths
        self.doc_store = doc_store

    def index(
        self,
        conn: sqlite3.Connection,
        config: Config,
        force: bool = False,
        *,
        status: IndexingStatus | None = None,
    ) -> IndexResult:
        """Index all supported files into the project collection.

        Collects files from all paths, indexes them, and prunes stale sources.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            force: If True, re-index all files regardless of change detection.
            status: Optional indexing status tracker for file-level progress.

        Returns:
            IndexResult summarizing the indexing run.
        """
        collection_id = get_or_create_collection(conn, self.collection_name, "project")

        files = _collect_files(self.paths)
        result = self._index_files(conn, config, files, collection_id, force, status=status)
        result.pruned = prune_stale_sources(conn, collection_id)

        logger.info(
            "Project indexer done: %d indexed, %d skipped, %d errors out of %d files",
            result.indexed,
            result.skipped,
            result.errors,
            result.total_found,
        )

        return result

    def _index_files(
        self,
        conn: sqlite3.Connection,
        config: Config,
        files: list[Path],
        collection_id: int,
        force: bool,
        *,
        status: IndexingStatus | None = None,
    ) -> IndexResult:
        """Index a list of files into a given collection.

        Uses a two-pass approach: first scans for changed files (fast hash
        check), then indexes only the changed files with per-file progress.
        """
        total_found = len(files)
        indexed = 0
        skipped = 0
        errors = 0

        logger.info(
            "Project indexer: found %d files for collection '%s'",
            total_found,
            self.collection_name,
        )

        # Scan pass: identify changed files
        changed_files: list[tuple[Path, str, int]] = []  # (path, hash, size)
        for file_path in files:
            file_h = file_hash(file_path)
            if not force:
                source_path = str(file_path.resolve())
                row = conn.execute(
                    "SELECT id, file_hash FROM sources WHERE collection_id = ? AND source_path = ?",
                    (collection_id, source_path),
                ).fetchone()
                if row and row["file_hash"] == file_h:
                    skipped += 1
                    continue
            file_size = file_path.stat().st_size
            changed_files.append((file_path, file_h, file_size))

        # Report file-level totals
        if status and changed_files:
            total_bytes = sum(size for _, _, size in changed_files)
            status.set_file_total(self.collection_name, len(changed_files), total_bytes)

        # Index pass: process changed files with per-file status ticks
        for file_path, file_h, file_size in changed_files:
            try:
                was_indexed = self._index_file(
                    conn, config, file_path, collection_id, force, precomputed_hash=file_h
                )
                if was_indexed:
                    indexed += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error("Error indexing %s: %s", file_path, e)
                errors += 1
            finally:
                if status:
                    status.file_processed(self.collection_name, 1, file_size)

        return IndexResult(indexed=indexed, skipped=skipped, errors=errors, total_found=total_found)

    def _index_repo_documents(
        self,
        conn: sqlite3.Connection,
        config: Config,
        repo_path: Path,
        sub_name: str,
        force: bool,
    ) -> IndexResult:
        """Index non-code document files found inside a git repo.

        Scans the repo for files with extensions in EXTENSION_MAP that are
        NOT code files (per is_code_file), and indexes them into the repo's
        sub-collection.
        """
        collection_id = get_or_create_collection(conn, sub_name, "code")
        doc_files: list[Path] = []
        for item in sorted(repo_path.rglob("*")):
            if not item.is_file() or item.name.startswith("."):
                continue
            rel_parts = item.relative_to(repo_path).parts
            if any(part.startswith(".") for part in rel_parts[:-1]):
                continue
            ext = item.suffix.lower()
            if ext in EXTENSION_MAP and not is_code_file(item):
                doc_files.append(item)
        if not doc_files:
            return IndexResult()
        return self._index_files(conn, config, doc_files, collection_id, force)

    def _index_file(
        self,
        conn: sqlite3.Connection,
        config: Config,
        file_path: Path,
        collection_id: int,
        force: bool,
        precomputed_hash: str | None = None,
    ) -> bool:
        """Index a single file into the collection."""
        source_path = str(file_path.resolve())
        file_h = precomputed_hash or file_hash(file_path)
        ext = file_path.suffix.lower()
        if is_spec_file(file_path):
            source_type = "spec"
        else:
            source_type = EXTENSION_MAP.get(ext, "plaintext")

        # Check if already indexed with same hash (skip when hash was pre-checked)
        if not force and precomputed_hash is None:
            row = conn.execute(
                "SELECT id, file_hash FROM sources WHERE collection_id = ? AND source_path = ?",
                (collection_id, source_path),
            ).fetchone()
            if row and row["file_hash"] == file_h:
                logger.debug("Unchanged, skipping: %s", file_path)
                return False

        # Parse and chunk
        chunks = parse_and_chunk(
            file_path,
            source_type,
            config,
            doc_store=self.doc_store,
            source_path=source_path,
        )
        if not chunks:
            logger.warning("No content extracted from %s, skipping", file_path)
            return False

        # Generate embeddings
        texts = [c.text for c in chunks]
        embeddings = get_embeddings(texts, config)

        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).isoformat()
        upsert_source_with_chunks(
            conn,
            collection_id=collection_id,
            source_path=source_path,
            source_type=source_type,
            chunks=chunks,
            embeddings=embeddings,
            file_hash=file_h,
            file_modified_at=mtime,
        )
        logger.info("Indexed %s [%s] (%d chunks)", file_path, source_type, len(chunks))
        return True
