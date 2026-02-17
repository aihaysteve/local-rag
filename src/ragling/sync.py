"""Startup sync: discover and index new/changed/deleted content.

Scans configured directories (user home dirs and global paths) at startup
and indexes files that are new or changed since the last sync.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from ragling.config import Config
from ragling.indexing_status import IndexingStatus

logger = logging.getLogger(__name__)

# File extensions worth indexing (matches project indexer's _EXTENSION_MAP)
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".html",
        ".htm",
        ".epub",
        ".txt",
        ".tex",
        ".latex",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".bmp",
        ".webp",
        ".csv",
        ".adoc",
        ".vtt",
        ".mp3",
        ".wav",
        ".md",
        ".json",
        ".yaml",
        ".yml",
    }
)


def map_file_to_collection(file_path: Path, config: Config) -> str | None:
    """Determine which collection a file belongs to based on its path.

    Maps files to collections:
    - Files under config.home/<username>/ map to that username (if the
      username exists in config.users)
    - Files under a global_path map to "global"
    - Files that don't match any known directory return None

    Args:
        file_path: Path to the file.
        config: Application configuration.

    Returns:
        Collection name string, or None if the file doesn't belong
        to any known directory.
    """
    resolved = file_path.resolve() if not file_path.is_absolute() else file_path

    # Check user directories under home
    if config.home is not None:
        home_resolved = config.home.resolve()
        try:
            relative = resolved.relative_to(home_resolved)
        except ValueError:
            pass
        else:
            # The first component of the relative path is the username
            parts = relative.parts
            if parts:
                username = parts[0]
                if username in config.users:
                    return username

    # Check global paths
    for global_path in config.global_paths:
        global_resolved = global_path.resolve()
        try:
            resolved.relative_to(global_resolved)
        except ValueError:
            continue
        else:
            return "global"

    return None


def _index_directory(
    directory: Path,
    collection_name: str,
    config: Config,
    conn: sqlite3.Connection,
) -> None:
    """Index a directory using the appropriate indexer based on content type.

    Uses auto-detection to route:
    - .git/ -> GitRepoIndexer (code + commit history)
    - .obsidian/ -> ObsidianIndexer (frontmatter, wikilinks, tags)
    - neither -> ProjectIndexer (routes by file extension)

    Args:
        directory: Path to the directory to index.
        collection_name: Collection name to index into.
        config: Application configuration.
        conn: Database connection.
    """
    from ragling.indexers.auto_indexer import detect_directory_type
    from ragling.indexers.base import IndexResult

    dir_type = detect_directory_type(directory)
    result: IndexResult

    if dir_type == "code":
        from ragling.indexers.git_indexer import GitRepoIndexer

        git_indexer = GitRepoIndexer(directory, collection_name=collection_name)
        result = git_indexer.index(conn, config, index_history=True)
    elif dir_type == "obsidian":
        from ragling.doc_store import DocStore
        from ragling.indexers.obsidian import ObsidianIndexer

        doc_store = DocStore(config.shared_db_path)
        try:
            obsidian_indexer = ObsidianIndexer(
                [directory], config.obsidian_exclude_folders, doc_store=doc_store
            )
            result = obsidian_indexer.index(conn, config)
        finally:
            doc_store.close()
    else:
        from ragling.doc_store import DocStore
        from ragling.indexers.project import ProjectIndexer

        doc_store = DocStore(config.shared_db_path)
        try:
            project_indexer = ProjectIndexer(collection_name, [directory], doc_store=doc_store)
            result = project_indexer.index(conn, config)
        finally:
            doc_store.close()

    logger.info(
        "Indexed %s (%s): %d indexed, %d skipped, %d errors",
        directory,
        dir_type,
        result.indexed,
        result.skipped,
        result.errors,
    )


def _index_file(file_path: Path, config: Config) -> None:
    """Index or re-index a single file, or prune it if deleted.

    If the file exists on disk, re-indexes it using the project indexer.
    If the file has been deleted, removes its source and vectors from the DB.

    Args:
        file_path: Path to the changed or deleted file.
        config: Application configuration.
    """
    collection = map_file_to_collection(file_path, config)
    if collection is None:
        logger.warning("Cannot map file to collection: %s", file_path)
        return

    if not file_path.exists():
        # File was deleted -- prune from DB
        from ragling.db import get_connection, get_or_create_collection, init_db
        from ragling.indexers.base import delete_source

        conn = get_connection(config)
        init_db(conn, config)
        try:
            collection_id = get_or_create_collection(conn, collection, "project")
            delete_source(conn, collection_id, str(file_path.resolve()))
        except Exception:
            logger.exception("Error pruning deleted file: %s", file_path)
        finally:
            conn.close()
        return

    # File exists -- re-index
    from ragling.db import get_connection, init_db
    from ragling.doc_store import DocStore
    from ragling.indexers.project import ProjectIndexer

    conn = get_connection(config)
    init_db(conn, config)
    doc_store = DocStore(config.shared_db_path)

    try:
        indexer = ProjectIndexer(collection, [file_path.parent], doc_store=doc_store)
        indexer.index(conn, config)
    except Exception:
        logger.exception("Error indexing file: %s", file_path)
    finally:
        doc_store.close()
        conn.close()


def run_startup_sync(
    config: Config,
    status: IndexingStatus,
    done_event: threading.Event | None = None,
) -> threading.Thread:
    """Spawn a daemon thread that indexes new/changed files at startup.

    Discovers all files, compares hashes against the database, and
    indexes any that are new or changed. Updates the IndexingStatus
    tracker as it progresses.

    Args:
        config: Application configuration.
        status: Indexing status tracker for progress reporting.
        done_event: Optional threading.Event that is set when sync completes.
            Useful for coordinating startup ordering (e.g., watcher waits
            for sync to finish before starting).

    Returns:
        The daemon thread that was started.
    """

    def _sync() -> None:
        try:
            from ragling.db import get_connection, init_db
            from ragling.indexers.auto_indexer import collect_indexable_directories

            conn = get_connection(config)
            init_db(conn, config)

            # Collect directories to index
            dirs_to_index: list[tuple[Path, str]] = []

            # User directories under home
            if config.home and config.home.is_dir():
                usernames = list(config.users.keys())
                for user_dir in collect_indexable_directories(config.home, usernames):
                    dirs_to_index.append((user_dir, user_dir.name))

            # Global paths
            for global_path in config.global_paths:
                if global_path.is_dir():
                    dirs_to_index.append((global_path, "global"))

            if not dirs_to_index:
                logger.info("Startup sync: no directories to index")
                return

            status.set_remaining(len(dirs_to_index))
            logger.info("Startup sync: %d directories to index", len(dirs_to_index))

            try:
                for directory, collection_name in dirs_to_index:
                    try:
                        _index_directory(directory, collection_name, config, conn)
                    except Exception:
                        logger.exception("Startup sync: error indexing %s", directory)
                    finally:
                        status.decrement()
            finally:
                conn.close()
        except Exception:
            logger.exception("Startup sync: fatal error")
        finally:
            status.finish()
            if done_event is not None:
                done_event.set()

    thread = threading.Thread(target=_sync, name="startup-sync", daemon=True)
    thread.start()
    return thread
