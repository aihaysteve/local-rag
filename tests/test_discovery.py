"""Tests for ragling.indexers.discovery module."""

from pathlib import Path

from ragling.indexers.discovery import DiscoveredSource, DiscoveryResult, discover_sources


class TestDataclasses:
    def test_discovered_source_fields(self) -> None:
        src = DiscoveredSource(
            path=Path("/tmp/vault"), relative_name="vault", source_type="obsidian"
        )
        assert src.path == Path("/tmp/vault")
        assert src.relative_name == "vault"
        assert src.source_type == "obsidian"

    def test_discovery_result_fields(self) -> None:
        result = DiscoveryResult(vaults=[], repos=[], leftover_paths=[])
        assert result.vaults == []
        assert result.repos == []
        assert result.leftover_paths == []


class TestBasicDetection:
    def test_detects_obsidian_vault(self, tmp_path: Path) -> None:
        vault = tmp_path / "my-vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "note.md").write_text("hello")

        result = discover_sources(tmp_path)
        assert len(result.vaults) == 1
        assert result.vaults[0].path == vault
        assert result.vaults[0].relative_name == "my-vault"
        assert result.vaults[0].source_type == "obsidian"

    def test_detects_git_repo(self, tmp_path: Path) -> None:
        repo = tmp_path / "my-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "main.py").write_text("print('hello')")

        result = discover_sources(tmp_path)
        assert len(result.repos) == 1
        assert result.repos[0].path == repo
        assert result.repos[0].relative_name == "my-repo"
        assert result.repos[0].source_type == "git"

    def test_no_markers_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file.md").write_text("hello")

        result = discover_sources(tmp_path)
        assert result.vaults == []
        assert result.repos == []
