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


class TestWatchPathsIncludesObsidianAndCode:
    """Tests that get_watch_paths includes obsidian vaults and code group repos."""

    def test_includes_obsidian_vaults(self, tmp_path: Path) -> None:
        from ragling.watcher import get_watch_paths

        vault = tmp_path / "vault"
        vault.mkdir()
        config = Config(obsidian_vaults=[vault])
        paths = get_watch_paths(config)
        assert vault in paths

    def test_includes_code_group_repos(self, tmp_path: Path) -> None:
        from ragling.watcher import get_watch_paths

        repo = tmp_path / "repo"
        repo.mkdir()
        config = Config(code_groups={"my-org": [repo]})
        paths = get_watch_paths(config)
        assert repo in paths

    def test_skips_nonexistent_obsidian_vaults(self, tmp_path: Path) -> None:
        from ragling.watcher import get_watch_paths

        config = Config(obsidian_vaults=[tmp_path / "nonexistent"])
        paths = get_watch_paths(config)
        assert len(paths) == 0

    def test_skips_nonexistent_code_repos(self, tmp_path: Path) -> None:
        from ragling.watcher import get_watch_paths

        config = Config(code_groups={"org": [tmp_path / "nonexistent"]})
        paths = get_watch_paths(config)
        assert len(paths) == 0

    def test_deduplicates_overlapping_paths(self, tmp_path: Path) -> None:
        """Same path in home and obsidian should appear only once."""
        from ragling.watcher import get_watch_paths

        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        config = Config(
            home=shared_dir,
            obsidian_vaults=[shared_dir],
        )
        paths = get_watch_paths(config)
        assert paths.count(shared_dir) == 1

    def test_combines_all_path_types(self, tmp_path: Path) -> None:
        from ragling.watcher import get_watch_paths

        home = tmp_path / "home"
        global_dir = tmp_path / "global"
        vault = tmp_path / "vault"
        repo = tmp_path / "repo"
        for d in (home, global_dir, vault, repo):
            d.mkdir()

        config = Config(
            home=home,
            global_paths=[global_dir],
            obsidian_vaults=[vault],
            code_groups={"org": [repo]},
        )
        paths = get_watch_paths(config)
        assert home in paths
        assert global_dir in paths
        assert vault in paths
        assert repo in paths


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
