"""Startup sync: discover and index new/changed/deleted content.

Scans configured directories (user home dirs and global paths) at startup
and indexes files that are new or changed since the last sync.
"""

import logging
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


def _is_hidden(path: Path) -> bool:
    """Check if any component of the path starts with a dot.

    Args:
        path: File or directory path to check.

    Returns:
        True if any path component starts with '.'.
    """
    return any(part.startswith(".") for part in path.parts)


def _collect_supported_files(directory: Path) -> list[Path]:
    """Recursively collect files with supported extensions from a directory.

    Skips hidden files and directories (any path component starting with '.').

    Args:
        directory: Root directory to walk.

    Returns:
        Sorted list of file paths with supported extensions.
    """
    if not directory.is_dir():
        logger.debug("Directory does not exist, skipping: %s", directory)
        return []

    files: list[Path] = []
    for child in sorted(directory.rglob("*")):
        if not child.is_file():
            continue
        if _is_hidden(child):
            continue
        if child.suffix.lower() in _SUPPORTED_EXTENSIONS:
            files.append(child)
    return files


def discover_files_to_sync(config: Config) -> list[Path]:
    """Walk user home dirs and global paths, collecting supported files.

    Discovers files from two sources:
    1. User directories under config.home (one subdirectory per configured user)
    2. Global paths accessible to all users

    Hidden files (any path component starting with '.') are skipped.

    Args:
        config: Application configuration with home, users, and global_paths.

    Returns:
        List of file paths to consider for syncing.
    """
    files: list[Path] = []

    # Collect from user directories under home
    if config.home is not None and config.home.is_dir():
        for username in config.users:
            user_dir = config.home / username
            if user_dir.is_dir():
                files.extend(_collect_supported_files(user_dir))

    # Collect from global paths
    for global_path in config.global_paths:
        files.extend(_collect_supported_files(global_path))

    return files


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


def run_startup_sync(config: Config, status: IndexingStatus) -> threading.Thread:
    """Spawn a daemon thread that indexes new/changed files at startup.

    Discovers all files, compares hashes against the database, and
    indexes any that are new or changed. Updates the IndexingStatus
    tracker as it progresses.

    Args:
        config: Application configuration.
        status: Indexing status tracker for progress reporting.

    Returns:
        The daemon thread that was started.
    """

    def _sync() -> None:
        try:
            files = discover_files_to_sync(config)
            if not files:
                logger.info("Startup sync: no files to sync")
                return

            status.set_remaining(len(files))
            logger.info("Startup sync: found %d files to check", len(files))

            for file_path in files:
                try:
                    collection = map_file_to_collection(file_path, config)
                    if collection is None:
                        logger.warning(
                            "Startup sync: cannot map file to collection, skipping: %s",
                            file_path,
                        )
                        continue

                    # TODO: integrate with DB hash check and indexing pipeline
                    # For now, just log the file and its collection
                    logger.debug(
                        "Startup sync: would index %s into collection '%s'",
                        file_path,
                        collection,
                    )
                except Exception:
                    logger.exception("Startup sync: error processing %s", file_path)
                finally:
                    status.decrement()

        except Exception:
            logger.exception("Startup sync: fatal error")
        finally:
            status.finish()

    thread = threading.Thread(target=_sync, name="startup-sync", daemon=True)
    thread.start()
    return thread
