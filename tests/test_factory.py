"""Tests for indexers.factory — centralized indexer creation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestCreateIndexer:
    """create_indexer returns the correct indexer type for each collection."""

    def test_obsidian_returns_obsidian_indexer(self) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer

        config = Config(obsidian_vaults=[Path("/tmp/vault")])
        indexer = create_indexer("obsidian", config)
        assert type(indexer).__name__ == "ObsidianIndexer"

    def test_email_returns_email_indexer(self) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer
        from ragling.indexers.email_indexer import EmailIndexer

        config = Config(emclient_db_path=Path("/tmp/mail.db"))
        indexer = create_indexer("email", config)
        assert isinstance(indexer, EmailIndexer)

    def test_calibre_returns_calibre_indexer(self) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer
        from ragling.indexers.calibre_indexer import CalibreIndexer

        config = Config(calibre_libraries=[Path("/tmp/calibre")])
        indexer = create_indexer("calibre", config)
        assert isinstance(indexer, CalibreIndexer)

    def test_rss_returns_rss_indexer(self) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer
        from ragling.indexers.rss_indexer import RSSIndexer

        config = Config(netnewswire_db_path=Path("/tmp/netnewswire.db"))
        indexer = create_indexer("rss", config)
        assert isinstance(indexer, RSSIndexer)

    def test_code_group_returns_git_indexer(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer
        from ragling.indexers.git_indexer import GitRepoIndexer

        config = Config(code_groups={"mygroup": (tmp_path,)})
        indexer = create_indexer("mygroup", config, path=tmp_path)
        assert isinstance(indexer, GitRepoIndexer)

    def test_code_group_without_path_raises(self) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer

        config = Config(code_groups={"mygroup": (Path("/tmp/repo"),)})
        with pytest.raises(ValueError, match="requires a path"):
            create_indexer("mygroup", config)

    def test_project_with_path_returns_project_indexer(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer
        from ragling.indexers.project import ProjectIndexer

        config = Config()
        indexer = create_indexer("custom", config, path=tmp_path)
        assert isinstance(indexer, ProjectIndexer)

    def test_unknown_collection_no_path_raises(self) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer

        config = Config()
        with pytest.raises(ValueError, match="Unknown collection"):
            create_indexer("nonexistent", config)

    def test_watch_code_returns_git_indexer(self, tmp_path: Path) -> None:
        from types import MappingProxyType

        from ragling.config import Config
        from ragling.indexer_types import IndexerType
        from ragling.indexers.factory import create_indexer
        from ragling.indexers.git_indexer import GitRepoIndexer

        config = Config(watch=MappingProxyType({"mywatch": (tmp_path,)}))
        with patch(
            "ragling.indexers.auto_indexer.detect_directory_type",
            return_value=IndexerType.CODE,
        ):
            indexer = create_indexer("mywatch", config, path=tmp_path)
        assert isinstance(indexer, GitRepoIndexer)

    def test_watch_project_returns_project_indexer(self, tmp_path: Path) -> None:
        from types import MappingProxyType

        from ragling.config import Config
        from ragling.indexer_types import IndexerType
        from ragling.indexers.factory import create_indexer
        from ragling.indexers.project import ProjectIndexer

        config = Config(watch=MappingProxyType({"mywatch": (tmp_path,)}))
        with patch(
            "ragling.indexers.auto_indexer.detect_directory_type",
            return_value=IndexerType.PROJECT,
        ):
            indexer = create_indexer("mywatch", config, path=tmp_path)
        assert isinstance(indexer, ProjectIndexer)

    def test_watch_without_path_raises(self) -> None:
        from types import MappingProxyType

        from ragling.config import Config
        from ragling.indexers.factory import create_indexer

        config = Config(watch=MappingProxyType({"mywatch": (Path("/tmp/dir"),)}))
        with pytest.raises(ValueError, match="requires a path"):
            create_indexer("mywatch", config)

    def test_obsidian_passes_doc_store(self) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer

        config = Config(obsidian_vaults=[Path("/tmp/vault")])
        doc_store = MagicMock()
        indexer = create_indexer("obsidian", config, doc_store=doc_store)
        assert indexer.doc_store is doc_store

    def test_obsidian_with_path_overrides_vaults(self, tmp_path: Path) -> None:
        from ragling.config import Config
        from ragling.indexers.factory import create_indexer

        config = Config(obsidian_vaults=[Path("/tmp/vault1"), Path("/tmp/vault2")])
        indexer = create_indexer("obsidian", config, path=tmp_path)
        assert type(indexer).__name__ == "ObsidianIndexer"
        # When path is provided, it should override the vault list
        assert indexer.vault_paths == [tmp_path]
