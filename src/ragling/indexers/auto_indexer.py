"""Auto-detection indexer that routes directories to the correct indexer."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_directory_type(directory: Path) -> str:
    """Detect the content type of a directory by marker files.

    Checks for .obsidian and .git markers. Obsidian takes precedence
    because an Obsidian vault with git tracking is primarily notes, not code.

    Args:
        directory: Path to the directory.

    Returns:
        'obsidian', 'code', or 'project'.
    """
    if (directory / ".obsidian").is_dir():
        return "obsidian"
    if (directory / ".git").is_dir():
        return "code"
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
