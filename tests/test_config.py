"""Tests for ragling.config module."""

import json
import logging
from pathlib import Path
from types import MappingProxyType

import pytest

from ragling.config import Config, UserConfig, load_config


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


class TestUserConfigRepr:
    """UserConfig.__repr__ must mask api_key to prevent accidental leakage."""

    def test_repr_masks_api_key(self) -> None:
        uc = UserConfig(api_key="rag_supersecretkey123")
        r = repr(uc)
        assert "rag_supersecretkey123" not in r
        assert "****" in r

    def test_repr_shows_other_fields(self) -> None:
        uc = UserConfig(
            api_key="rag_secret",
            system_collections=["obsidian"],
            path_mappings={"/a/": "/b/"},
        )
        r = repr(uc)
        assert "obsidian" in r
        assert "/a/" in r


class TestConfigImmutability:
    """Config should be frozen to prevent accidental mutation."""

    def test_config_is_frozen(self) -> None:  # Tests Core INV-1
        config = Config()
        with pytest.raises(AttributeError):
            config.group_name = "mutated"  # type: ignore[misc]

    def test_with_overrides_returns_new_instance(self) -> None:  # Tests Core INV-1
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

    def test_git_commit_subject_blacklist_is_tuple(self) -> None:
        config = Config(git_commit_subject_blacklist=("merge",))
        assert isinstance(config.git_commit_subject_blacklist, tuple)

    def test_default_containers_are_immutable(self) -> None:
        """Default values for container fields should be immutable types."""
        config = Config()
        assert isinstance(config.obsidian_vaults, tuple)
        assert isinstance(config.obsidian_exclude_folders, tuple)
        assert isinstance(config.calibre_libraries, tuple)
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
                    "watch": {"docs": [str(tmp_path / "docs")]},
                    "disabled_collections": ["email"],
                    "git_commit_subject_blacklist": ["merge"],
                    "global_paths": [str(tmp_path / "global")],
                }
            )
        )
        config = load_config(config_file)
        assert isinstance(config.obsidian_vaults, tuple)
        assert isinstance(config.calibre_libraries, tuple)
        assert isinstance(config.watch, MappingProxyType)
        assert isinstance(config.watch["docs"], tuple)
        # obsidian_vaults auto-migrated to watch["obsidian"]
        assert isinstance(config.watch["obsidian"], tuple)
        assert isinstance(config.disabled_collections, frozenset)
        assert isinstance(config.git_commit_subject_blacklist, tuple)
        assert isinstance(config.global_paths, tuple)


class TestOllamaHostConfig:
    def test_default_ollama_host_is_none(self) -> None:
        config = Config()
        assert config.ollama_host is None

    def test_loads_ollama_host_from_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"ollama_host": "http://gpu-box:11434"}))
        config = load_config(config_file)
        assert config.ollama_host == "http://gpu-box:11434"

    def test_missing_ollama_host_defaults_to_none(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"embedding_model": "bge-m3"}))
        config = load_config(config_file)
        assert config.ollama_host is None


class TestEnrichmentConfig:
    """Tests for EnrichmentConfig dataclass and load_config integration."""

    def test_enrichment_config_defaults(self) -> None:
        """EnrichmentConfig has sensible defaults matching current hardcoded behavior."""
        from ragling.config import EnrichmentConfig

        ec = EnrichmentConfig()
        assert ec.image_description is True
        assert ec.code_enrichment is True
        assert ec.formula_enrichment is True
        assert ec.table_structure is True

    def test_config_has_enrichments_field(self) -> None:
        """Config includes an enrichments field with default EnrichmentConfig."""
        from ragling.config import EnrichmentConfig

        config = Config()
        assert isinstance(config.enrichments, EnrichmentConfig)
        assert config.enrichments.image_description is True

    def test_load_config_enrichments(self, tmp_path: Path) -> None:
        """load_config reads enrichment settings from JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "enrichments": {
                        "image_description": False,
                        "code_enrichment": False,
                        "formula_enrichment": False,
                        "table_structure": False,
                    }
                }
            )
        )
        config = load_config(config_file)
        assert config.enrichments.image_description is False
        assert config.enrichments.code_enrichment is False
        assert config.enrichments.formula_enrichment is False
        assert config.enrichments.table_structure is False

    def test_load_config_enrichments_defaults(self, tmp_path: Path) -> None:
        """load_config uses enrichment defaults when not specified."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({}))
        config = load_config(config_file)
        assert config.enrichments.image_description is True

    def test_enrichment_config_is_frozen(self) -> None:
        """EnrichmentConfig should be immutable."""
        from ragling.config import EnrichmentConfig

        ec = EnrichmentConfig()
        with pytest.raises(AttributeError):
            ec.image_description = False  # type: ignore[misc]


