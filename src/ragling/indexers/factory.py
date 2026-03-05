"""Centralized indexer creation and dispatch.

Single source of truth for mapping collection names to indexer instances.
Used by IndexingQueue, CLI, and any other code that needs to create indexers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ragling.indexer_types import IndexerType

if TYPE_CHECKING:
    from ragling.config import Config
    from ragling.doc_store import DocStore
    from ragling.indexers.base import BaseIndexer

logger = logging.getLogger(__name__)


def _build_indexer(
    indexer_type: IndexerType,
    collection: str,
    config: Config,
    path: Path | None,
    doc_store: DocStore | None,
) -> BaseIndexer:
    """Create an indexer instance from a resolved IndexerType.

    Shared construction logic used by both the name-based and
    type-based resolution paths. Lazy-imports indexer classes to
    avoid circular imports.
    """
    from ragling.indexers.calibre_indexer import CalibreIndexer
    from ragling.indexers.email_indexer import EmailIndexer
    from ragling.indexers.git_indexer import GitRepoIndexer
    from ragling.indexers.obsidian import ObsidianIndexer
    from ragling.indexers.project import ProjectIndexer
    from ragling.indexers.rss_indexer import RSSIndexer

    if indexer_type == IndexerType.OBSIDIAN:
        vault_paths = [path] if path else list(config.obsidian_vaults)
        return ObsidianIndexer(vault_paths, config.obsidian_exclude_folders, doc_store=doc_store)

    if indexer_type == IndexerType.EMAIL:
        db_path = str(path) if path else str(config.emclient_db_path)
        return EmailIndexer(db_path)

    if indexer_type == IndexerType.CALIBRE:
        libraries = [path] if path else list(config.calibre_libraries)
        return CalibreIndexer(libraries, doc_store=doc_store)

    if indexer_type == IndexerType.RSS:
        db_path = str(path) if path else str(config.netnewswire_db_path)
        return RSSIndexer(db_path)

    if indexer_type == IndexerType.CODE:
        if path is None:
            raise ValueError(f"Code indexer for '{collection}' requires a path")
        return GitRepoIndexer(path, collection_name=collection)

    if indexer_type == IndexerType.PROJECT:
        paths = [path] if path else []
        return ProjectIndexer(collection, paths, doc_store=doc_store)

    raise ValueError(f"Unknown indexer_type: {indexer_type!r}")


def _resolve_indexer_type(collection: str, config: Config, path: Path | None) -> IndexerType:
    """Resolve collection name to an IndexerType.

    Args:
        collection: Collection name.
        config: Application configuration.
        path: Optional path (needed for watch collections).

    Returns:
        The resolved IndexerType.

    Raises:
        ValueError: If collection is unknown and no path is provided.
    """
    if collection == "obsidian":
        return IndexerType.OBSIDIAN
    if collection == "email":
        return IndexerType.EMAIL
    if collection == "calibre":
        return IndexerType.CALIBRE
    if collection == "rss":
        return IndexerType.RSS

    if collection in config.code_groups:
        return IndexerType.CODE

    if collection in config.watch:
        from ragling.indexers.auto_indexer import detect_directory_type

        if path is None:
            raise ValueError(f"Watch collection '{collection}' requires a path")
        return detect_directory_type(path)

    if path is not None:
        return IndexerType.PROJECT

    raise ValueError(f"Unknown collection '{collection}'. Provide a path for project indexing.")


def create_indexer(
    collection: str,
    config: Config,
    path: Path | None = None,
    doc_store: DocStore | None = None,
    indexer_type: IndexerType | None = None,
) -> BaseIndexer:
    """Create the appropriate indexer for a collection.

    When ``indexer_type`` is provided it takes precedence over
    collection-name-based resolution, allowing callers that already
    know the type (e.g. IndexingQueue) to bypass the name lookup.

    Args:
        collection: Collection name (e.g. "obsidian", "email", a code group name).
        config: Ragling configuration.
        path: Optional path override (for specific repo/directory).
        doc_store: DocStore for formats requiring Docling conversion.
        indexer_type: Optional explicit indexer type. When provided, overrides
            the collection-name-based resolution.

    Returns:
        Configured BaseIndexer instance.

    Raises:
        ValueError: If collection is unknown and no path is provided.
    """
    resolved_type = (
        indexer_type
        if indexer_type is not None
        else _resolve_indexer_type(collection, config, path)
    )

    # Code groups require a path for per-repo indexing
    if resolved_type == IndexerType.CODE and path is None and collection in config.code_groups:
        raise ValueError(f"Code group '{collection}' requires a path (one repo at a time)")

    return _build_indexer(resolved_type, collection, config, path, doc_store)
