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
    from ragling.indexers.calibre_indexer import CalibreIndexer
    from ragling.indexers.email_indexer import EmailIndexer
    from ragling.indexers.git_indexer import GitRepoIndexer
    from ragling.indexers.obsidian import ObsidianIndexer
    from ragling.indexers.project import ProjectIndexer
    from ragling.indexers.rss_indexer import RSSIndexer

    # When explicit indexer_type is provided, use it directly
    if indexer_type is not None:
        return _create_by_type(
            indexer_type,
            collection,
            config,
            path,
            doc_store,
            ObsidianIndexer,
            EmailIndexer,
            CalibreIndexer,
            RSSIndexer,
            GitRepoIndexer,
            ProjectIndexer,
        )

    # Otherwise, resolve from collection name
    if collection == "obsidian":
        vault_paths = [path] if path else list(config.obsidian_vaults)
        return ObsidianIndexer(vault_paths, config.obsidian_exclude_folders, doc_store=doc_store)

    if collection == "email":
        db_path = str(path) if path else str(config.emclient_db_path)
        return EmailIndexer(db_path)

    if collection == "calibre":
        libraries = [path] if path else list(config.calibre_libraries)
        return CalibreIndexer(libraries, doc_store=doc_store)

    if collection == "rss":
        db_path = str(path) if path else str(config.netnewswire_db_path)
        return RSSIndexer(db_path)

    if collection in config.code_groups:
        if path is None:
            raise ValueError(f"Code group '{collection}' requires a path (one repo at a time)")
        return GitRepoIndexer(path, collection_name=collection)

    if collection in config.watch:
        from ragling.indexers.auto_indexer import detect_directory_type

        if path is None:
            raise ValueError(f"Watch collection '{collection}' requires a path")
        dir_type = detect_directory_type(path)
        if dir_type == IndexerType.CODE:
            return GitRepoIndexer(path, collection_name=collection)
        return ProjectIndexer(collection, [path], doc_store=doc_store)

    # Fallback: project indexer with explicit path
    if path is not None:
        return ProjectIndexer(collection, [path], doc_store=doc_store)

    raise ValueError(f"Unknown collection '{collection}'. Provide a path for project indexing.")


def _create_by_type(
    indexer_type: IndexerType,
    collection: str,
    config: Config,
    path: Path | None,
    doc_store: DocStore | None,
    obsidian_cls: type,
    email_cls: type,
    calibre_cls: type,
    rss_cls: type,
    git_cls: type,
    project_cls: type,
) -> BaseIndexer:
    """Create an indexer from an explicit IndexerType.

    This is the type-based path used by the IndexingQueue where the
    indexer type is already known from the IndexJob.
    """
    if indexer_type == IndexerType.OBSIDIAN:
        vault_paths = [path] if path else list(config.obsidian_vaults)
        return obsidian_cls(vault_paths, config.obsidian_exclude_folders, doc_store=doc_store)

    if indexer_type == IndexerType.EMAIL:
        db_path = str(path) if path else str(config.emclient_db_path)
        return email_cls(db_path)

    if indexer_type == IndexerType.CALIBRE:
        libraries = [path] if path else list(config.calibre_libraries)
        return calibre_cls(libraries, doc_store=doc_store)

    if indexer_type == IndexerType.RSS:
        db_path = str(path) if path else str(config.netnewswire_db_path)
        return rss_cls(db_path)

    if indexer_type == IndexerType.CODE:
        if path is None:
            raise ValueError(f"Code indexer for '{collection}' requires a path")
        return git_cls(path, collection_name=collection)

    if indexer_type == IndexerType.PROJECT:
        paths = [path] if path else []
        return project_cls(collection, paths, doc_store=doc_store)

    raise ValueError(f"Unknown indexer_type: {indexer_type!r}")
