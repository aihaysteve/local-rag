"""Auto-detection indexer that routes directories to the correct indexer."""

from pathlib import Path

from ragling.indexer_types import IndexerType


def _check_markers(directory: Path) -> IndexerType | None:
    """Check a single directory for .obsidian or .git markers.

    Obsidian takes precedence because a vault with git tracking
    is primarily notes, not code.

    Returns:
        IndexerType.OBSIDIAN, IndexerType.CODE, or None if no markers found.
    """
    if (directory / ".obsidian").is_dir():
        return IndexerType.OBSIDIAN
    if (directory / ".git").is_dir():
        return IndexerType.CODE
    return None


def detect_directory_type(directory: Path) -> IndexerType:
    """Detect the content type of a directory by marker files.

    Args:
        directory: Path to the directory.

    Returns:
        IndexerType.OBSIDIAN, IndexerType.CODE, or IndexerType.PROJECT.
    """
    return _check_markers(directory) or IndexerType.PROJECT


def detect_indexer_type_for_file(file_path: Path) -> IndexerType:
    """Detect the indexer type for a file by walking up its directory tree.

    Checks each ancestor directory for `.obsidian` or `.git` markers.
    Obsidian takes precedence (a vault with git tracking is primarily notes).

    Args:
        file_path: Path to the file.

    Returns:
        IndexerType.OBSIDIAN, IndexerType.CODE, or IndexerType.PROJECT.
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
    return IndexerType.PROJECT
