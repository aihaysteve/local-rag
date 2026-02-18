"""Project document indexer for ragling.

Indexes arbitrary document folders (PDF, DOCX, TXT, HTML, MD) into named
project collections. Supports auto-discovery of Obsidian vaults and git repos,
delegating to specialised indexers when markers are found.
"""

from __future__ import annotations

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
from ragling.indexers.discovery import DiscoveredSource, discover_sources, reconcile_sub_collections
from ragling.parsers.code import get_supported_extensions as _get_code_extensions
from ragling.parsers.code import is_code_file
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

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(_EXTENSION_MAP) | _get_code_extensions()


def is_supported_extension(ext: str) -> bool:
    """Check if a file extension is supported for indexing.

    Covers both document extensions (_EXTENSION_MAP) and code extensions
    (_CODE_EXTENSION_MAP from parsers.code).

    Args:
        ext: File extension including the dot (e.g. ".pdf").

    Returns:
        True if the extension is supported for any indexing path.
    """
    return ext in _SUPPORTED_EXTENSIONS


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
        return convert_and_chunk(
            path, doc_store, chunk_max_tokens=config.chunk_size_tokens, source_type=source_type
        )

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


def _merge_results(a: IndexResult, b: IndexResult) -> IndexResult:
    """Merge two IndexResult instances by summing their fields.

    Args:
        a: First result.
        b: Second result.

    Returns:
        A new IndexResult with summed counts.
    """
    return IndexResult(
        indexed=a.indexed + b.indexed,
        skipped=a.skipped + b.skipped,
        skipped_empty=a.skipped_empty + b.skipped_empty,
        pruned=a.pruned + b.pruned,
        errors=a.errors + b.errors,
        total_found=a.total_found + b.total_found,
        error_messages=a.error_messages + b.error_messages,
    )


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

        Runs auto-discovery on each directory path to detect Obsidian vaults
        and git repos. When markers are found, delegates to specialised indexers.
        Falls back to flat indexing when no markers are found anywhere.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            force: If True, re-index all files regardless of change detection.

        Returns:
            IndexResult summarizing the indexing run.
        """
        # Collect discoveries from all directory paths; single files go to leftovers
        all_vaults: list[DiscoveredSource] = []
        all_repos: list[DiscoveredSource] = []
        all_leftovers: list[Path] = []
        single_files: list[Path] = []

        for p in self.paths:
            if p.is_file():
                single_files.append(p)
                continue
            if not p.is_dir():
                logger.warning("Path does not exist: %s", p)
                continue

            discovery = discover_sources(p)
            all_vaults.extend(discovery.vaults)
            all_repos.extend(discovery.repos)
            all_leftovers.extend(discovery.leftover_paths)

            # Reconcile stale sub-collections for this path
            reconcile_sub_collections(conn, self.collection_name, discovery)

        # If no markers found anywhere, fall back to flat indexing
        if not all_vaults and not all_repos:
            return self._index_flat(conn, config, force)

        # Discovery-aware indexing: delegate to specialised indexers
        aggregate = IndexResult()

        # Delegate vaults to ObsidianIndexer
        for vault in all_vaults:
            sub_name = (
                f"{self.collection_name}/{vault.relative_name}"
                if vault.relative_name
                else self.collection_name
            )
            result = self._index_sub_collection(conn, config, vault, sub_name, "project", force)
            aggregate = _merge_results(aggregate, result)

        # Delegate repos to GitRepoIndexer
        for repo in all_repos:
            sub_name = (
                f"{self.collection_name}/{repo.relative_name}"
                if repo.relative_name
                else self.collection_name
            )
            result = self._index_repo(conn, config, repo, sub_name, force)
            aggregate = _merge_results(aggregate, result)

            # Run document pass for non-code files in the repo
            doc_result = self._index_repo_documents(conn, config, repo, sub_name, force)
            aggregate = _merge_results(aggregate, doc_result)

        # Index leftover files (and single files) into the parent project collection
        leftover_files = single_files + [
            f for f in all_leftovers if f.suffix.lower() in _EXTENSION_MAP
        ]
        if leftover_files:
            collection_id = get_or_create_collection(conn, self.collection_name, "project")
            leftover_result = self._index_files(conn, config, leftover_files, collection_id, force)
            leftover_result.pruned = prune_stale_sources(conn, collection_id)
            aggregate = _merge_results(aggregate, leftover_result)

        logger.info(
            "Project indexer done (discovery): %d indexed, %d skipped, %d errors",
            aggregate.indexed,
            aggregate.skipped,
            aggregate.errors,
        )

        return aggregate

    def _index_flat(
        self, conn: sqlite3.Connection, config: Config, force: bool = False
    ) -> IndexResult:
        """Original flat indexing behavior — no discovery delegation.

        Creates the project collection, collects all files, indexes them,
        and prunes stale sources.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            force: If True, re-index all files regardless of change detection.

        Returns:
            IndexResult summarizing the indexing run.
        """
        collection_id = get_or_create_collection(conn, self.collection_name, "project")

        files = _collect_files(self.paths)
        result = self._index_files(conn, config, files, collection_id, force)
        result.pruned = prune_stale_sources(conn, collection_id)

        logger.info(
            "Project indexer done (flat): %d indexed, %d skipped, %d errors out of %d files",
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
    ) -> IndexResult:
        """Index a list of files into a given collection.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            files: List of file paths to index.
            collection_id: Collection ID to index into.
            force: If True, re-index regardless of change detection.

        Returns:
            IndexResult summarizing the indexing run.
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

        return IndexResult(indexed=indexed, skipped=skipped, errors=errors, total_found=total_found)

    def _index_sub_collection(
        self,
        conn: sqlite3.Connection,
        config: Config,
        vault: DiscoveredSource,
        sub_name: str,
        collection_type: str,
        force: bool,
    ) -> IndexResult:
        """Delegate an Obsidian vault to ObsidianIndexer with sub-collection naming.

        Monkey-patches get_or_create_collection in the obsidian module so
        that ObsidianIndexer writes to the correct sub-collection name
        instead of hardcoded "obsidian".

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            vault: The discovered vault source.
            sub_name: Sub-collection name (e.g. "project/my-vault").
            collection_type: Collection type for the sub-collection.
            force: If True, re-index all files.

        Returns:
            IndexResult from the ObsidianIndexer.
        """
        import ragling.indexers.obsidian as obsidian_mod
        from ragling.indexers.obsidian import ObsidianIndexer

        indexer = ObsidianIndexer([vault.path], doc_store=self.doc_store)

        original_func = obsidian_mod.get_or_create_collection  # type: ignore[attr-defined]

        def patched_get_or_create(
            conn: sqlite3.Connection,
            name: str,
            ctype: str = "project",
            description: str | None = None,
        ) -> int:
            return original_func(conn, sub_name, collection_type, description)

        obsidian_mod.get_or_create_collection = patched_get_or_create  # type: ignore[assignment]
        try:
            return indexer.index(conn, config, force=force)
        finally:
            obsidian_mod.get_or_create_collection = original_func  # type: ignore[attr-defined]

    def _index_repo(
        self,
        conn: sqlite3.Connection,
        config: Config,
        repo: DiscoveredSource,
        sub_name: str,
        force: bool,
    ) -> IndexResult:
        """Delegate a git repo to GitRepoIndexer.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            repo: The discovered git repo source.
            sub_name: Sub-collection name (e.g. "project/my-repo").
            force: If True, re-index all files.

        Returns:
            IndexResult from the GitRepoIndexer.
        """
        from ragling.indexers.git_indexer import GitRepoIndexer

        indexer = GitRepoIndexer(repo.path, collection_name=sub_name)
        return indexer.index(conn, config, force=force, index_history=True)

    def _index_repo_documents(
        self,
        conn: sqlite3.Connection,
        config: Config,
        repo: DiscoveredSource,
        sub_name: str,
        force: bool,
    ) -> IndexResult:
        """Index non-code document files found inside a git repo.

        Scans the repo for files with extensions in _EXTENSION_MAP that are
        NOT code files (per is_code_file), and indexes them into the repo's
        sub-collection.

        Args:
            conn: SQLite database connection.
            config: Application configuration.
            repo: The discovered git repo source.
            sub_name: Sub-collection name for the repo.
            force: If True, re-index all files.

        Returns:
            IndexResult summarizing the document indexing.
        """
        collection_id = get_or_create_collection(conn, sub_name, "code")
        doc_files: list[Path] = []
        for item in sorted(repo.path.rglob("*")):
            if not item.is_file() or item.name.startswith("."):
                continue
            rel_parts = item.relative_to(repo.path).parts
            if any(part.startswith(".") for part in rel_parts[:-1]):
                continue
            ext = item.suffix.lower()
            if ext in _EXTENSION_MAP and not is_code_file(item):
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
