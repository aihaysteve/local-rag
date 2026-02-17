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


class TestDetectIndexerTypeForFile:
    """Tests for detect_indexer_type_for_file which walks up the tree."""

    def test_file_inside_obsidian_vault(self, tmp_path: Path) -> None:
        """File deep inside an obsidian vault should detect obsidian."""
        from ragling.indexers.auto_indexer import detect_indexer_type_for_file

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        subdir = vault / "notes" / "daily"
        subdir.mkdir(parents=True)
        deep_file = subdir / "2025-01-01.md"
        deep_file.write_text("# Daily Note")

        assert detect_indexer_type_for_file(deep_file) == "obsidian"

    def test_file_inside_git_repo(self, tmp_path: Path) -> None:
        """File deep inside a git repo should detect code."""
        from ragling.indexers.auto_indexer import detect_indexer_type_for_file

        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()
        src = repo / "src" / "lib"
        src.mkdir(parents=True)
        deep_file = src / "main.py"
        deep_file.write_text("print('hello')")

        assert detect_indexer_type_for_file(deep_file) == "code"

    def test_obsidian_takes_precedence_over_git(self, tmp_path: Path) -> None:
        """Obsidian vault with git tracking should detect obsidian."""
        from ragling.indexers.auto_indexer import detect_indexer_type_for_file

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / ".git").mkdir()
        note = vault / "note.md"
        note.write_text("# Note")

        assert detect_indexer_type_for_file(note) == "obsidian"

    def test_file_with_no_markers_defaults_to_project(self, tmp_path: Path) -> None:
        """File in a plain directory should default to project."""
        from ragling.indexers.auto_indexer import detect_indexer_type_for_file

        plain_dir = tmp_path / "docs"
        plain_dir.mkdir()
        doc = plain_dir / "readme.md"
        doc.write_text("# Readme")

        assert detect_indexer_type_for_file(doc) == "project"

    def test_stops_walking_at_filesystem_root(self, tmp_path: Path) -> None:
        """Does not walk past root or cause infinite loop."""
        from ragling.indexers.auto_indexer import detect_indexer_type_for_file

        # File directly in tmp_path with no markers anywhere
        plain_file = tmp_path / "orphan.md"
        plain_file.write_text("orphan")

        assert detect_indexer_type_for_file(plain_file) == "project"