class TestLoadConfigResilience:
    """Tests for load_config() resilience on malformed input."""

    def test_truncated_json_returns_defaults(self, tmp_path: Path) -> None:  # Tests Core INV-2
        """Truncated JSON file does not crash; returns default Config."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"embedding_model": "bge-')
        config = load_config(config_file)
        assert isinstance(config, Config)
        assert config.group_name == "default"

    def test_invalid_json_returns_defaults(self, tmp_path: Path) -> None:  # Tests Core INV-2
        """Completely invalid JSON returns default Config."""
        config_file = tmp_path / "config.json"
        config_file.write_text("not json at all {{{")
        config = load_config(config_file)
        assert isinstance(config, Config)

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:  # Tests Core INV-2
        """Empty config file returns default Config."""
        config_file = tmp_path / "config.json"
        config_file.write_text("")
        config = load_config(config_file)
        assert isinstance(config, Config)

    def test_null_bytes_returns_defaults(self, tmp_path: Path) -> None:  # Tests Core INV-2
        """Config file containing null bytes (valid UTF-8) returns default Config."""
        config_file = tmp_path / "config.json"
        config_file.write_bytes(b"\x00\x00\x00\x00")
        config = load_config(config_file)
        assert isinstance(config, Config)

    def test_binary_config_returns_defaults(self, tmp_path: Path) -> None:  # Tests Core INV-2
        """Config file with invalid UTF-8 bytes returns default Config."""
        config_file = tmp_path / "config.json"
        config_file.write_bytes(b"\x80\x81\x82\xff\xfe")
        config = load_config(config_file)
        assert isinstance(config, Config)


class TestMalformedConfigFallback:
    """load_config should fall back to defaults on malformed or unreadable config."""

    def test_malformed_json_falls_back_to_defaults(
        self, tmp_path: Path
    ) -> None:  # Tests Core INV-2
        config_file = tmp_path / "config.json"
        config_file.write_text("{not valid json!!!")
        config = load_config(config_file)
        # Key fields should have default values
        assert config.embedding_model == "bge-m3"
        assert config.group_name == "default"
        assert config.obsidian_vaults == ()

    def test_malformed_json_logs_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("{corrupt")
        with caplog.at_level(logging.ERROR, logger="ragling.config"):
            load_config(config_file)
        assert any("Failed to load config" in msg for msg in caplog.messages)

    def test_unreadable_config_falls_back_to_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")
        config_file.chmod(0o000)
        try:
            config = load_config(config_file)
            assert config.embedding_model == "bge-m3"
            assert config.group_name == "default"
            assert config.obsidian_vaults == ()
        finally:
            config_file.chmod(0o644)


class TestWatchConfig:
    """Tests for the watch config field."""

    def test_default_watch_is_empty(self) -> None:
        config = Config()
        assert config.watch == {}

    def test_watch_is_mapping_proxy(self) -> None:
        config = Config()
        assert isinstance(config.watch, MappingProxyType)

    def test_loads_watch_string_value(self, tmp_path: Path) -> None:
        """A string value is normalized to a single-element tuple."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"watch": {"movie-rec": str(tmp_path / "movie-rec")}}))
        config = load_config(config_file)
        assert "movie-rec" in config.watch
        assert config.watch["movie-rec"] == (tmp_path / "movie-rec",)

    def test_loads_watch_list_value(self, tmp_path: Path) -> None:
        """A list of paths is normalized to a tuple."""
        dir1 = tmp_path / "papers"
        dir2 = tmp_path / "refs"
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"watch": {"research": [str(dir1), str(dir2)]}}))
        config = load_config(config_file)
        assert config.watch["research"] == (dir1, dir2)

    def test_loads_watch_mixed_values(self, tmp_path: Path) -> None:
        """Mix of string and list values in watch config."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "watch": {
                        "single": str(tmp_path / "one"),
                        "multi": [str(tmp_path / "a"), str(tmp_path / "b")],
                    }
                }
            )
        )
        config = load_config(config_file)
        assert config.watch["single"] == (tmp_path / "one",)
        assert config.watch["multi"] == (tmp_path / "a", tmp_path / "b")

    def test_watch_tilde_expansion(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"watch": {"proj": "~/Projects/proj"}}))
        config = load_config(config_file)
        assert "~" not in str(config.watch["proj"][0])

    def test_watch_relative_dot_resolves_to_config_dir(self, tmp_path: Path) -> None:
        """Relative '.' in watch should resolve against config file directory, not CWD."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        config_file = project_dir / "ragling.json"
        config_file.write_text(json.dumps({"watch": {"my-project": "."}}))
        config = load_config(config_file)
        assert config.watch["my-project"][0] == project_dir.resolve()

    def test_watch_relative_subdir_resolves_to_config_dir(self, tmp_path: Path) -> None:
        """Relative subdir in watch should resolve against config file directory."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        config_file = project_dir / "ragling.json"
        config_file.write_text(json.dumps({"watch": {"docs": "docs"}}))
        config = load_config(config_file)
        assert config.watch["docs"][0] == (project_dir / "docs").resolve()

    def test_watch_absolute_path_unchanged(self, tmp_path: Path) -> None:
        """Absolute paths should remain unchanged regardless of config location."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        config_file = project_dir / "ragling.json"
        abs_path = tmp_path / "other-dir"
        config_file.write_text(json.dumps({"watch": {"other": str(abs_path)}}))
        config = load_config(config_file)
        assert config.watch["other"][0] == abs_path

    def test_obsidian_vaults_relative_resolves_to_config_dir(self, tmp_path: Path) -> None:
        """Relative paths in obsidian_vaults should resolve against config dir."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        config_file = project_dir / "ragling.json"
        config_file.write_text(json.dumps({"obsidian_vaults": ["vault"]}))
        config = load_config(config_file)
        assert config.obsidian_vaults[0] == (project_dir / "vault").resolve()

    def test_global_paths_relative_resolves_to_config_dir(self, tmp_path: Path) -> None:
        """Relative paths in global_paths should resolve against config dir."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        config_file = project_dir / "ragling.json"
        config_file.write_text(json.dumps({"global_paths": ["shared"]}))
        config = load_config(config_file)
        assert config.global_paths[0] == (project_dir / "shared").resolve()

    def test_missing_watch_uses_empty_default(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"embedding_model": "bge-m3"}))
        config = load_config(config_file)
        assert config.watch == {}

    def test_watch_values_are_tuples(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"watch": {"proj": str(tmp_path / "proj")}}))
        config = load_config(config_file)
        assert isinstance(config.watch["proj"], tuple)

    def test_with_overrides_converts_watch_dict(self) -> None:
        """with_overrides should accept a plain dict for watch and convert it."""
        config = Config()
        new_config = config.with_overrides(watch={"proj": (Path("/proj"),)})
        assert isinstance(new_config.watch, MappingProxyType)

    def test_load_config_watch_is_immutable(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"watch": {"proj": str(tmp_path / "proj")}}))
        config = load_config(config_file)
        assert isinstance(config.watch, MappingProxyType)

    @pytest.mark.parametrize("name", ["email", "calibre", "rss", "global"])
    def test_rejects_watch_name_matching_system_collection(self, tmp_path: Path, name: str) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"watch": {name: str(tmp_path / "dir")}}))
        with pytest.raises(ValueError, match="system collection"):
            load_config(config_file)

    def test_code_group_and_watch_name_collision_merges(self, tmp_path: Path) -> None:
        """When code_groups and watch share a name, migration merges paths."""
        repo = tmp_path / "repo"
        repo.mkdir()
        watch_dir = tmp_path / "dir"
        watch_dir.mkdir()
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "code_groups": {"my-org": [str(repo)]},
                    "watch": {"my-org": [str(watch_dir)]},
                }
            )
        )
        config = load_config(config_file)
        # Both paths should be merged into watch
        assert repo in config.watch["my-org"]
        assert watch_dir in config.watch["my-org"]


