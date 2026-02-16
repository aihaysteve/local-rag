"""Tests for ragling.config module."""

import json
from pathlib import Path

from ragling.config import Config, load_config


class TestConfigDefaults:
    def test_default_shared_db_path(self) -> None:
        config = Config()
        assert config.shared_db_path == Path.home() / ".ragling" / "doc_store.sqlite"

    def test_default_group_name(self) -> None:
        config = Config()
        assert config.group_name == "default"

    def test_default_group_db_dir(self) -> None:
        config = Config()
        assert config.group_db_dir == Path.home() / ".ragling" / "groups"

    def test_group_index_db_path_property(self) -> None:
        config = Config(group_name="personal")
        expected = config.group_db_dir / "personal" / "index.db"
        assert config.group_index_db_path == expected

    def test_group_index_db_path_default_group(self) -> None:
        config = Config()
        expected = config.group_db_dir / "default" / "index.db"
        assert config.group_index_db_path == expected


class TestConfigFromJson:
    def test_loads_group_fields_from_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "shared_db_path": str(tmp_path / "shared.sqlite"),
                    "group_name": "work",
                    "group_db_dir": str(tmp_path / "groups"),
                }
            )
        )

        config = load_config(config_file)
        assert config.shared_db_path == tmp_path / "shared.sqlite"
        assert config.group_name == "work"
        assert config.group_db_dir == tmp_path / "groups"

    def test_missing_group_fields_use_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = load_config(config_file)
        assert config.group_name == "default"
        assert "ragling" in str(config.shared_db_path)

    def test_tilde_expansion_in_group_paths(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "shared_db_path": "~/custom/doc_store.sqlite",
                    "group_db_dir": "~/custom/groups",
                }
            )
        )

        config = load_config(config_file)
        assert "~" not in str(config.shared_db_path)
        assert "~" not in str(config.group_db_dir)
