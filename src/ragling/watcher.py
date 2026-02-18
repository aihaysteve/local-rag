"""File system watcher with debounced indexing queue."""

import logging
import threading
from collections.abc import Callable, Set as AbstractSet
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from ragling.config import Config

logger = logging.getLogger(__name__)


def get_watch_paths(config: Config) -> list[Path]:
    """Compute which directories to watch based on config.

    Includes home directory, global paths, obsidian vaults, and code
    group repos. Only includes paths that exist on disk. Deduplicates
    by resolved path.

    Args:
        config: Application configuration.

    Returns:
        List of existing directory paths to watch.
    """
    seen: set[Path] = set()
    paths: list[Path] = []

    def _add(p: Path) -> None:
        resolved = p.resolve()
        if resolved not in seen and p.is_dir():
            seen.add(resolved)
            paths.append(p)

    if config.home:
        _add(config.home)
    for gp in config.global_paths:
        _add(gp)
    for vault in config.obsidian_vaults:
        _add(vault)
    for repo_paths in config.code_groups.values():
        for repo_path in repo_paths:
            _add(repo_path)
    return paths


class DebouncedIndexQueue:
    """Collects file change events and fires a batched callback after a delay.

    When a file change is enqueued, the queue waits for ``debounce_seconds``
    of inactivity before invoking the callback with the collected set of
    changed file paths. Rapid successive changes reset the timer and are
    batched into a single callback invocation. Duplicate paths are
    deduplicated automatically.

    Args:
        callback: Function called with the list of changed file paths.
        debounce_seconds: Seconds to wait after the last enqueue before firing.
    """

    def __init__(
        self, callback: Callable[[list[Path]], None], debounce_seconds: float = 2.0
    ) -> None:
        self._callback = callback
        self._debounce = debounce_seconds
        self._pending: set[Path] = set()
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        """Start accepting enqueue requests."""
        self._running = True

    def stop(self) -> None:
        """Stop the queue and flush any pending items."""
        self._running = False
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            if self._pending:
                self._flush()

    def enqueue(self, path: Path) -> None:
        """Add a file path to the pending set and reset the debounce timer.

        Args:
            path: Path to a changed file.
        """
        if not self._running:
            return
        with self._lock:
            self._pending.add(path)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        """Invoke the callback with all pending paths and clear the set."""
        with self._lock:
            if not self._pending:
                return
            files = list(self._pending)
            self._pending.clear()
            self._timer = None
        try:
            self._callback(files)
        except Exception:
            logger.exception("Error in watcher callback")


class _Handler(FileSystemEventHandler):
    """Watchdog event handler that filters by extension and enqueues changes."""

    def __init__(self, queue: DebouncedIndexQueue, supported_extensions: AbstractSet[str]) -> None:
        self._queue = queue
        self._extensions = supported_extensions

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        self._handle(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion events."""
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() in self._extensions:
            if not _in_hidden_directory(path):
                self._queue.enqueue(path)
        elif _is_git_state_file(path):
            self._queue.enqueue(path)


def _in_hidden_directory(path: Path) -> bool:
    """Check if any parent directory component starts with a dot."""
    return any(part.startswith(".") for part in path.parts[:-1])


def _is_git_state_file(path: Path) -> bool:
    """Check if a path is a git state file that signals repo changes.

    Matches .git/HEAD and anything under .git/refs/ (branch updates,
    remote tracking refs). Excludes noisy paths like .git/objects/,
    .git/index, and .git/logs/.
    """
    parts = path.parts
    try:
        git_idx = parts.index(".git")
    except ValueError:
        return False
    rest = parts[git_idx + 1 :]
    if not rest:
        return False
    if rest == ("HEAD",):
        return True
    if rest[0] == "refs":
        return True
    return False


def start_watcher(
    config: Config,
    callback: Callable[[list[Path]], None],
    supported_extensions: AbstractSet[str] | None = None,
) -> BaseObserver | None:
    """Start watching configured directories for file changes.

    Sets up a watchdog Observer that monitors all directories returned
    by ``get_watch_paths(config)`` for file creation and modification
    events. Changes are debounced and batched before invoking the callback.

    Args:
        config: Application configuration.
        callback: Function called with batched list of changed file paths.
        supported_extensions: File extensions to watch. Defaults to
            ``_SUPPORTED_EXTENSIONS`` which covers both document and code extensions.

    Returns:
        The started Observer instance, or None if no directories to watch.
    """
    from ragling.indexers.project import _SUPPORTED_EXTENSIONS

    extensions = supported_extensions or _SUPPORTED_EXTENSIONS
    watch_paths = get_watch_paths(config)
    if not watch_paths:
        logger.info("No directories to watch.")
        return None

    queue = DebouncedIndexQueue(callback=callback, debounce_seconds=2.0)
    queue.start()
    handler = _Handler(queue, extensions)
    observer = Observer()

    for path in watch_paths:
        observer.schedule(handler, str(path), recursive=True)
        logger.info("Watching: %s", path)

    observer.daemon = True
    observer.start()
    return observer
