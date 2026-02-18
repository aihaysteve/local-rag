"""Thread-safe indexing status tracker with per-collection file counts."""

import threading
from typing import Any


class IndexingStatus:
    """Tracks remaining files to index, broken down by collection.

    Supports two levels of tracking:
    - **Job-level** (increment/decrement): coarse "N jobs remaining" per collection.
    - **File-level** (set_file_total/file_processed): fine-grained "M of N files done".

    When both exist for the same collection, file-level takes precedence in
    ``to_dict()`` output.

    Thread-safe. All public methods acquire the internal lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._file_counts: dict[str, dict[str, int]] = {}

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
        Also clears file-level data for the collection, since the job owning
        that data is complete.

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
            # Clear file-level data when the job completes
            self._file_counts.pop(collection, None)

    def set_file_total(self, collection: str, total: int, total_bytes: int = 0) -> None:
        """Set the total file count and byte size for a collection.

        Initialises the processed count to zero if the collection has not
        been seen before at the file level.

        Args:
            collection: Collection name.
            total: Total number of files to index.
            total_bytes: Total bytes of files to index (default 0).
        """
        with self._lock:
            entry = self._file_counts.get(collection)
            if entry is None:
                self._file_counts[collection] = {
                    "total": total,
                    "processed": 0,
                    "total_bytes": total_bytes,
                    "remaining_bytes": total_bytes,
                }
            else:
                entry["total"] = total
                entry["total_bytes"] = total_bytes
                entry["remaining_bytes"] = total_bytes

    def file_processed(self, collection: str, count: int = 1, file_bytes: int = 0) -> None:
        """Record that *count* files have been processed for a collection.

        The collection must already have a total set via ``set_file_total``.

        Args:
            collection: Collection name.
            count: Number of files just processed (default 1).
            file_bytes: Bytes of files just processed (default 0).
        """
        with self._lock:
            entry = self._file_counts.get(collection)
            if entry is None:
                self._file_counts[collection] = {
                    "total": 0,
                    "processed": count,
                    "total_bytes": 0,
                    "remaining_bytes": -file_bytes,
                }
            else:
                entry["processed"] = entry["processed"] + count
                entry["remaining_bytes"] = entry.get("remaining_bytes", 0) - file_bytes

    def finish(self) -> None:
        """Mark all indexing as complete."""
        with self._lock:
            self._counts.clear()
            self._file_counts.clear()

    def is_collection_active(self, collection: str) -> bool:
        """Check if a collection has pending or in-progress work.

        Args:
            collection: Collection name to check.

        Returns:
            True if the collection has remaining jobs or file-level work.
        """
        with self._lock:
            if collection in self._counts:
                return True
            if collection in self._file_counts:
                return True
            return False

    def is_active(self) -> bool:
        """Check if any indexing is in progress."""
        with self._lock:
            return bool(self._counts) or bool(self._file_counts)

    def to_dict(self) -> dict[str, Any] | None:
        """Return status dict for inclusion in search responses.

        Returns None when idle (omit from response). When active, returns::

            {
                "active": True,
                "total_remaining": <int>,
                "collections": {
                    "obsidian": {"total": 100, "processed": 55, "remaining": 45},
                    "email": 2,
                    ...
                }
            }

        Collections with file-level tracking get a dict entry; collections
        with only job-level tracking get a plain int (backward compatible).
        File-level counts take precedence when both exist for a collection.
        """
        with self._lock:
            if not self._counts and not self._file_counts:
                return None

            collections: dict[str, Any] = {}
            total_remaining = 0
            total_remaining_bytes = 0

            # Collect all collection names from both sources.
            all_names = set(self._counts) | set(self._file_counts)

            for name in sorted(all_names):
                file_entry = self._file_counts.get(name)
                if file_entry is not None:
                    remaining = file_entry["total"] - file_entry["processed"]
                    remaining_bytes = file_entry.get("remaining_bytes", 0)
                    collections[name] = {
                        "total": file_entry["total"],
                        "processed": file_entry["processed"],
                        "remaining": remaining,
                        "total_bytes": file_entry.get("total_bytes", 0),
                        "remaining_bytes": remaining_bytes,
                    }
                    total_remaining += remaining
                    total_remaining_bytes += remaining_bytes
                else:
                    job_count = self._counts[name]
                    collections[name] = job_count
                    total_remaining += job_count

            return {
                "active": True,
                "total_remaining": total_remaining,
                "total_remaining_bytes": total_remaining_bytes,
                "collections": collections,
            }
