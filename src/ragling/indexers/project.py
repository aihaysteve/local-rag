"""Project document indexer for ragling.

Indexes arbitrary document folders (PDF, DOCX, TXT, HTML, MD) into named
project collections.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ragling.chunker import Chunk
from ragling.config import Config
from ragling.db import get_or_create_collection
from ragling.doc_store import DocStore
from ragling.docling_bridge import (
    epub_to_docling_doc,
    markdown_to_docling_doc,
    plaintext_to_docling_doc,
)
from ragling.docling_convert import DOCLING_FORMATS, chunk_with_hybrid, convert_and_chunk
from ragling.embeddings import get_embeddings
from ragling.indexers.base import (
    BaseIndexer,
    IndexResult,
    file_hash,
    prune_stale_sources,
    upsert_source_with_chunks,
)
from ragling.parsers.epub import parse_epub
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
    ".bmp": "image",
    ".webp": "image",
    ".csv": "csv",
    ".adoc": "asciidoc",
    ".vtt": "vtt",
    ".mp3": "audio",
    ".wav": "audio",
    # Legacy-handled formats
    ".md": "markdown",
    ".json": "plaintext",
    ".yaml": "plaintext",
    ".yml": "plaintext",
}


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
    if source_type in DOCLING_FORMATS:
        if doc_store is None:
            logger.error(
                "Format '%s' requires doc_store for Docling conversion but none was provided "
                "— this indicates a configuration error. Skipping %s",
                source_type,
                path,
            )
            return []
        return convert_and_chunk(path, doc_store, chunk_max_tokens=config.chunk_size_tokens)

    # Markdown: parse with legacy parser (preserves Obsidian metadata), chunk with HybridChunker
    if source_type == "markdown":
        text = path.read_text(encoding="utf-8", errors="replace")
        doc = parse_markdown(text, path.name)
        docling_doc = markdown_to_docling_doc(doc.body_text, doc.title)
        extra_metadata: dict[str, list[str]] = {}
        if doc.tags:
            extra_metadata["tags"] = doc.tags
        if doc.links:
            extra_metadata["links"] = doc.links
        return chunk_with_hybrid(
            docling_doc,
            title=doc.title,
            source_path=str(path),
            extra_metadata=extra_metadata or None,
            chunk_max_tokens=config.chunk_size_tokens,
        )

    # EPUB: parse with legacy parser, chunk with HybridChunker
    if source_type == "epub":
        chapters = parse_epub(path)
        docling_doc = epub_to_docling_doc(chapters, path.name)
        return chunk_with_hybrid(
            docling_doc,
            title=path.name,
            source_path=str(path),
            chunk_max_tokens=config.chunk_size_tokens,
        )

    # Plaintext: build minimal DoclingDocument, chunk with HybridChunker
    if source_type == "plaintext":
        text = path.read_text(encoding="utf-8", errors="replace")
        docling_doc = plaintext_to_docling_doc(text, path.name)
        return chunk_with_hybrid(
            docling_doc,
            title=path.name,
            source_path=str(path),
            chunk_max_tokens=config.chunk_size_tokens,
        )

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

        pruned = prune_stale_sources(conn, collection_id)

        logger.info(
            "Project indexer done: %d indexed, %d skipped, %d errors out of %d files",
            indexed,
            skipped,
            errors,
            total_found,
        )

        return IndexResult(
            indexed=indexed, skipped=skipped, errors=errors, total_found=total_found, pruned=pruned
        )

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
        file_h = file_hash(file_path)
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
