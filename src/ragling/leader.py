"""Per-group leader election using fcntl.flock().

Each ragling serve process attempts an exclusive non-blocking flock on
a per-group lock file. The winner becomes the leader (runs IndexingQueue
and watchers). Losers become followers (search-only, retry periodically).

The kernel releases the lock automatically when the process dies, so
there are no stale locks, no PID files, and no heartbeats.
"""

from __future__ import annotations

import fcntl
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragling.config import Config

logger = logging.getLogger(__name__)


def lock_path_for_config(config: Config) -> Path:
    """Derive the lock file path from the group's index database path.

    Args:
        config: Application configuration with group_name set.

    Returns:
        Path to the lock file (adjacent to the index database).
    """
    if config.group_name != "default":
        db_path = config.group_index_db_path
    else:
        db_path = config.db_path
    return db_path.parent / (db_path.name + ".lock")


class LeaderLock:
    """Exclusive per-group lock using fcntl.flock().

    Usage::

        lock = LeaderLock(lock_path)
        if lock.try_acquire():
            # Leader: start IndexingQueue, watchers, etc.
        else:
            # Follower: search-only mode
            lock.start_retry(on_promote=my_callback)

    The lock is released when close() is called or the process dies.

    Args:
        lock_path: Path to the lock file.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fd: int | None = None
        self._is_leader = False
        self._retry_thread: threading.Thread | None = None
        self._stop_event: threading.Event = threading.Event()

    @property
    def is_leader(self) -> bool:
        """Whether this instance holds the lock."""
        return self._is_leader

    def try_acquire(self) -> bool:
        """Attempt to acquire the exclusive lock (non-blocking).

        Returns:
            True if the lock was acquired, False if another process holds it.
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._fd is None:
            self._fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._is_leader = True
            logger.info("Acquired leader lock: %s", self._lock_path)
        except BlockingIOError:
            self._is_leader = False
            logger.info("Leader lock held by another process: %s", self._lock_path)
        return self._is_leader

    def start_retry(
        self,
        interval: float = 30.0,
        on_promote: Callable[[], None] | None = None,
    ) -> None:
        """Start a background thread that retries lock acquisition.

        The thread sleeps for ``interval`` seconds between attempts.
        On successful acquisition, calls ``on_promote`` (if provided)
        and exits the loop.

        Args:
            interval: Seconds between retry attempts.
            on_promote: Callback invoked when this instance acquires the lock.
        """
        self._stop_event.clear()

        def _retry_loop() -> None:
            while not self._stop_event.wait(timeout=interval):
                if self.try_acquire():
                    logger.info("Promoted to leader via retry")
                    if on_promote:
                        try:
                            on_promote()
                        except Exception:
                            logger.exception("Error in promotion callback")
                    break

        self._retry_thread = threading.Thread(target=_retry_loop, name="leader-retry", daemon=True)
        self._retry_thread.start()

    def stop_retry(self) -> None:
        """Stop the retry thread if running."""
        self._stop_event.set()
        if self._retry_thread is not None:
            self._retry_thread.join(timeout=5.0)

    def close(self) -> None:
        """Release the lock and close the file descriptor."""
        self.stop_retry()
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            self._is_leader = False

    def __enter__(self) -> LeaderLock:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
