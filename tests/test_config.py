"""Tests for ragling.config module."""

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from ragling.config import Config, load_config


class TestAsrConfigDefaults:
    def test_default_asr_model(self) -> None:
        config = Config()
        assert config.asr.model == "small"

    def test_default_asr_language(self) -> None:
        config = Config()
        assert config.asr.language is None


class TestAsrConfigFromJson:
    def test_loads_asr_from_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"asr": {"model": "turbo", "language": "en"}}))
        config = load_config(config_file)
        assert config.asr.model == "turbo"
        assert config.asr.language == "en"

    def test_missing_asr_uses_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"embedding_model": "bge-m3"}))
        config = load_config(config_file)
        assert config.asr.model == "small"
        assert config.asr.language is None

    def test_partial_asr_merges_with_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"asr": {"model": "turbo"}}))
        config = load_config(config_file)
        assert config.asr.model == "turbo"
        assert config.asr.language is None  # default preserved


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


class TestUserConfig:
    """Tests for user/home/global config fields."""

    def test_default_home_is_none(self) -> None:
        config = Config()
        assert config.home is None

    def test_default_global_paths_is_empty(self) -> None:
        config = Config()
        assert config.global_paths == ()

    def test_default_users_is_empty(self) -> None:
        config = Config()
        assert config.users == {}

    def test_loads_home_from_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"home": str(tmp_path / "groups")}))
        config = load_config(config_file)
        assert config.home == tmp_path / "groups"

    def test_loads_global_paths_from_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        global_dir = tmp_path / "global"
        config_file.write_text(json.dumps({"global_paths": [str(global_dir)]}))
        config = load_config(config_file)
        assert config.global_paths == (global_dir,)

    def test_loads_users_from_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "users": {
                        "kitchen": {
                            "api_key": "rag_test123",
                            "system_collections": ["obsidian"],
                            "path_mappings": {"/host/path/": "/container/path/"},
                        }
                    }
                }
            )
        )
        config = load_config(config_file)
        assert "kitchen" in config.users
        assert config.users["kitchen"].api_key == "rag_test123"
        assert config.users["kitchen"].system_collections == ["obsidian"]
        assert config.users["kitchen"].path_mappings == {"/host/path/": "/container/path/"}

    def test_system_sources_wraps_existing_fields(self, tmp_path: Path) -> None:
        """system_sources in JSON maps to existing Config fields."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "system_sources": {
                        "obsidian_vaults": [str(tmp_path / "vault")],
                        "calibre_libraries": [str(tmp_path / "calibre")],
                    }
                }
            )
        )
        config = load_config(config_file)
        assert config.obsidian_vaults == (tmp_path / "vault",)
        assert config.calibre_libraries == (tmp_path / "calibre",)

    def test_tilde_expansion_in_home(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"home": "~/NanoClaw/groups"}))
        config = load_config(config_file)
        assert "~" not in str(config.home)

    def test_tilde_expansion_in_path_mappings(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "users": {
                        "test": {
                            "api_key": "rag_abc",
                            "path_mappings": {"~/groups/test/": "/workspace/group/"},
                        }
                    }
                }
            )
        )
        config = load_config(config_file)
        mapping_keys = list(config.users["test"].path_mappings.keys())
        assert not any("~" in k for k in mapping_keys)


class TestConfigImmutability:
    """Config should be frozen to prevent accidental mutation."""

    def test_config_is_frozen(self) -> None:
        config = Config()
        with pytest.raises(AttributeError):
            config.group_name = "mutated"  # type: ignore[misc]

    def test_with_overrides_returns_new_instance(self) -> None:
        config = Config(group_name="original")
        new_config = config.with_overrides(group_name="changed")
        assert new_config.group_name == "changed"
        assert config.group_name == "original"
        assert new_config is not config

    def test_with_overrides_preserves_other_fields(self) -> None:
        config = Config(group_name="original", embedding_model="test-model")
        new_config = config.with_overrides(group_name="changed")
        assert new_config.embedding_model == "test-model"

    def test_with_overrides_multiple_fields(self) -> None:
        config = Config()
        new_config = config.with_overrides(group_name="work", embedding_dimensions=512)
        assert new_config.group_name == "work"
        assert new_config.embedding_dimensions == 512

    def test_with_overrides_no_args_returns_copy(self) -> None:
        config = Config()
        new_config = config.with_overrides()
        assert new_config == config
        assert new_config is not config

    def test_with_overrides_rejects_invalid_field(self) -> None:
        config = Config()
        with pytest.raises(TypeError):
            config.with_overrides(nonexistent_field="value")

    def test_obsidian_vaults_is_tuple(self) -> None:
        config = Config(obsidian_vaults=(Path("/a"), Path("/b")))
        assert isinstance(config.obsidian_vaults, tuple)

    def test_calibre_libraries_is_tuple(self) -> None:
        config = Config(calibre_libraries=(Path("/lib"),))
        assert isinstance(config.calibre_libraries, tuple)

    def test_global_paths_is_tuple(self) -> None:
        config = Config(global_paths=(Path("/g"),))
        assert isinstance(config.global_paths, tuple)

    def test_disabled_collections_is_frozenset(self) -> None:
        config = Config(disabled_collections=frozenset({"email"}))
        assert isinstance(config.disabled_collections, frozenset)

    def test_obsidian_exclude_folders_is_tuple(self) -> None:
        config = Config(obsidian_exclude_folders=("_Inbox",))
        assert isinstance(config.obsidian_exclude_folders, tuple)

    def test_code_groups_is_mapping_proxy(self) -> None:
        config = Config(code_groups=MappingProxyType({"org": (Path("/repo"),)}))
        assert isinstance(config.code_groups, MappingProxyType)

    def test_code_groups_values_are_tuples(self) -> None:
        config = Config(code_groups=MappingProxyType({"org": (Path("/repo"),)}))
        assert isinstance(config.code_groups["org"], tuple)

    def test_git_commit_subject_blacklist_is_tuple(self) -> None:
        config = Config(git_commit_subject_blacklist=("merge",))
        assert isinstance(config.git_commit_subject_blacklist, tuple)

    def test_default_containers_are_immutable(self) -> None:
        """Default values for container fields should be immutable types."""
        config = Config()
        assert isinstance(config.obsidian_vaults, tuple)
        assert isinstance(config.obsidian_exclude_folders, tuple)
        assert isinstance(config.calibre_libraries, tuple)
        assert isinstance(config.code_groups, MappingProxyType)
        assert isinstance(config.disabled_collections, frozenset)
        assert isinstance(config.git_commit_subject_blacklist, tuple)
        assert isinstance(config.global_paths, tuple)

    def test_load_config_produces_immutable_containers(self, tmp_path: Path) -> None:
        """load_config should produce immutable container types."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "obsidian_vaults": [str(tmp_path / "vault")],
                    "calibre_libraries": [str(tmp_path / "calibre")],
                    "code_groups": {"org": [str(tmp_path / "repo")]},
                    "disabled_collections": ["email"],
                    "git_commit_subject_blacklist": ["merge"],
                    "global_paths": [str(tmp_path / "global")],
                }
            )
        )
        config = load_config(config_file)
        assert isinstance(config.obsidian_vaults, tuple)
        assert isinstance(config.calibre_libraries, tuple)
        assert isinstance(config.code_groups, MappingProxyType)
        assert isinstance(config.code_groups["org"], tuple)
        assert isinstance(config.disabled_collections, frozenset)
        assert isinstance(config.git_commit_subject_blacklist, tuple)
        assert isinstance(config.global_paths, tuple)

    def test_with_overrides_converts_code_groups_dict(self) -> None:
        """with_overrides should accept a plain dict for code_groups and convert it."""
        config = Config()
        new_config = config.with_overrides(code_groups={"org": (Path("/repo"),)})
        assert isinstance(new_config.code_groups, MappingProxyType)
