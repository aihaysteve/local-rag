"""Startup sync: discover and submit indexing jobs for all configured sources.

Scans configured directories and system sources at startup, submitting
IndexJob items to the queue for system collections. Directory-based sources
(home, global, obsidian, code groups, watch) use the unified walker pipeline.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from ragling.config import Config
from ragling.indexer_types import IndexerType
from ragling.indexing_queue import IndexJob

if TYPE_CHECKING:
    from ragling.doc_store import DocStore
    from ragling.indexers.base import IndexResult
    from ragling.indexing_queue import IndexingQueue
    from ragling.indexing_status import IndexingStatus

logger = logging.getLogger(__name__)


def _sync_directory_source(
    conn: sqlite3.Connection,
    config: Config,
    watch_name: str,
    watch_path: Path,
    force: bool = False,
    doc_store: DocStore | None = None,
    status: IndexingStatus | None = None,
) -> IndexResult:
    """Index a directory using the unified walker pipeline."""
    from ragling.indexers.walk_processor import process_walk_result
    from ragling.indexers.walker import ExclusionConfig, walk

    exclusion_config = ExclusionConfig(
        global_ragignore_path=Path.home() / ".ragling" / "ragignore",
    )
    walk_result = walk(watch_path, exclusion_config=exclusion_config)
    return process_walk_result(
        walk_result,
        conn,
        config,
        watch_name=watch_name,
        watch_root=watch_path,
        force=force,
        doc_store=doc_store,
        status=status,
    )


def _resolve_path(file_path: Path, config: Config) -> tuple[str | None, Path | None]:
    """Resolve a file path to its collection name and containing directory.

    Checks user directories under config.home first, then global paths.

    Args:
        file_path: Path to the file.
        config: Application configuration.

    Returns:
        Tuple of (collection_name, containing_dir). Both are None if the
        file doesn't belong to any known directory.
    """
    resolved = file_path.resolve()

    # Check user directories under home
    if config.home is not None:
        home_resolved = config.home.resolve()
        if resolved.is_relative_to(home_resolved):
            relative = resolved.relative_to(home_resolved)
            parts = relative.parts
            if parts:
                username = parts[0]
                if username in config.users:
                    return username, home_resolved / username

    # Check global paths
    for global_path in config.global_paths:
        global_resolved = global_path.resolve()
        if resolved.is_relative_to(global_resolved):
            return "global", global_resolved

    # Check obsidian vaults
    for vault in config.obsidian_vaults:
        vault_resolved = vault.resolve()
        if resolved.is_relative_to(vault_resolved):
            return "obsidian", vault_resolved

    # Check code groups
    for group_name, repo_paths in config.code_groups.items():
        for repo_path in repo_paths:
            repo_resolved = repo_path.resolve()
            if resolved.is_relative_to(repo_resolved):
                return group_name, repo_resolved

    # Check watch directories
    for watch_name, watch_paths in config.watch.items():
        for watch_path in watch_paths:
            watch_resolved = watch_path.resolve()
            if resolved.is_relative_to(watch_resolved):
                return watch_name, watch_resolved

    return None, None


def map_file_to_collection(file_path: Path, config: Config) -> str | None:
    """Determine which collection a file belongs to based on its path.

    Args:
        file_path: Path to the file.
        config: Application configuration.

    Returns:
        Collection name string, or None if the file doesn't belong
        to any known directory.
    """
    collection, _ = _resolve_path(file_path, config)
    return collection


def run_startup_sync(
    config: Config,
    queue: IndexingQueue,
    done_event: threading.Event | None = None,
) -> threading.Thread:
    """Spawn a daemon thread that discovers all sources and submits IndexJobs.

    Enumerates home directories, global paths, obsidian vaults, code groups,
    watch directories, and system collections, then submits IndexJob items
    to the queue.

    Args:
        config: Application configuration.
        queue: The indexing queue to submit jobs to.
        done_event: Optional threading.Event that is set when enumeration
            completes. Useful for coordinating startup ordering.

    Returns:
        The daemon thread that was started.
    """

    def _sync() -> None:
        try:
            from ragling.db import get_connection, init_db

            conn = get_connection(config)
            init_db(conn, config)

            try:
                # --- Home user directories (walker replaces detect_directory_type) ---
                if config.home and config.home.is_dir():
                    for username in config.users:
                        user_dir = config.home / username
                        if not user_dir.is_dir() or not config.is_collection_enabled(username):
                            continue
                        try:
                            result = _sync_directory_source(conn, config, username, user_dir)
                            logger.info("Synced %s: %s", username, result)
                        except Exception:
                            logger.exception("Error syncing user dir: %s", username)

                # --- Global paths ---
                if config.is_collection_enabled("global"):
                    for global_path in config.global_paths:
                        if not global_path.is_dir():
                            continue
                        try:
                            result = _sync_directory_source(conn, config, "global", global_path)
                            logger.info("Synced global (%s): %s", global_path, result)
                        except Exception:
                            logger.exception("Error syncing global path: %s", global_path)

                # --- Obsidian vaults ---
                if config.is_collection_enabled("obsidian"):
                    for vault in config.obsidian_vaults:
                        if not vault.is_dir():
                            continue
                        try:
                            result = _sync_directory_source(conn, config, "obsidian", vault)
                            logger.info("Synced obsidian (%s): %s", vault, result)
                        except Exception:
                            logger.exception("Error syncing obsidian vault: %s", vault)

                # --- Code groups ---
                for group_name, repo_paths in config.code_groups.items():
                    if not config.is_collection_enabled(group_name):
                        continue
                    for repo_path in repo_paths:
                        if not repo_path.is_dir():
                            continue
                        try:
                            result = _sync_directory_source(conn, config, group_name, repo_path)
                            logger.info(
                                "Synced code group %s (%s): %s",
                                group_name,
                                repo_path,
                                result,
                            )
                        except Exception:
                            logger.exception(
                                "Error syncing code group: %s/%s",
                                group_name,
                                repo_path,
                            )

                # --- Watch directories ---
                for watch_name, watch_paths in config.watch.items():
                    if not config.is_collection_enabled(watch_name):
                        continue
                    for watch_path in watch_paths:
                        if not watch_path.is_dir():
                            continue
                        try:
                            result = _sync_directory_source(conn, config, watch_name, watch_path)
                            logger.info(
                                "Synced watch %s (%s): %s",
                                watch_name,
                                watch_path,
                                result,
                            )
                        except Exception:
                            logger.exception("Error syncing watch: %s/%s", watch_name, watch_path)
            finally:
                conn.close()

            # --- System collections (unchanged, still use queue) ---
            if (
                config.is_collection_enabled("email")
                and config.emclient_db_path
                and config.emclient_db_path.exists()
            ):
                queue.submit(
                    IndexJob(
                        job_type="system_collection",
                        path=config.emclient_db_path,
                        collection_name="email",
                        indexer_type=IndexerType.EMAIL,
                    )
                )

            if config.is_collection_enabled("calibre"):
                for lib in config.calibre_libraries:
                    if not lib.exists():
                        continue
                    queue.submit(
                        IndexJob(
                            job_type="system_collection",
                            path=lib,
                            collection_name="calibre",
                            indexer_type=IndexerType.CALIBRE,
                        )
                    )

            if (
                config.is_collection_enabled("rss")
                and config.netnewswire_db_path
                and config.netnewswire_db_path.exists()
            ):
                queue.submit(
                    IndexJob(
                        job_type="system_collection",
                        path=config.netnewswire_db_path,
                        collection_name="rss",
                        indexer_type=IndexerType.RSS,
                    )
                )

            logger.info("Startup sync: all sources processed")
        except Exception:
            logger.exception("Startup sync: fatal error")
        finally:
            if done_event is not None:
                done_event.set()

    thread = threading.Thread(target=_sync, name="startup-sync", daemon=True)
    thread.start()
    return thread


def submit_file_change(
    file_path: Path,
    config: Config,
    queue: IndexingQueue,
) -> None:
    """Submit an IndexJob for a changed or deleted file.

    If the file exists on disk, submits a directory-level job using
    auto-detection. If the file has been deleted, submits a prune job.

    Args:
        file_path: Path to the changed or deleted file.
        config: Application configuration.
        queue: The indexing queue to submit jobs to.
    """
    collection, containing_dir = _resolve_path(file_path, config)
    if collection is None:
        logger.warning("Cannot map file to collection: %s", file_path)
        return
    if not config.is_collection_enabled(collection):
        return

    if not file_path.exists():
        queue.submit(
            IndexJob(
                job_type="file_deleted",
                path=file_path,
                collection_name=collection,
                indexer_type=IndexerType.PRUNE,
            )
        )
        return

    # File exists — detect indexer type by walking up directory tree
    from ragling.indexers.auto_indexer import detect_indexer_type_for_file

    indexer_type = detect_indexer_type_for_file(file_path)
    target_dir = containing_dir or file_path.parent
    queue.submit(
        IndexJob(
            job_type="file",
            path=target_dir,
            collection_name=collection,
            indexer_type=indexer_type,
        )
    )
