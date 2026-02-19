"""Tests for ragling.indexers.discovery module."""

from pathlib import Path

from ragling.indexers.discovery import (
    DiscoveredSource,
    DiscoveryResult,
    discover_sources,
    reconcile_sub_collections,
)


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


class TestPrecedence:
    def test_obsidian_takes_precedence_over_git(self, tmp_path: Path) -> None:
        """When a dir has both .obsidian and .git, it's classified as obsidian."""
        both = tmp_path / "both"
        both.mkdir()
        (both / ".obsidian").mkdir()
        (both / ".git").mkdir()

        result = discover_sources(tmp_path)
        assert len(result.vaults) == 1
        assert len(result.repos) == 0
        assert result.vaults[0].source_type == "obsidian"

    def test_mixed_siblings(self, tmp_path: Path) -> None:
        """Sibling dirs with different markers are correctly classified."""
        vault = tmp_path / "notes"
        vault.mkdir()
        (vault / ".obsidian").mkdir()

        repo = tmp_path / "code"
        repo.mkdir()
        (repo / ".git").mkdir()

        result = discover_sources(tmp_path)
        assert len(result.vaults) == 1
        assert len(result.repos) == 1
        assert result.vaults[0].relative_name == "notes"
        assert result.repos[0].relative_name == "code"


