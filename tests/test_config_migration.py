"""Tests for config migration of code_groups/obsidian_vaults into watch."""

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
