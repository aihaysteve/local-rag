"""Startup sync: discover and submit indexing jobs for all configured sources.

Scans configured directories and system sources at startup, submitting
IndexJob items to the queue. The queue worker handles actual indexing.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from ragling.config import Config
from ragling.indexing_queue import IndexJob

if TYPE_CHECKING:
    from ragling.indexing_queue import IndexingQueue

logger = logging.getLogger(__name__)


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
    and system collections, then submits IndexJob items to the queue.

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
            from ragling.indexers.auto_indexer import (
                collect_indexable_directories,
                detect_directory_type,
            )

            # --- Home user directories ---
            if config.home and config.home.is_dir():
                usernames = list(config.users.keys())
                for user_dir in collect_indexable_directories(config.home, usernames):
                    if not config.is_collection_enabled(user_dir.name):
                        continue
                    dir_type = detect_directory_type(user_dir)
                    queue.submit(
                        IndexJob(
                            job_type="directory",
                            path=user_dir,
                            collection_name=user_dir.name,
                            indexer_type=dir_type,
                        )
                    )

            # --- Global paths ---
            if config.is_collection_enabled("global"):
                for global_path in config.global_paths:
                    if not global_path.is_dir():
                        continue
                    dir_type = detect_directory_type(global_path)
                    queue.submit(
                        IndexJob(
                            job_type="directory",
                            path=global_path,
                            collection_name="global",
                            indexer_type=dir_type,
                        )
                    )

            # --- Obsidian vaults ---
            if config.is_collection_enabled("obsidian"):
                for vault in config.obsidian_vaults:
                    if not vault.is_dir():
                        continue
                    queue.submit(
                        IndexJob(
                            job_type="directory",
                            path=vault,
                            collection_name="obsidian",
                            indexer_type="obsidian",
                        )
                    )

            # --- Code groups ---
            for group_name, repo_paths in config.code_groups.items():
                if not config.is_collection_enabled(group_name):
                    continue
                for repo_path in repo_paths:
                    queue.submit(
                        IndexJob(
                            job_type="directory",
                            path=repo_path,
                            collection_name=group_name,
                            indexer_type="code",
                        )
                    )

            # --- System collections ---
            if config.is_collection_enabled("email"):
                queue.submit(
                    IndexJob(
                        job_type="system_collection",
                        path=config.emclient_db_path,
                        collection_name="email",
                        indexer_type="email",
                    )
                )

            if config.is_collection_enabled("calibre"):
                for lib in config.calibre_libraries:
                    queue.submit(
                        IndexJob(
                            job_type="system_collection",
                            path=lib,
                            collection_name="calibre",
                            indexer_type="calibre",
                        )
                    )

            if config.is_collection_enabled("rss"):
                queue.submit(
                    IndexJob(
                        job_type="system_collection",
                        path=config.netnewswire_db_path,
                        collection_name="rss",
                        indexer_type="rss",
                    )
                )

            logger.info("Startup sync: all jobs submitted to queue")
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
                indexer_type="prune",
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
