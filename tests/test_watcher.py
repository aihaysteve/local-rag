"""Tests for ragling.watcher module."""

import time
from pathlib import Path
from unittest.mock import MagicMock

from watchdog.events import FileDeletedEvent

from ragling.config import Config
from ragling.watcher import DebouncedIndexQueue, _Handler


class TestDebouncedQueue:
    def test_queues_file_and_fires_after_delay(self) -> None:
        from ragling.watcher import DebouncedIndexQueue

        callback = MagicMock()
        queue = DebouncedIndexQueue(callback=callback, debounce_seconds=0.1)
        queue.start()
        try:
            queue.enqueue(Path("/test/file.md"))
            time.sleep(0.3)
            callback.assert_called_once()
            files = callback.call_args[0][0]
            assert Path("/test/file.md") in files
        finally:
            queue.stop()

    def test_batches_rapid_changes(self) -> None:
        from ragling.watcher import DebouncedIndexQueue

        callback = MagicMock()
        queue = DebouncedIndexQueue(callback=callback, debounce_seconds=0.2)
        queue.start()
        try:
            queue.enqueue(Path("/test/a.md"))
            time.sleep(0.05)
            queue.enqueue(Path("/test/b.md"))
            time.sleep(0.05)
            queue.enqueue(Path("/test/c.md"))
            time.sleep(0.4)
            callback.assert_called_once()
            files = callback.call_args[0][0]
            assert len(files) == 3
        finally:
            queue.stop()

    def test_deduplicates_same_file(self) -> None:
        from ragling.watcher import DebouncedIndexQueue

        callback = MagicMock()
        queue = DebouncedIndexQueue(callback=callback, debounce_seconds=0.1)
        queue.start()
        try:
            queue.enqueue(Path("/test/file.md"))
            queue.enqueue(Path("/test/file.md"))
            queue.enqueue(Path("/test/file.md"))
            time.sleep(0.3)
            callback.assert_called_once()
            files = callback.call_args[0][0]
            assert len(files) == 1
        finally:
            queue.stop()


class TestWatcherPaths:
    def test_computes_watch_paths_from_config(self, tmp_path: Path) -> None:
        from ragling.watcher import get_watch_paths

        home = tmp_path / "groups"
        global_dir = tmp_path / "global"
        home.mkdir()
        global_dir.mkdir()

        config = Config(home=home, global_paths=[global_dir])
        paths = get_watch_paths(config)
        assert home in paths
        assert global_dir in paths

    def test_skips_nonexistent_paths(self, tmp_path: Path) -> None:
        from ragling.watcher import get_watch_paths

        config = Config(
            home=tmp_path / "nonexistent",
            global_paths=[tmp_path / "also-nonexistent"],
        )
        paths = get_watch_paths(config)
        assert len(paths) == 0


class TestHandlerOnDeleted:
    def test_deleted_file_is_enqueued(self) -> None:
        queue = MagicMock(spec=DebouncedIndexQueue)
        handler = _Handler(queue, {".md", ".txt"})

        event = FileDeletedEvent(src_path="/tmp/notes.md")
        handler.on_deleted(event)

        queue.enqueue.assert_called_once_with(Path("/tmp/notes.md"))

    def test_deleted_unsupported_extension_ignored(self) -> None:
        queue = MagicMock(spec=DebouncedIndexQueue)
        handler = _Handler(queue, {".md", ".txt"})

        event = FileDeletedEvent(src_path="/tmp/photo.raw")
        handler.on_deleted(event)

        queue.enqueue.assert_not_called()

    def test_deleted_directory_ignored(self) -> None:
        queue = MagicMock(spec=DebouncedIndexQueue)
        handler = _Handler(queue, {".md", ".txt"})

        event = FileDeletedEvent(src_path="/tmp/somedir")
        event._is_directory = True  # watchdog sets this for dir events
        handler.on_deleted(event)

        queue.enqueue.assert_not_called()
