"""Tests for config migration of code_groups/obsidian_vaults into watch."""

from pathlib import Path

from ragling.config import migrate_config_dict


class TestConfigMigration:
    def test_code_groups_migrated_to_watch(self) -> None:
        raw = {
            "code_groups": {"myrepo": ["/home/user/repos/myrepo"]},
            "watch": {"existing": ["/home/user/docs"]},
        }
        migrated, warnings = migrate_config_dict(raw)
        assert "myrepo" in migrated["watch"]
        assert "/home/user/repos/myrepo" in migrated["watch"]["myrepo"]
        assert len(warnings) > 0

    def test_obsidian_vaults_migrated_to_watch(self) -> None:
        raw = {
            "obsidian_vaults": ["/home/user/vault"],
        }
        migrated, warnings = migrate_config_dict(raw)
        assert any(
            "/home/user/vault" in str(v)
            for paths in migrated.get("watch", {}).values()
            for v in paths
        )
        assert len(warnings) > 0

    def test_no_migration_when_fields_absent(self) -> None:
        raw = {"watch": {"mywatch": ["/some/path"]}}
        migrated, warnings = migrate_config_dict(raw)
        assert warnings == []
        assert migrated["watch"] == raw["watch"]

    def test_existing_watch_preserved(self) -> None:
        raw = {
            "code_groups": {"repo": ["/repo"]},
            "watch": {"docs": ["/docs"]},
        }
        migrated, warnings = migrate_config_dict(raw)
        assert "docs" in migrated["watch"]
        assert "/docs" in migrated["watch"]["docs"]

    def test_name_collision_handled(self) -> None:
        """If code_groups name matches existing watch name, paths are merged."""
        raw = {
            "code_groups": {"shared": ["/repo"]},
            "watch": {"shared": ["/docs"]},
        }
        migrated, warnings = migrate_config_dict(raw)
        shared_paths = migrated["watch"]["shared"]
        assert "/repo" in shared_paths
        assert "/docs" in shared_paths

    def test_obsidian_vaults_preserved_for_uri_construction(self) -> None:
        """obsidian_vaults is kept in dict (for URI construction) even after migration."""
        raw = {
            "obsidian_vaults": ["/home/user/vault"],
        }
        migrated, _ = migrate_config_dict(raw)
        assert "obsidian_vaults" in migrated
        assert "/home/user/vault" in migrated["obsidian_vaults"]

    def test_code_groups_removed_after_migration(self) -> None:
        """code_groups key is deleted after migration to watch."""
        raw = {
            "code_groups": {"repo": ["/repo"]},
        }
        migrated, _ = migrate_config_dict(raw)
        assert "code_groups" not in migrated


class TestConfigMigrationInLoadConfig:
    """Integration tests verifying migration is wired into load_config."""

    def test_load_config_migrates_obsidian_vaults_to_watch(self, tmp_path: Path) -> None:
        import json

        from ragling.config import load_config

        config_file = tmp_path / "config.json"
        vault = tmp_path / "vault"
        vault.mkdir()
        config_file.write_text(
            json.dumps(
                {
                    "obsidian_vaults": [str(vault)],
                }
            )
        )
        config = load_config(config_file)
        # Obsidian paths should appear in watch
        assert "obsidian" in config.watch
        assert vault in config.watch["obsidian"]
        # And still be available for URI construction
        assert vault in config.obsidian_vaults

    def test_load_config_migrates_code_groups_to_watch(self, tmp_path: Path) -> None:
        import json

        from ragling.config import load_config

        config_file = tmp_path / "config.json"
        repo = tmp_path / "repo"
        repo.mkdir()
        config_file.write_text(
            json.dumps(
                {
                    "code_groups": {"mycode": [str(repo)]},
                }
            )
        )
        config = load_config(config_file)
        # Code group paths should appear in watch
        assert "mycode" in config.watch
        assert repo in config.watch["mycode"]