class TestNesting:
    def test_nested_git_inside_vault(self, tmp_path: Path) -> None:
        """A .git repo nested inside an .obsidian vault gets its own discovery."""
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        nested_repo = vault / "projects" / "my-repo"
        nested_repo.mkdir(parents=True)
        (nested_repo / ".git").mkdir()

        result = discover_sources(tmp_path)
        assert len(result.vaults) == 1
        assert len(result.repos) == 1
        assert result.repos[0].relative_name == "vault/projects/my-repo"

    def test_deeply_nested_vault(self, tmp_path: Path) -> None:
        """Vault found several levels deep."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / ".obsidian").mkdir()

        result = discover_sources(tmp_path)
        assert len(result.vaults) == 1
        assert result.vaults[0].relative_name == "a/b/c"


class TestLeftoverFiles:
    def test_files_outside_markers_are_leftovers(self, tmp_path: Path) -> None:
        """Files not inside any discovered subtree are returned as leftovers."""
        vault = tmp_path / "notes"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "note.md").write_text("hello")

        loose_pdf = tmp_path / "report.pdf"
        loose_pdf.write_bytes(b"%PDF fake")
        loose_txt = tmp_path / "readme.txt"
        loose_txt.write_text("hello")

        result = discover_sources(tmp_path)
        leftover_names = {p.name for p in result.leftover_paths}
        assert "report.pdf" in leftover_names
        assert "readme.txt" in leftover_names
        assert "note.md" not in leftover_names

    def test_no_markers_all_files_are_leftovers(self, tmp_path: Path) -> None:
        """When no markers found, all files are leftovers."""
        (tmp_path / "a.txt").write_text("a")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.md").write_text("b")

        result = discover_sources(tmp_path)
        assert len(result.leftover_paths) == 2

    def test_files_in_hidden_directories_are_not_leftovers(self, tmp_path: Path) -> None:
        """Files inside hidden directories (e.g. .claude/) are excluded from leftovers."""
        hidden = tmp_path / ".claude" / "var" / "models"
        hidden.mkdir(parents=True)
        (hidden / "tokenizer.json").write_text("{}")

        visible = tmp_path / "docs"
        visible.mkdir()
        (visible / "readme.txt").write_text("hello")

        result = discover_sources(tmp_path)
        leftover_names = {p.name for p in result.leftover_paths}
        assert "tokenizer.json" not in leftover_names
        assert "readme.txt" in leftover_names

    def test_files_in_nested_hidden_directories_excluded(self, tmp_path: Path) -> None:
        """Hidden dir as child of visible dir (e.g. visible/.hidden/deep/secret.txt)."""
        nested = tmp_path / "visible" / ".hidden" / "deep"
        nested.mkdir(parents=True)
        (nested / "secret.txt").write_text("secret")

        (tmp_path / "visible" / "public.txt").write_text("public")

        result = discover_sources(tmp_path)
        leftover_names = {p.name for p in result.leftover_paths}
        assert "secret.txt" not in leftover_names
        assert "public.txt" in leftover_names

    def test_files_in_subdir_of_non_marker_are_leftovers(self, tmp_path: Path) -> None:
        """Files in plain subdirs (no marker) are leftovers."""
        repo = tmp_path / "code"
        repo.mkdir()
        (repo / ".git").mkdir()

        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "spec.pdf").write_bytes(b"%PDF fake")

        result = discover_sources(tmp_path)
        leftover_names = {p.name for p in result.leftover_paths}
        assert "spec.pdf" in leftover_names


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


class TestEdgeCases:
    def test_symlink_cycle_does_not_infinite_loop(self, tmp_path: Path) -> None:
        """Symlink cycle is detected and scanning completes without hanging."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / ".git").mkdir()
        # Create a symlink cycle: real/link -> real
        (real_dir / "link").symlink_to(real_dir)

        result = discover_sources(tmp_path)
        assert len(result.repos) == 1  # Should find the repo once, not loop

    def test_follows_non_cyclic_symlinks(self, tmp_path: Path) -> None:
        """Non-cyclic symlinks are followed and markers found."""
        target = tmp_path / "target"
        target.mkdir()
        (target / ".obsidian").mkdir()

        link = tmp_path / "link"
        link.symlink_to(target)

        result = discover_sources(tmp_path)
        # Should find the vault via the symlink
        assert len(result.vaults) >= 1

    def test_permission_error_skips_dir(self, tmp_path: Path) -> None:
        """Unreadable directories are skipped without crashing."""
        forbidden = tmp_path / "forbidden"
        forbidden.mkdir()
        forbidden.chmod(0o000)

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        try:
            result = discover_sources(tmp_path)
            # Should still find the accessible repo
            assert len(result.repos) == 1
        finally:
            forbidden.chmod(0o755)  # Restore for cleanup

    def test_root_is_obsidian_vault(self, tmp_path: Path) -> None:
        """When root itself is a vault, relative_name is empty string."""
        (tmp_path / ".obsidian").mkdir()
        (tmp_path / "note.md").write_text("hello")

        result = discover_sources(tmp_path)
        assert len(result.vaults) == 1
        assert result.vaults[0].relative_name == ""

    def test_root_is_git_repo(self, tmp_path: Path) -> None:
        """When root itself is a repo, relative_name is empty string."""
        (tmp_path / ".git").mkdir()
        (tmp_path / "main.py").write_text("print('hi')")

        result = discover_sources(tmp_path)
        assert len(result.repos) == 1
        assert result.repos[0].relative_name == ""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns empty result."""
        result = discover_sources(tmp_path)
        assert result.vaults == []
        assert result.repos == []
        assert result.leftover_paths == []


class TestReconciliation:
    def _setup_db(self, tmp_path: Path) -> tuple:
        """Helper to create a test database connection."""
        from ragling.config import Config
        from ragling.db import get_connection, init_db

        config = Config(db_path=tmp_path / "test.db", embedding_dimensions=4)
        conn = get_connection(config)
        init_db(conn, config)
        return conn, config

    def test_stale_sub_collection_deleted(self, tmp_path: Path) -> None:
        """Sub-collection whose marker no longer exists gets deleted."""
        from ragling.db import get_or_create_collection

        conn, _config = self._setup_db(tmp_path)

        # Create a sub-collection as if a previous run found a vault
        get_or_create_collection(conn, "myproject/old-vault", "system")

        # Current discovery finds no vaults (marker removed)
        result = DiscoveryResult(vaults=[], repos=[], leftover_paths=[])

        deleted = reconcile_sub_collections(conn, "myproject", result)
        assert deleted == ["myproject/old-vault"]

        # Verify it's gone from DB
        row = conn.execute(
            "SELECT id FROM collections WHERE name = ?", ("myproject/old-vault",)
        ).fetchone()
        assert row is None
        conn.close()

    def test_current_sub_collections_preserved(self, tmp_path: Path) -> None:
        """Sub-collections that still have markers are not deleted."""
        from ragling.db import get_or_create_collection

        conn, _config = self._setup_db(tmp_path)

        get_or_create_collection(conn, "myproject/vault", "system")

        vault = DiscoveredSource(
            path=Path("/tmp/vault"), relative_name="vault", source_type="obsidian"
        )
        result = DiscoveryResult(vaults=[vault], repos=[], leftover_paths=[])

        deleted = reconcile_sub_collections(conn, "myproject", result)
        assert deleted == []

        row = conn.execute(
            "SELECT id FROM collections WHERE name = ?", ("myproject/vault",)
        ).fetchone()
        assert row is not None
        conn.close()

    def test_parent_collection_not_touched(self, tmp_path: Path) -> None:
        """The parent project collection is never deleted by reconciliation."""
        from ragling.db import get_or_create_collection

        conn, _config = self._setup_db(tmp_path)
        get_or_create_collection(conn, "myproject", "project")

        result = DiscoveryResult(vaults=[], repos=[], leftover_paths=[])
        deleted = reconcile_sub_collections(conn, "myproject", result)
        assert "myproject" not in deleted

        row = conn.execute("SELECT id FROM collections WHERE name = ?", ("myproject",)).fetchone()
        assert row is not None
        conn.close()
