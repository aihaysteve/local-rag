"""System collection watcher for monitoring SQLite databases.

Watches SQLite database files for email, calibre, and RSS sources.
Uses debounced change detection — when a DB file is modified, waits
for a quiet period before submitting an indexing job.

The longer debounce (default 10s vs 2s for file watcher) accounts for
WAL files changing frequently during normal SQLite operations.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEvent, FileSystemEventHandler

from ragling.config import Config
from ragling.indexing_queue import IndexJob

if TYPE_CHECKING:
    from ragling.indexing_queue import IndexingQueue

logger = logging.getLogger(__name__)

_DEFAULT_DEBOUNCE_SECONDS = 10.0


class SystemCollectionWatcher:
    """Monitors system SQLite databases and submits indexing jobs on change.

    Each watched DB path is mapped to a collection name and indexer type.
    Changes are debounced per-path to avoid redundant indexing during
    frequent WAL writes.

    Args:
        config: Application configuration.
        queue: The indexing queue to submit jobs to.
        debounce_seconds: Seconds to wait after last change before submitting.
    """

    def __init__(
        self,
        config: Config,
        queue: IndexingQueue,
        debounce_seconds: float = _DEFAULT_DEBOUNCE_SECONDS,
    ) -> None:
        self._config = config
        self._queue = queue
        self._debounce = debounce_seconds
        self._lock = threading.RLock()
        self._timers: dict[Path, threading.Timer] = {}
        self._pending: set[Path] = set()

        # Build path-to-collection mapping
        self._path_map: dict[Path, tuple[str, str]] = {}
        for collection, path in self.get_db_paths():
            resolved = path.resolve()
            # For system collections, indexer_type matches collection name
            self._path_map[resolved] = (collection, collection)

    def get_db_paths(self) -> list[tuple[str, Path]]:
        """Return list of (collection_name, db_path) for enabled system collections.

        Returns:
            List of tuples mapping collection names to their database paths.
        """
        paths: list[tuple[str, Path]] = []
        if self._config.is_collection_enabled("email"):
            paths.append(("email", self._config.emclient_db_path))
        if self._config.is_collection_enabled("calibre"):
            for lib in self._config.calibre_libraries:
                paths.append(("calibre", Path(lib)))
        if self._config.is_collection_enabled("rss"):
            paths.append(("rss", self._config.netnewswire_db_path))
        return paths

    def get_watch_directories(self) -> list[Path]:
        """Return directories that should be watched for system DB changes.

        These are the actual DB paths (for directories) or their parent
        directories (for files). Used to configure watchdog observers.

        Returns:
            Deduplicated list of existing directories to watch.
        """
        seen: set[Path] = set()
        dirs: list[Path] = []
        for resolved in self._path_map:
            # If the path is a directory, watch it directly
            # If it's a file, watch its parent
            watch_dir = resolved if resolved.is_dir() else resolved.parent
            if watch_dir not in seen and watch_dir.exists():
                seen.add(watch_dir)
                dirs.append(watch_dir)
        return dirs

    def notify_change(self, path: Path) -> None:
        """Notify that a watched path has changed.

        Resets the debounce timer for this path. After the debounce period,
        submits an IndexJob for the corresponding collection.

        Args:
            path: The path that changed.
        """
        resolved = path.resolve()
        if resolved not in self._path_map:
            return

        with self._lock:
            self._pending.add(resolved)
            existing = self._timers.get(resolved)
            if existing:
                existing.cancel()
            timer = threading.Timer(self._debounce, self._flush_path, args=(resolved,))
            timer.daemon = True
            timer.start()
            self._timers[resolved] = timer

    def stop(self) -> None:
        """Stop the watcher and flush all pending changes immediately."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            pending = set(self._pending)
            self._pending.clear()

        for resolved in pending:
            self._submit_job(resolved)

    def _flush_path(self, resolved: Path) -> None:
        """Flush a single pending path after debounce expires."""
        with self._lock:
            self._timers.pop(resolved, None)
            if resolved not in self._pending:
                return
            self._pending.discard(resolved)

        self._submit_job(resolved)

    def _submit_job(self, resolved: Path) -> None:
        """Submit an IndexJob for a resolved path."""
        mapping = self._path_map.get(resolved)
        if not mapping:
            return
        collection, indexer_type = mapping
        self._queue.submit(
            IndexJob(
                job_type="system_collection",
                path=resolved,
                collection_name=collection,
                indexer_type=indexer_type,
            )
        )
        logger.info("Submitted system collection reindex: %s", collection)


class _SystemDbHandler(FileSystemEventHandler):
    """Watchdog handler that routes file changes to SystemCollectionWatcher.

    When a file is modified inside a watched system DB directory, the
    handler resolves it to a known DB path and notifies the watcher.
    """

    def __init__(self, watcher: SystemCollectionWatcher) -> None:
        self._watcher = watcher
        # Build a set of watched directory paths for fast lookup
        self._watched_dirs = {p.resolve() for p in watcher._path_map}

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        file_path = Path(str(event.src_path)).resolve()
        for watched_dir in self._watched_dirs:
            if file_path.is_relative_to(watched_dir):
                self._watcher.notify_change(watched_dir)
                return
