"""Tests for ragling.indexers.auto_indexer module."""

from pathlib import Path


class TestDetectDirectoryType:
    def test_detects_git_repo(self, tmp_path: Path) -> None:
        from ragling.indexers.auto_indexer import detect_directory_type

        (tmp_path / ".git").mkdir()
        (tmp_path / "main.py").write_text("print('hello')")
        assert detect_directory_type(tmp_path) == "code"

    def test_detects_obsidian_vault(self, tmp_path: Path) -> None:
        from ragling.indexers.auto_indexer import detect_directory_type

        (tmp_path / ".obsidian").mkdir()
        (tmp_path / "note.md").write_text("# Note")
        assert detect_directory_type(tmp_path) == "obsidian"

    def test_defaults_to_project(self, tmp_path: Path) -> None:
        from ragling.indexers.auto_indexer import detect_directory_type

        (tmp_path / "readme.md").write_text("# Readme")
        assert detect_directory_type(tmp_path) == "project"

    def test_git_takes_precedence_over_obsidian(self, tmp_path: Path) -> None:
        """If both .git and .obsidian exist, treat as obsidian (vault with git tracking)."""
        from ragling.indexers.auto_indexer import detect_directory_type

        (tmp_path / ".git").mkdir()
        (tmp_path / ".obsidian").mkdir()
        assert detect_directory_type(tmp_path) == "obsidian"


class TestCollectDirectoriesToIndex:
    def test_home_with_subdirs(self, tmp_path: Path) -> None:
        from ragling.indexers.auto_indexer import collect_indexable_directories

        home = tmp_path / "groups"
        home.mkdir()
        (home / "kitchen").mkdir()
        (home / "garage").mkdir()
        (home / ".hidden").mkdir()  # should be skipped

        dirs = collect_indexable_directories(home, usernames=["kitchen", "garage"])
        names = {d.name for d in dirs}
        assert "kitchen" in names
        assert "garage" in names
        assert ".hidden" not in names

    def test_only_returns_dirs_for_configured_users(self, tmp_path: Path) -> None:
        from ragling.indexers.auto_indexer import collect_indexable_directories

        home = tmp_path / "groups"
        home.mkdir()
        (home / "kitchen").mkdir()
        (home / "unknown").mkdir()

        dirs = collect_indexable_directories(home, usernames=["kitchen"])
        names = {d.name for d in dirs}
        assert "kitchen" in names
        assert "unknown" not in names
