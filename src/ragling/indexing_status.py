"""Thread-safe indexing status tracker."""

import threading
from typing import Any


class IndexingStatus:
    """Tracks remaining files to index. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._remaining = 0

    def set_remaining(self, count: int) -> None:
        """Set the number of files remaining to index."""
        with self._lock:
            self._remaining = count

    def decrement(self) -> None:
        """Decrement remaining count by one."""
        with self._lock:
            self._remaining = max(0, self._remaining - 1)

    def finish(self) -> None:
        """Mark indexing as complete."""
        with self._lock:
            self._remaining = 0

    def is_active(self) -> bool:
        """Check if indexing is in progress."""
        with self._lock:
            return self._remaining > 0

    def to_dict(self) -> dict[str, Any] | None:
        """Return status dict for inclusion in search responses.

        Returns None when idle (omit from response).
        """
        with self._lock:
            if self._remaining > 0:
                return {"active": True, "remaining": self._remaining}
            return None
