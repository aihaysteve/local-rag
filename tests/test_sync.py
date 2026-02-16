"""Tests for ragling.sync module."""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from ragling.config import Config, UserConfig
from ragling.indexing_status import IndexingStatus


class TestSyncMapFileToCollection:
    """Tests for mapping a file path to its collection name."""

    def test_file_in_user_dir_maps_to_username(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        home = tmp_path / "groups"
        config = Config(home=home, users={"kitchen": UserConfig(api_key="k")})
        name = map_file_to_collection(home / "kitchen" / "notes.md", config)
        assert name == "kitchen"

    def test_file_in_global_dir_maps_to_global(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        global_dir = tmp_path / "global"
        config = Config(global_paths=[global_dir])
        name = map_file_to_collection(global_dir / "shared.md", config)
        assert name == "global"

    def test_file_outside_known_dirs_returns_none(self, tmp_path: Path) -> None:
        from ragling.sync import map_file_to_collection

        config = Config(home=tmp_path / "groups", global_paths=[])
        name = map_file_to_collection(tmp_path / "random" / "file.md", config)
        assert name is None


class TestIndexDirectory:
    """Tests for _index_directory routing to correct indexer."""

    def test_routes_git_directory_to_git_indexer(self, tmp_path: Path) -> None:
        from ragling.sync import _index_directory

        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()
        (repo_dir / "main.py").write_text("print('hello')")

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        with patch("ragling.indexers.git_indexer.GitRepoIndexer") as MockGit:
            mock_indexer = MagicMock()
            mock_indexer.index.return_value = MagicMock(
                indexed=1, skipped=0, errors=0, total_found=1
            )
            MockGit.return_value = mock_indexer
            conn = MagicMock()

            _index_directory(repo_dir, "kitchen", config, conn)

            MockGit.assert_called_once_with(repo_dir, collection_name="kitchen")
            mock_indexer.index.assert_called_once_with(conn, config, index_history=True)

    def test_routes_plain_directory_to_project_indexer(self, tmp_path: Path) -> None:
        from ragling.sync import _index_directory

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "readme.md").write_text("# Hello")

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        with patch("ragling.indexers.project.ProjectIndexer") as MockProject:
            mock_indexer = MagicMock()
            mock_indexer.index.return_value = MagicMock(
                indexed=1, skipped=0, errors=0, total_found=1
            )
            MockProject.return_value = mock_indexer
            with patch("ragling.doc_store.DocStore") as MockDocStore:
                mock_doc_store = MagicMock()
                MockDocStore.return_value = mock_doc_store
                conn = MagicMock()

                _index_directory(docs_dir, "kitchen", config, conn)

                MockProject.assert_called_once_with("kitchen", [docs_dir], doc_store=mock_doc_store)
                mock_indexer.index.assert_called_once_with(conn, config)
                mock_doc_store.close.assert_called_once()

    def test_routes_obsidian_directory_to_obsidian_indexer(self, tmp_path: Path) -> None:
        from ragling.sync import _index_directory

        vault_dir = tmp_path / "myvault"
        vault_dir.mkdir()
        (vault_dir / ".obsidian").mkdir()
        (vault_dir / "note.md").write_text("# Note")

        config = Config(
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        with patch("ragling.indexers.obsidian.ObsidianIndexer") as MockObsidian:
            mock_indexer = MagicMock()
            mock_indexer.index.return_value = MagicMock(
                indexed=1, skipped=0, errors=0, total_found=1
            )
            MockObsidian.return_value = mock_indexer
            with patch("ragling.doc_store.DocStore") as MockDocStore:
                mock_doc_store = MagicMock()
                MockDocStore.return_value = mock_doc_store
                conn = MagicMock()

                _index_directory(vault_dir, "kitchen", config, conn)

                MockObsidian.assert_called_once_with(
                    [vault_dir], config.obsidian_exclude_folders, doc_store=mock_doc_store
                )
                mock_indexer.index.assert_called_once_with(conn, config)
                mock_doc_store.close.assert_called_once()


class TestSyncDoneEvent:
    """Tests for done_event parameter on run_startup_sync."""

    def test_done_event_is_set_after_sync(self, tmp_path: Path) -> None:
        from ragling.sync import run_startup_sync

        config = Config(
            home=tmp_path / "groups",
            users={},
            global_paths=[],
        )
        status = IndexingStatus()
        done = threading.Event()

        thread = run_startup_sync(config, status, done_event=done)
        assert done.wait(timeout=5.0), "done_event was not set"
        thread.join(timeout=5.0)

    def test_done_event_is_set_even_on_error(self, tmp_path: Path) -> None:
        from ragling.sync import run_startup_sync

        home = tmp_path / "groups"
        home.mkdir()
        config = Config(
            home=home,
            users={"testuser": UserConfig(api_key="k")},
            global_paths=[],
        )
        status = IndexingStatus()
        done = threading.Event()

        # Patch to raise an error inside _sync to test finally-block behavior
        with patch(
            "ragling.indexers.auto_indexer.collect_indexable_directories",
            side_effect=RuntimeError("boom"),
        ):
            thread = run_startup_sync(config, status, done_event=done)
            assert done.wait(timeout=5.0), "done_event was not set after error"
            thread.join(timeout=5.0)

    def test_works_without_done_event(self, tmp_path: Path) -> None:
        """Backward compatibility: done_event=None (default) still works."""
        from ragling.sync import run_startup_sync

        config = Config(
            home=tmp_path / "groups",
            users={},
            global_paths=[],
        )
        status = IndexingStatus()

        thread = run_startup_sync(config, status)
        thread.join(timeout=5.0)
        assert not thread.is_alive()


class TestIndexFile:
    """Tests for _index_file single-file re-indexing helper."""

    def test_indexes_file_in_user_dir(self, tmp_path: Path) -> None:
        from ragling.sync import _index_file

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        user_dir.mkdir(parents=True)
        test_file = user_dir / "notes.md"
        test_file.write_text("# Notes")

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="k")},
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        with (
            patch("ragling.db.get_connection") as mock_get_conn,
            patch("ragling.db.init_db"),
            patch("ragling.doc_store.DocStore") as MockDocStore,
            patch("ragling.indexers.project.ProjectIndexer") as MockProject,
        ):
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn
            mock_doc_store = MagicMock()
            MockDocStore.return_value = mock_doc_store
            mock_indexer = MagicMock()
            mock_indexer.index.return_value = MagicMock(
                indexed=1, skipped=0, errors=0, total_found=1
            )
            MockProject.return_value = mock_indexer

            _index_file(test_file, config)

            MockProject.assert_called_once_with("kitchen", [user_dir], doc_store=mock_doc_store)
            mock_indexer.index.assert_called_once_with(mock_conn, config)
            mock_doc_store.close.assert_called_once()
            mock_conn.close.assert_called_once()

    def test_returns_none_for_unmapped_file(self, tmp_path: Path) -> None:
        from ragling.sync import _index_file

        config = Config(
            home=tmp_path / "groups",
            users={},
            global_paths=[],
        )

        # Should not raise, just log a warning
        _index_file(tmp_path / "random" / "file.md", config)

    def test_indexes_file_in_global_dir(self, tmp_path: Path) -> None:
        from ragling.sync import _index_file

        global_dir = tmp_path / "global"
        global_dir.mkdir()
        test_file = global_dir / "shared.md"
        test_file.write_text("# Shared")

        config = Config(
            global_paths=[global_dir],
            db_path=tmp_path / "test.db",
            shared_db_path=tmp_path / "doc_store.sqlite",
            embedding_dimensions=4,
        )

        with (
            patch("ragling.db.get_connection") as mock_get_conn,
            patch("ragling.db.init_db"),
            patch("ragling.doc_store.DocStore") as MockDocStore,
            patch("ragling.indexers.project.ProjectIndexer") as MockProject,
        ):
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn
            mock_doc_store = MagicMock()
            MockDocStore.return_value = mock_doc_store
            mock_indexer = MagicMock()
            mock_indexer.index.return_value = MagicMock(
                indexed=1, skipped=0, errors=0, total_found=1
            )
            MockProject.return_value = mock_indexer

            _index_file(test_file, config)

            MockProject.assert_called_once_with("global", [global_dir], doc_store=mock_doc_store)
            mock_indexer.index.assert_called_once_with(mock_conn, config)
            mock_doc_store.close.assert_called_once()
            mock_conn.close.assert_called_once()
