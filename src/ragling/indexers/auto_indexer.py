"""Auto-detection indexer that routes directories to the correct indexer."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _check_markers(directory: Path) -> str | None:
    """Check a single directory for .obsidian or .git markers.

    Obsidian takes precedence because a vault with git tracking
    is primarily notes, not code.

    Returns:
        'obsidian', 'code', or None if no markers found.
    """
    if (directory / ".obsidian").is_dir():
        return "obsidian"
    if (directory / ".git").is_dir():
        return "code"
    return None


def detect_directory_type(directory: Path) -> str:
    """Detect the content type of a directory by marker files.

    Args:
        directory: Path to the directory.

    Returns:
        'obsidian', 'code', or 'project'.
    """
    return _check_markers(directory) or "project"


def detect_indexer_type_for_file(file_path: Path) -> str:
    """Detect the indexer type for a file by walking up its directory tree.

    Checks each ancestor directory for `.obsidian` or `.git` markers.
    Obsidian takes precedence (a vault with git tracking is primarily notes).

    Args:
        file_path: Path to the file.

    Returns:
        'obsidian', 'code', or 'project'.
    """
    current = file_path.parent.resolve()
    while True:
        result = _check_markers(current)
        if result is not None:
            return result
        parent = current.parent
        if parent == current:
            break
        current = parent
    return "project"


def collect_indexable_directories(home: Path, usernames: list[str]) -> list[Path]:
    """Collect directories under home that correspond to configured users.

    Only returns directories for usernames in the provided list, skipping
    any that start with '.' or don't exist on disk.

    Args:
        home: Base directory containing user subdirectories.
        usernames: List of configured usernames.

    Returns:
        List of existing directories matching configured usernames.
    """
    dirs: list[Path] = []
    for username in usernames:
        if username.startswith("."):
            continue
        user_dir = home / username
        if user_dir.is_dir():
            dirs.append(user_dir)
        else:
            logger.debug("User directory not found: %s", user_dir)
    return dirs
