"""Calibre library indexer for ragling.

Indexes ebooks from Calibre libraries into the "calibre" system collection,
enriching every chunk with book-level metadata (authors, tags, series, etc.).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragling.indexing_status import IndexingStatus

from ragling.chunker import Chunk
from ragling.config import Config
from ragling.db import get_or_create_collection
from ragling.doc_store import DocStore
from ragling.docling_bridge import epub_to_docling_doc, plaintext_to_docling_doc
from ragling.docling_convert import chunk_with_hybrid, convert_and_chunk
from ragling.embeddings import get_embeddings
from ragling.indexers.base import (
    BaseIndexer,
    IndexResult,
    file_hash,
    prune_stale_sources,
    upsert_source_with_chunks,
)
from ragling.parsers.calibre import CalibreBook, get_book_file_path, parse_calibre_library

logger = logging.getLogger(__name__)

PREFERRED_FORMATS = ["EPUB", "PDF"]


class CalibreIndexer(BaseIndexer):
    """Indexes ebooks from Calibre libraries with rich metadata."""

    def __init__(self, library_paths: Sequence[Path], doc_store: DocStore | None = None) -> None:
        self.library_paths = library_paths
        self.doc_store = doc_store

    def index(
        self,
        conn: sqlite3.Connection,
        config: Config,
        force: bool = False,
        *,
        status: IndexingStatus | None = None,
    ) -> IndexResult:
        """Index all configured Calibre libraries.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            force: If True, re-index all books regardless of hash match.
            status: Optional indexing status tracker for file-level progress.

        Returns:
            IndexResult with counts of indexed/skipped/errored books.
        """
        collection_id = get_or_create_collection(conn, "calibre", "system")

        total_found = 0
        indexed = 0
        skipped = 0
        errors = 0

        # Collect all books to index across libraries (scan pass)
        books_to_index: list[tuple[Path, CalibreBook, str, int]] = []
        # (library_path, book, content_hash, file_size)

        for library_path in self.library_paths:
            library_path = library_path.expanduser().resolve()
            if not library_path.is_dir():
                logger.warning("Calibre library path does not exist: %s", library_path)
                errors += 1
                continue

            logger.info("Indexing Calibre library: %s", library_path)
            books = parse_calibre_library(library_path)
            total_found += len(books)
            logger.info("Found %d books in %s", len(books), library_path)

            # Scan pass: identify changed books
            for book in books:
                file_info = get_book_file_path(library_path, book, PREFERRED_FORMATS)
                if file_info:
                    file_path, _fmt = file_info
                    content_hash = file_hash(file_path)
                    source_path = str(file_path)
                    file_size = file_path.stat().st_size
                else:
                    if not book.description:
                        skipped += 1
                        continue
                    source_path = f"calibre://{library_path}/{book.relative_path}"
                    content_hash = hashlib.sha256(book.description.encode()).hexdigest()
                    file_size = 0

                if not force:
                    row = conn.execute(
                        "SELECT id, file_hash FROM sources "
                        "WHERE collection_id = ? AND source_path = ?",
                        (collection_id, source_path),
                    ).fetchone()
                    if row and row["file_hash"] == content_hash:
                        # Check metadata changes
                        if _metadata_changed(conn, row["id"], book):
                            _refresh_metadata(
                                conn,
                                row["id"],
                                book,
                                library_path,
                                file_info[1] if file_info else None,
                            )
                            conn.commit()
                            logger.info("Metadata refreshed for: %s", book.title)
                            indexed += 1
                        else:
                            skipped += 1
                        continue

                books_to_index.append((library_path, book, content_hash, file_size))

        # Report file-level totals
        if status and books_to_index:
            total_bytes = sum(size for _, _, _, size in books_to_index)
            status.set_file_total("calibre", len(books_to_index), total_bytes)

        # Index pass: process changed books with per-file status ticks
        for library_path, book, content_hash, file_size in books_to_index:
            try:
                result = _index_book(
                    conn,
                    config,
                    collection_id,
                    library_path,
                    book,
                    force,
                    doc_store=self.doc_store,
                    precomputed_hash=content_hash,
                )
                if result == "indexed":
                    indexed += 1
                elif result == "skipped":
                    skipped += 1
            except Exception:
                logger.exception("Error indexing book: %s", book.title)
                errors += 1
            finally:
                if status:
                    status.file_processed("calibre", 1, file_size)

        pruned = prune_stale_sources(conn, collection_id)

        logger.info(
            "Calibre indexing complete: %d found, %d indexed, %d skipped, %d errors",
            total_found,
            indexed,
            skipped,
            errors,
        )
        return IndexResult(
            indexed=indexed, skipped=skipped, errors=errors, total_found=total_found, pruned=pruned
        )


def _build_book_metadata(book: CalibreBook, library_path: Path, fmt: str | None) -> dict:
    """Build the metadata dict to attach to every chunk of a book."""
    meta: dict = {}
    if book.authors:
        meta["authors"] = book.authors
    if book.tags:
        meta["tags"] = book.tags
    if book.series:
        meta["series"] = book.series
    if book.series_index is not None:
        meta["series_index"] = book.series_index
    if book.publisher:
        meta["publisher"] = book.publisher
    if book.pubdate:
        meta["pubdate"] = book.pubdate
    if book.rating is not None:
        meta["rating"] = book.rating
    if book.languages:
        meta["languages"] = book.languages
    if book.identifiers:
        meta["identifiers"] = book.identifiers
    meta["calibre_id"] = book.book_id
    if fmt:
        meta["format"] = fmt
    meta["library"] = str(library_path)
    return meta


def _index_book(
    conn: sqlite3.Connection,
    config: Config,
    collection_id: int,
    library_path: Path,
    book: CalibreBook,
    force: bool,
    doc_store: DocStore | None = None,
    precomputed_hash: str | None = None,
) -> str:
    """Index a single Calibre book.

    Args:
        conn: SQLite database connection.
        config: Application configuration.
        collection_id: Collection ID to index into.
        library_path: Path to the Calibre library.
        book: CalibreBook metadata.
        force: If True, re-index regardless of change detection.
        doc_store: Optional shared document store.
        precomputed_hash: Pre-computed content hash (avoids recomputation
            when the scan pass already computed it).

    Returns:
        'indexed' if the book was processed, 'skipped' if unchanged.
    """
    file_info = get_book_file_path(library_path, book, PREFERRED_FORMATS)

    if file_info:
        file_path, fmt = file_info
        source_path = str(file_path)
        content_hash = precomputed_hash or file_hash(file_path)
        source_type = fmt  # "epub" or "pdf"
    else:
        # No EPUB or PDF available — index description only if available
        if not book.description:
            logger.warning("Book '%s' has no EPUB/PDF and no description, skipping", book.title)
            return "skipped"
        source_path = f"calibre://{library_path}/{book.relative_path}"
        content_hash = precomputed_hash or hashlib.sha256(book.description.encode()).hexdigest()
        source_type = "calibre-description"
        fmt = None

    # Check if source already exists with same hash (skip when hash was pre-checked)
    if not force and precomputed_hash is None:
        row = conn.execute(
            "SELECT id, file_hash FROM sources WHERE collection_id = ? AND source_path = ?",
            (collection_id, source_path),
        ).fetchone()
        if row and row["file_hash"] == content_hash:
            # File content unchanged — check if metadata changed
            if _metadata_changed(conn, row["id"], book):
                _refresh_metadata(conn, row["id"], book, library_path, fmt)
                conn.commit()
                logger.info("Metadata refreshed for: %s", book.title)
                return "indexed"
            logger.debug("Skipping unchanged book: %s", book.title)
            return "skipped"

    # Build chunks from book content
    book_meta = _build_book_metadata(book, library_path, fmt)
    chunks = _extract_and_chunk_book(book, file_info, config, book_meta, doc_store=doc_store)

    if not chunks:
        logger.warning("No content extracted from book '%s', skipping", book.title)
        return "skipped"

    # Embed all chunks
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
        file_modified_at=book.last_modified,
    )
    logger.info("Indexed book: %s [%s] (%d chunks)", book.title, source_type, len(chunks))
    return "indexed"


def _extract_and_chunk_book(
    book: CalibreBook,
    file_info: tuple[Path, str] | None,
    config: Config,
    book_meta: dict,
    doc_store: DocStore | None = None,
) -> list[Chunk]:
    """Extract text from the book file and produce enriched chunks."""
    chunks: list[Chunk] = []
    chunk_idx = 0

    if file_info:
        file_path, fmt = file_info

        if doc_store is not None and fmt == "pdf":
            # Use Docling for PDF conversion via shared doc store
            docling_chunks = convert_and_chunk(
                file_path, doc_store, chunk_max_tokens=config.chunk_size_tokens
            )
            for chunk in docling_chunks:
                chunk.chunk_index = chunk_idx
                meta = dict(book_meta)
                meta.update(chunk.metadata)
                chunk.metadata = meta
                chunks.append(chunk)
                chunk_idx += 1
        elif fmt == "epub":
            # EPUB: parse with legacy parser, chunk with HybridChunker
            from ragling.parsers.epub import parse_epub

            epub_chapters = parse_epub(file_path)
            docling_doc = epub_to_docling_doc(epub_chapters, book.title)
            epub_chunks = chunk_with_hybrid(
                docling_doc,
                title=book.title,
                source_path=str(file_path),
                chunk_max_tokens=config.chunk_size_tokens,
            )
            for chunk in epub_chunks:
                chunk.chunk_index = chunk_idx
                meta = dict(book_meta)
                meta.update(chunk.metadata)
                chunk.metadata = meta
                chunks.append(chunk)
                chunk_idx += 1
        elif fmt == "pdf" and doc_store is None:
            logger.error(
                "PDF format requires doc_store for Docling conversion but none was provided "
                "— this indicates a configuration error. Skipping book file content for '%s'",
                book.title,
            )
        else:
            logger.warning(
                "Unexpected format '%s' for book '%s', skipping file content",
                fmt,
                book.title,
            )

    # Add description chunk(s) if available
    if book.description:
        desc_title = f"{book.title} (description)"
        docling_doc = plaintext_to_docling_doc(book.description, desc_title)
        desc_chunks = chunk_with_hybrid(
            docling_doc,
            title=desc_title,
            source_path=f"calibre://{book.title}/description",
            chunk_max_tokens=config.chunk_size_tokens,
        )
        for chunk in desc_chunks:
            chunk.chunk_index = chunk_idx
            meta = dict(book_meta)
            meta["chunk_type"] = "description"
            meta.update(chunk.metadata)
            chunk.metadata = meta
            chunks.append(chunk)
            chunk_idx += 1

    return chunks


def _metadata_changed(conn: sqlite3.Connection, source_id: int, book: CalibreBook) -> bool:
    """Check if Calibre metadata has changed since last index by comparing a sample doc's metadata."""
    row = conn.execute(
        "SELECT metadata FROM documents WHERE source_id = ? LIMIT 1",
        (source_id,),
    ).fetchone()
    if not row or not row["metadata"]:
        return True

    stored_meta = json.loads(row["metadata"])
    # Compare key metadata fields — use `or None` to match what _build_book_metadata stores
    # (it skips falsy values, so stored_meta won't have the key for None/[])
    if stored_meta.get("authors") != (book.authors or None):
        return True
    if stored_meta.get("tags") != (book.tags or None):
        return True
    if stored_meta.get("series") != book.series:
        return True
    if stored_meta.get("rating") != book.rating:
        return True
    if stored_meta.get("publisher") != book.publisher:
        return True

    return False


def _refresh_metadata(
    conn: sqlite3.Connection,
    source_id: int,
    book: CalibreBook,
    library_path: Path,
    fmt: str | None,
) -> None:
    """Update metadata JSON on existing document rows without re-embedding."""
    book_meta = _build_book_metadata(book, library_path, fmt)

    rows = conn.execute(
        "SELECT id, metadata FROM documents WHERE source_id = ?",
        (source_id,),
    ).fetchall()

    for row in rows:
        existing_meta = json.loads(row["metadata"]) if row["metadata"] else {}
        # Preserve chunk-specific fields (page_number, chapter_number, chunk_type)
        merged = dict(book_meta)
        for key in ("page_number", "chapter_number", "chunk_type"):
            if key in existing_meta:
                merged[key] = existing_meta[key]

        conn.execute(
            "UPDATE documents SET metadata = ? WHERE id = ?",
            (json.dumps(merged), row["id"]),
        )
