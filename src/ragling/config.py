"""Configuration loading and validation for ragling."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".ragling"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_DB_PATH = DEFAULT_CONFIG_DIR / "rag.db"
DEFAULT_SHARED_DB_PATH = DEFAULT_CONFIG_DIR / "doc_store.sqlite"
DEFAULT_GROUP_DB_DIR = DEFAULT_CONFIG_DIR / "groups"


@dataclass
class AsrConfig:
    """ASR (speech-to-text) configuration."""

    model: str = "small"
    language: str | None = None


@dataclass(frozen=True)
class EnrichmentConfig:
    """Document enrichment pipeline configuration.

    Controls which Docling enrichments are enabled during document conversion.
    All enrichments are enabled by default to match previous hardcoded behavior.
    """

    image_description: bool = True
    code_enrichment: bool = True
    formula_enrichment: bool = True
    table_structure: bool = True


@dataclass
class SearchDefaults:
    """Default search parameters."""

    top_k: int = 10
    rrf_k: int = 60
    vector_weight: float = 0.7
    fts_weight: float = 0.3


@dataclass
class UserConfig:
    """Per-user configuration for SSE access control."""

    api_key: str
    system_collections: list[str] = field(default_factory=list)
    path_mappings: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"UserConfig(api_key='****', "
            f"system_collections={self.system_collections!r}, "
            f"path_mappings={self.path_mappings!r})"
        )


@dataclass(frozen=True)
class Config:
    """Application configuration (immutable).

    Use ``with_overrides()`` to derive a new Config with changed fields.
    """

    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    embedding_model: str = "bge-m3"
    embedding_dimensions: int = 1024
    chunk_size_tokens: int = 256
    chunk_overlap_tokens: int = 50
    obsidian_vaults: tuple[Path, ...] = ()
    obsidian_exclude_folders: tuple[str, ...] = ()
    emclient_db_path: Path = field(
        default_factory=lambda: Path.home() / "Library" / "Application Support" / "eM Client"
    )
    calibre_libraries: tuple[Path, ...] = ()
    netnewswire_db_path: Path = field(
        default_factory=lambda: (
            Path.home()
            / "Library"
            / "Containers"
            / "com.ranchero.NetNewsWire-Evergreen"
            / "Data"
            / "Library"
            / "Application Support"
            / "NetNewsWire"
            / "Accounts"
        )
    )
    code_groups: MappingProxyType[str, tuple[Path, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    disabled_collections: frozenset[str] = frozenset()
    git_history_in_months: int = 6
    git_commit_subject_blacklist: tuple[str, ...] = ()
    search_defaults: SearchDefaults = field(default_factory=SearchDefaults)
    asr: AsrConfig = field(default_factory=AsrConfig)
    enrichments: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    shared_db_path: Path = field(default_factory=lambda: DEFAULT_SHARED_DB_PATH)
    group_name: str = "default"
    group_db_dir: Path = field(default_factory=lambda: DEFAULT_GROUP_DB_DIR)
    home: Path | None = None
    global_paths: tuple[Path, ...] = ()
    # TODO: users could be MappingProxyType[str, UserConfig] for full immutability,
    # but the churn is not worth it since users is not mutated after construction.
    users: dict[str, UserConfig] = field(default_factory=dict)
    ollama_host: str | None = None

    @property
    def group_index_db_path(self) -> Path:
        """Path to this group's per-group index database."""
        return self.group_db_dir / self.group_name / "index.db"

    def is_collection_enabled(self, name: str) -> bool:
        """Check if a collection is enabled for indexing.

        Args:
            name: Collection name (e.g., 'obsidian', 'email', 'calibre', 'rss',
                  or any user-created collection name).

        Returns:
            True if the collection is not in the disabled_collections set.
        """
        return name not in self.disabled_collections

    def with_overrides(self, **kwargs: Any) -> Config:
        """Return a new Config with the specified fields replaced.

        Automatically converts plain dicts for ``code_groups`` to
        ``MappingProxyType`` so callers don't need to import it.

        Args:
            **kwargs: Field names and new values.

        Returns:
            A new Config instance with the overridden fields.
        """
        if "code_groups" in kwargs and isinstance(kwargs["code_groups"], dict):
            kwargs["code_groups"] = MappingProxyType(kwargs["code_groups"])
        return replace(self, **kwargs)


def _expand_path(p: str | Path) -> Path:
    """Expand ~ and resolve a path."""
    return Path(p).expanduser()


def _expand_path_str(p: str) -> str:
    """Expand ~ in a string path, preserving trailing slashes."""
    expanded = str(Path(p).expanduser())
    if p.endswith("/") and not expanded.endswith("/"):
        expanded += "/"
    return expanded


