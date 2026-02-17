"""Thread-safe indexing status tracker with per-collection file counts."""

import threading
from typing import Any


class IndexingStatus:
    """Tracks remaining files to index, broken down by collection.

    Thread-safe. All public methods acquire the internal lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def increment(self, collection: str, count: int = 1) -> None:
        """Increment remaining count for a collection.

        Args:
            collection: Collection name.
            count: Number of files to add (default 1).
        """
        with self._lock:
            self._counts[collection] = self._counts.get(collection, 0) + count

    def decrement(self, collection: str, count: int = 1) -> None:
        """Decrement remaining count for a collection.

        Clamps at zero. Removes the collection entry when it reaches zero.

        Args:
            collection: Collection name.
            count: Number of files to subtract (default 1).
        """
        with self._lock:
            current = self._counts.get(collection, 0)
            new_val = max(0, current - count)
            if new_val == 0:
                self._counts.pop(collection, None)
            else:
                self._counts[collection] = new_val

    def finish(self) -> None:
        """Mark all indexing as complete."""
        with self._lock:
            self._counts.clear()

    def is_active(self) -> bool:
        """Check if any indexing is in progress."""
        with self._lock:
            return bool(self._counts)

    def to_dict(self) -> dict[str, Any] | None:
        """Return status dict for inclusion in search responses.

        Returns None when idle (omit from response). When active, returns::

            {
                "active": True,
                "total_remaining": <int>,
                "collections": {"obsidian": 3, "email": 2, ...}
            }
        """
        with self._lock:
            if not self._counts:
                return None
            return {
                "active": True,
                "total_remaining": sum(self._counts.values()),
                "collections": dict(self._counts),
            }