class TestRerankerConfig:
    """Tests for RerankerConfig parsing."""

    def test_reranker_config_defaults(self) -> None:
        """RerankerConfig has sensible defaults when no reranker section in config."""
        from ragling.config import RerankerConfig

        rc = RerankerConfig()
        assert rc.model == "mixedbread-ai/mxbai-rerank-xsmall-v1"
        assert rc.min_score == 0.0
        assert rc.enabled is False
        assert rc.endpoint is None

    def test_reranker_config_from_json(self, tmp_path: Path) -> None:
        """load_config() parses reranker section from config JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "reranker": {
                        "model": "BAAI/bge-reranker-v2-m3",
                        "min_score": 0.3,
                        "enabled": True,
                        "endpoint": "https://infinity.example.com",
                    }
                }
            )
        )
        cfg = load_config(config_file)
        assert cfg.reranker.model == "BAAI/bge-reranker-v2-m3"
        assert cfg.reranker.min_score == 0.3
        assert cfg.reranker.enabled is True
        assert cfg.reranker.endpoint == "https://infinity.example.com"

    def test_reranker_config_absent_means_disabled(self, tmp_path: Path) -> None:
        """When reranker section is absent, reranker is disabled."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({}))
        cfg = load_config(config_file)
        assert cfg.reranker.enabled is False
        assert cfg.reranker.endpoint is None

    def test_reranker_enabled_auto_true_when_endpoint_set(self, tmp_path: Path) -> None:
        """enabled defaults to True when endpoint is provided."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "reranker": {
                        "endpoint": "https://infinity.example.com",
                    }
                }
            )
        )
        cfg = load_config(config_file)
        assert cfg.reranker.enabled is True
        assert cfg.reranker.endpoint == "https://infinity.example.com"


class TestConfigAutoDiscovery:
    """Tests for ragling.json auto-discovery in CWD."""

    def test_discovers_ragling_json_in_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_config(None) should use ragling.json from CWD when present."""
        config_file = tmp_path / "ragling.json"
        config_file.write_text(json.dumps({"embedding_model": "test-model"}))
        monkeypatch.chdir(tmp_path)
        config = load_config(None)
        assert config.embedding_model == "test-model"

    def test_falls_back_to_default_when_no_ragling_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_config(None) should fall back to ~/.ragling/config.json when no ragling.json in CWD."""
        monkeypatch.chdir(tmp_path)
        # No ragling.json in tmp_path — should use defaults (or global config)
        config = load_config(None)
        assert config.embedding_model == "bge-m3"  # default value

    def test_explicit_path_overrides_auto_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit path argument should take precedence over CWD ragling.json."""
        # ragling.json in CWD with one value
        cwd_config = tmp_path / "ragling.json"
        cwd_config.write_text(json.dumps({"embedding_model": "cwd-model"}))
        monkeypatch.chdir(tmp_path)

        # Explicit config with a different value
        explicit_config = tmp_path / "explicit.json"
        explicit_config.write_text(json.dumps({"embedding_model": "explicit-model"}))

        config = load_config(explicit_config)
        assert config.embedding_model == "explicit-model"
