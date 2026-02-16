"""Tests for ragling.sync module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ragling.config import Config, UserConfig


class TestSyncDiscoverFiles:
    """Tests for file discovery during sync."""

    def test_discovers_files_in_user_dir(self, tmp_path: Path) -> None:
        from ragling.sync import discover_files_to_sync

        home = tmp_path / "groups"
        user_dir = home / "kitchen"
        user_dir.mkdir(parents=True)
        (user_dir / "notes.md").write_text("# Notes")
        (user_dir / "data.txt").write_text("data")

        config = Config(
            home=home,
            users={"kitchen": UserConfig(api_key="rag_test")},
        )
        files = discover_files_to_sync(config)
        paths = {str(f) for f in files}
        assert str(user_dir / "notes.md") in paths
        assert str(user_dir / "data.txt") in paths

    def test_discovers_files_in_global_paths(self, tmp_path: Path) -> None:
        from ragling.sync import discover_files_to_sync

        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "shared.md").write_text("# Shared")

        config = Config(global_paths=[global_dir])
        files = discover_files_to_sync(config)
        paths = {str(f) for f in files}
        assert str(global_dir / "shared.md") in paths

    def test_skips_hidden_files(self, tmp_path: Path) -> None:
        from ragling.sync import discover_files_to_sync

        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / ".hidden.md").write_text("secret")
        (global_dir / "visible.md").write_text("public")

        config = Config(global_paths=[global_dir])
        files = discover_files_to_sync(config)
        paths = {str(f) for f in files}
        assert str(global_dir / "visible.md") in paths
        assert str(global_dir / ".hidden.md") not in paths

    def test_no_home_returns_only_global(self, tmp_path: Path) -> None:
        from ragling.sync import discover_files_to_sync

        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "doc.md").write_text("text")

        config = Config(home=None, global_paths=[global_dir])
        files = discover_files_to_sync(config)
        assert len(files) >= 1


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
