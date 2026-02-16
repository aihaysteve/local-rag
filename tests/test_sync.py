"""Tests for ragling.sync module."""

from pathlib import Path

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
