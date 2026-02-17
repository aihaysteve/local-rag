"""Tests for ragling.system_watcher module."""

import time
from pathlib import Path
from unittest.mock import MagicMock

from ragling.config import Config
from ragling.indexing_queue import IndexJob


class TestSystemCollectionWatcher:
    """Tests for SystemCollectionWatcher that monitors system DB files."""

    def test_collects_db_paths_from_config(self, tmp_path: Path) -> None:
        """Watcher discovers all system DB paths from config."""
        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        calibre_lib = tmp_path / "calibre"
        nnw_db = tmp_path / "nnw"
        email_db.mkdir()
        calibre_lib.mkdir()
        nnw_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            calibre_libraries=(calibre_lib,),
            netnewswire_db_path=nnw_db,
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue)

        db_paths = watcher.get_db_paths()
        assert ("email", email_db) in db_paths
        assert ("calibre", calibre_lib) in db_paths
        assert ("rss", nnw_db) in db_paths

    def test_skips_disabled_collections(self, tmp_path: Path) -> None:
        """Disabled collections are not watched."""
        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        nnw_db = tmp_path / "nnw"
        email_db.mkdir()
        nnw_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            netnewswire_db_path=nnw_db,
            disabled_collections={"email"},
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue)

        db_paths = watcher.get_db_paths()
        collections = [name for name, _ in db_paths]
        assert "email" not in collections
        assert "rss" in collections

    def test_submits_job_on_change(self, tmp_path: Path) -> None:
        """When a DB file changes, an IndexJob is submitted to the queue."""
        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        email_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            disabled_collections={"calibre", "rss"},
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue, debounce_seconds=0.1)

        watcher.notify_change(email_db)
        time.sleep(0.3)

        queue.submit.assert_called_once()
        job = queue.submit.call_args[0][0]
        assert isinstance(job, IndexJob)
        assert job.collection_name == "email"
        assert job.indexer_type == "email"
        assert job.job_type == "system_collection"

    def test_debounces_rapid_changes(self, tmp_path: Path) -> None:
        """Multiple rapid changes to the same DB are batched."""
        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        email_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            disabled_collections={"calibre", "rss"},
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue, debounce_seconds=0.2)

        # Rapid notifications
        watcher.notify_change(email_db)
        time.sleep(0.05)
        watcher.notify_change(email_db)
        time.sleep(0.05)
        watcher.notify_change(email_db)
        time.sleep(0.4)

        # Should only fire once
        assert queue.submit.call_count == 1

    def test_maps_path_to_correct_collection(self, tmp_path: Path) -> None:
        """Each DB path maps to the correct collection and indexer type."""
        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        calibre_lib = tmp_path / "calibre"
        nnw_db = tmp_path / "nnw"
        email_db.mkdir()
        calibre_lib.mkdir()
        nnw_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            calibre_libraries=(calibre_lib,),
            netnewswire_db_path=nnw_db,
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue, debounce_seconds=0.1)

        watcher.notify_change(calibre_lib)
        time.sleep(0.3)

        job = queue.submit.call_args[0][0]
        assert job.collection_name == "calibre"
        assert job.indexer_type == "calibre"

    def test_unknown_path_is_ignored(self, tmp_path: Path) -> None:
        """A path not matching any system DB is silently ignored."""
        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        email_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            disabled_collections={"calibre", "rss"},
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue, debounce_seconds=0.1)

        watcher.notify_change(tmp_path / "unknown")
        time.sleep(0.3)

        queue.submit.assert_not_called()

    def test_get_watch_directories_returns_parent_dirs(self, tmp_path: Path) -> None:
        """get_watch_directories returns parent directories of DB paths."""
        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        email_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            disabled_collections={"calibre", "rss"},
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue)

        watch_dirs = watcher.get_watch_directories()
        # email_db itself is a directory, so its parent (tmp_path) should be watched
        # OR the db path itself if it's a directory
        assert any(d.resolve() == email_db.resolve() for d in watch_dirs)

    def test_stop_flushes_pending(self, tmp_path: Path) -> None:
        """Stopping the watcher flushes any pending changes."""
        from ragling.system_watcher import SystemCollectionWatcher

        email_db = tmp_path / "emclient"
        email_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            disabled_collections={"calibre", "rss"},
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue, debounce_seconds=5.0)

        watcher.notify_change(email_db)
        # Without stop, the 5s debounce wouldn't fire yet
        watcher.stop()

        queue.submit.assert_called_once()


class TestSystemDbHandler:
    """Tests for the watchdog handler that routes events to SystemCollectionWatcher."""

    def test_handler_routes_file_modification(self, tmp_path: Path) -> None:
        from watchdog.events import FileModifiedEvent

        from ragling.system_watcher import SystemCollectionWatcher, _SystemDbHandler

        email_db = tmp_path / "emclient"
        email_db.mkdir()
        db_file = email_db / "mail.db"
        db_file.write_text("data")

        config = Config(
            emclient_db_path=email_db,
            disabled_collections={"calibre", "rss"},
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue)

        handler = _SystemDbHandler(watcher)
        event = FileModifiedEvent(src_path=str(db_file))
        handler.on_modified(event)

        # The parent directory matches the email_db path
        # notify_change should have been called
        # We verify by checking pending state or waiting for debounce
        # Since debounce is 10s, just check that the path was registered
        assert email_db.resolve() in watcher._pending

    def test_handler_ignores_unrelated_files(self, tmp_path: Path) -> None:
        from watchdog.events import FileModifiedEvent

        from ragling.system_watcher import SystemCollectionWatcher, _SystemDbHandler

        email_db = tmp_path / "emclient"
        email_db.mkdir()

        config = Config(
            emclient_db_path=email_db,
            disabled_collections={"calibre", "rss"},
        )
        queue = MagicMock()
        watcher = SystemCollectionWatcher(config, queue)

        handler = _SystemDbHandler(watcher)
        # File in a different directory
        event = FileModifiedEvent(src_path=str(tmp_path / "other" / "file.txt"))
        handler.on_modified(event)

        assert len(watcher._pending) == 0


class TestStartSystemWatcher:
    """Tests for start_system_watcher convenience function."""

    def test_returns_observer_and_watcher(self, tmp_path: Path) -> None:
        from ragling.system_watcher import start_system_watcher

        config = Config(
            emclient_db_path=tmp_path / "emclient.db",
            embedding_dimensions=4,
        )
        queue = MagicMock()

        # Create the DB file so the watch directory exists
        (tmp_path / "emclient.db").touch()

        observer, watcher = start_system_watcher(config, queue)
        assert observer.is_alive()
        observer.stop()
        observer.join(timeout=5)