def load_config(path: Path | None = None) -> Config:
    """Load configuration from a JSON file, falling back to defaults.

    Args:
        path: Path to config file. Defaults to ~/.ragling/config.json.

    Returns:
        Loaded Config instance with all paths expanded.
    """
    config_path = path or DEFAULT_CONFIG_PATH

    # Ensure config directory exists
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        logger.info("Loading config from %s", config_path)
        with open(config_path) as f:
            data = json.load(f)
    else:
        logger.info("No config file found at %s, using defaults", config_path)
        data = {}

    search_data = data.get("search_defaults", {})
    search_defaults = SearchDefaults(
        top_k=search_data.get("top_k", 10),
        rrf_k=search_data.get("rrf_k", 60),
        vector_weight=search_data.get("vector_weight", 0.7),
        fts_weight=search_data.get("fts_weight", 0.3),
    )

    # system_sources provides an alternative location for source config fields,
    # with top-level keys taking precedence for backwards compatibility.
    system_sources = data.get("system_sources", {})

    obsidian_vaults_raw = (
        data["obsidian_vaults"]
        if "obsidian_vaults" in data
        else system_sources.get("obsidian_vaults", [])
    )
    obsidian_vaults = tuple(_expand_path(v) for v in obsidian_vaults_raw)
    obsidian_exclude_folders = tuple(data.get("obsidian_exclude_folders", []))

    calibre_raw = (
        data["calibre_libraries"]
        if "calibre_libraries" in data
        else system_sources.get("calibre_libraries", [])
    )
    calibre_libraries = tuple(_expand_path(v) for v in calibre_raw)

    code_groups_raw: dict[str, tuple[Path, ...]] = {}
    for cg_name, paths in data.get("code_groups", {}).items():
        code_groups_raw[cg_name] = tuple(_expand_path(p) for p in paths)
    code_groups: MappingProxyType[str, tuple[Path, ...]] = MappingProxyType(code_groups_raw)
    disabled_collections = frozenset(data.get("disabled_collections", []))

    # Parse home
    home_raw = data.get("home")
    home = _expand_path(home_raw) if home_raw is not None else None

    # Parse global_paths
    global_paths = tuple(_expand_path(p) for p in data.get("global_paths", []))

    # Parse users
    users: dict[str, UserConfig] = {}
    for user_name, user_data in data.get("users", {}).items():
        if "api_key" not in user_data:
            raise ValueError(f"User '{user_name}' missing required 'api_key' field in config")
        raw_mappings = user_data.get("path_mappings", {})
        expanded_mappings = {_expand_path_str(k): v for k, v in raw_mappings.items()}
        users[user_name] = UserConfig(
            api_key=user_data["api_key"],
            system_collections=user_data.get("system_collections", []),
            path_mappings=expanded_mappings,
        )

    # emclient_db_path: top-level > system_sources > default
    emclient_raw = (
        data["emclient_db_path"]
        if "emclient_db_path" in data
        else system_sources.get("emclient_db_path")
    )
    emclient_default = str(Path.home() / "Library" / "Application Support" / "eM Client")
    emclient_db_path = _expand_path(emclient_raw if emclient_raw is not None else emclient_default)

    # netnewswire_db_path: top-level > system_sources > default
    nnw_raw = (
        data["netnewswire_db_path"]
        if "netnewswire_db_path" in data
        else system_sources.get("netnewswire_db_path")
    )
    nnw_default = str(
        Path.home()
        / "Library"
        / "Containers"
        / "com.ranchero.NetNewsWire-Evergreen"
        / "Data"
        / "Library"
        / "Application Support"
        / "NetNewsWire"
        / "Accounts"
    )
    netnewswire_db_path = _expand_path(nnw_raw if nnw_raw is not None else nnw_default)

    asr_data = data.get("asr", {})
    asr_config = AsrConfig(
        model=asr_data.get("model", "small"),
        language=asr_data.get("language"),
    )

    enrichments_data = data.get("enrichments", {})
    enrichments_config = EnrichmentConfig(
        image_description=enrichments_data.get("image_description", True),
        code_enrichment=enrichments_data.get("code_enrichment", True),
        formula_enrichment=enrichments_data.get("formula_enrichment", True),
        table_structure=enrichments_data.get("table_structure", True),
    )

    config = Config(
        db_path=_expand_path(data.get("db_path", str(DEFAULT_DB_PATH))),
        embedding_model=data.get("embedding_model", "bge-m3"),
        embedding_dimensions=data.get("embedding_dimensions", 1024),
        chunk_size_tokens=data.get("chunk_size_tokens", 256),
        chunk_overlap_tokens=data.get("chunk_overlap_tokens", 50),
        obsidian_vaults=obsidian_vaults,
        obsidian_exclude_folders=obsidian_exclude_folders,
        emclient_db_path=emclient_db_path,
        calibre_libraries=calibre_libraries,
        netnewswire_db_path=netnewswire_db_path,
        code_groups=code_groups,
        disabled_collections=disabled_collections,
        git_history_in_months=data.get("git_history_in_months", 6),
        git_commit_subject_blacklist=tuple(data.get("git_commit_subject_blacklist", [])),
        search_defaults=search_defaults,
        asr=asr_config,
        enrichments=enrichments_config,
        shared_db_path=_expand_path(data.get("shared_db_path", str(DEFAULT_SHARED_DB_PATH))),
        group_name=data.get("group_name", "default"),
        group_db_dir=_expand_path(data.get("group_db_dir", str(DEFAULT_GROUP_DB_DIR))),
        home=home,
        global_paths=global_paths,
        users=users,
        ollama_host=data.get("ollama_host"),
    )

    return config
