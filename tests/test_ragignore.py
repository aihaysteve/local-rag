"""Tests for ragignore template generation."""

from pathlib import Path

from ragling.ragignore import RAGIGNORE_TEMPLATE, ensure_ragignore


class TestRagignore:
    def test_template_is_non_empty(self) -> None:
        assert len(RAGIGNORE_TEMPLATE.strip()) > 0

    def test_creates_ragignore_if_missing(self, tmp_path: Path) -> None:
        ensure_ragignore(config_dir=tmp_path)
        assert (tmp_path / "ragignore").exists()
        assert (tmp_path / "ragignore.default").exists()

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        user_file = tmp_path / "ragignore"
        user_file.write_text("# my custom rules\n*.secret\n")
        ensure_ragignore(config_dir=tmp_path)
        assert user_file.read_text() == "# my custom rules\n*.secret\n"

    def test_updates_default_reference(self, tmp_path: Path) -> None:
        default = tmp_path / "ragignore.default"
        default.write_text("old default")
        ensure_ragignore(config_dir=tmp_path)
        assert default.read_text() == RAGIGNORE_TEMPLATE

    def test_creates_config_dir_if_missing(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "subdir" / ".ragling"
        ensure_ragignore(config_dir=config_dir)
        assert config_dir.exists()
        assert (config_dir / "ragignore").exists()
