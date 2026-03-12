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

RESERVED_COLLECTION_NAMES = frozenset({"email", "calibre", "rss", "global"})


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


DEFAULT_RERANKER_MODEL = "mixedbread-ai/mxbai-rerank-xsmall-v1"


@dataclass
class RerankerConfig:
    """Configuration for cross-encoder rescoring after RRF."""

    model: str = DEFAULT_RERANKER_MODEL
    min_score: float = 0.0
    enabled: bool = False
    endpoint: str | None = None


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
    watch: MappingProxyType[str, tuple[Path, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    disabled_collections: frozenset[str] = frozenset()
    git_history_in_months: int = 6
    git_commit_subject_blacklist: tuple[str, ...] = ()
    search_defaults: SearchDefaults = field(default_factory=SearchDefaults)
    reranker: RerankerConfig = field(default_factory=RerankerConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    enrichments: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    shared_db_path: Path = field(default_factory=lambda: DEFAULT_SHARED_DB_PATH)
    group_name: str = "default"
    group_db_dir: Path = field(default_factory=lambda: DEFAULT_GROUP_DB_DIR)
    home: Path | None = None
    global_paths: tuple[Path, ...] = ()
    users: MappingProxyType[str, UserConfig] = field(default_factory=lambda: MappingProxyType({}))
    ollama_host: str | None = None
    query_log_path: Path | None = None

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

        Automatically converts plain dicts for ``watch`` and
        ``users`` to ``MappingProxyType`` so callers don't need to import it.

        Args:
            **kwargs: Field names and new values.

        Returns:
            A new Config instance with the overridden fields.
        """
        if "watch" in kwargs and isinstance(kwargs["watch"], dict):
            kwargs["watch"] = MappingProxyType(kwargs["watch"])
        if "users" in kwargs and isinstance(kwargs["users"], dict):
            kwargs["users"] = MappingProxyType(kwargs["users"])
        return replace(self, **kwargs)


def _expand_path(p: str | Path, config_dir: Path | None = None) -> Path:
    """Expand ~ and resolve a path relative to *config_dir*.

    Absolute paths and ``~`` paths are returned as-is (after expansion).
    Relative paths are resolved against *config_dir* when provided.
    """
    path = Path(p).expanduser()
    if not path.is_absolute() and config_dir is not None:
        path = (config_dir / path).resolve()
    return path


def _expand_path_str(p: str, config_dir: Path | None = None) -> str:
    """Expand ~ in a string path, preserving trailing slashes."""
    expanded = str(_expand_path(p, config_dir))
    if p.endswith("/") and not expanded.endswith("/"):
        expanded += "/"
    return expanded


def migrate_config_dict(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Migrate legacy config fields into the unified watch model.

    Folds code_groups and obsidian_vaults into watch entries.
    Returns the migrated dict and a list of deprecation warnings.

    Called automatically by load_config to handle legacy configs.
    """
    warnings: list[str] = []
    result = dict(raw)
    watch: dict[str, list[str]] = {}

    # Preserve existing watch entries
    if "watch" in result:
        for name, paths in result["watch"].items():
            watch[name] = list(paths) if isinstance(paths, list) else [paths]

    # Migrate code_groups
    if "code_groups" in result:
        for name, paths in result["code_groups"].items():
            path_list = list(paths) if isinstance(paths, list) else [paths]
            if name in watch:
                existing = set(watch[name])
                for p in path_list:
                    if p not in existing:
                        watch[name].append(p)
            else:
                watch[name] = path_list
        warnings.append(
            "Deprecated: 'code_groups' has been migrated to 'watch'. "
            "The walker auto-detects git repos. Please update your config."
        )
        del result["code_groups"]

    # Migrate obsidian_vaults into watch (keep original for URI construction)
    if "obsidian_vaults" in result:
        vault_paths = result["obsidian_vaults"]
        if isinstance(vault_paths, list) and vault_paths:
            if "obsidian" in watch:
                existing = set(watch["obsidian"])
                for p in vault_paths:
                    if p not in existing:
                        watch["obsidian"].append(p)
            else:
                watch["obsidian"] = list(vault_paths)
            warnings.append(
                "Deprecated: 'obsidian_vaults' has been migrated to 'watch'. "
                "The walker auto-detects Obsidian vaults. Please update your config."
            )

    if watch:
        result["watch"] = watch

    return result, warnings


def load_config(path: Path | None = None) -> Config:
    """Load configuration from a JSON file, falling back to defaults.

    Args:
        path: Path to config file. When None, checks for ragling.json in
            the current directory first, then falls back to ~/.ragling/config.json.

    Returns:
        Loaded Config instance with all paths expanded.
    """
    if path is not None:
        config_path = path
    else:
        cwd_config = Path.cwd() / "ragling.json"
        if cwd_config.is_file():
            logger.info("Found ragling.json in current directory: %s", cwd_config)
            config_path = cwd_config
        else:
            config_path = DEFAULT_CONFIG_PATH

    config_dir = config_path.parent.resolve()

    # Ensure config directory exists
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        logger.info("Loading config from %s", config_path)
        try:
            with open(config_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.error("Failed to load config from %s: %s — using defaults", config_path, e)
            data = {}
    else:
        logger.info("No config file found at %s, using defaults", config_path)
        data = {}

    # system_sources provides an alternative location for source config fields,
    # with top-level keys taking precedence for backwards compatibility.
    # Promote to top-level before migration so migrate_config_dict sees them.
    system_sources = data.get("system_sources", {})
    for _ss_key in ("obsidian_vaults", "calibre_libraries"):
        if _ss_key not in data and _ss_key in system_sources:
            data[_ss_key] = system_sources[_ss_key]

    # Auto-migrate legacy config fields (code_groups, obsidian_vaults -> watch)
    data, migration_warnings = migrate_config_dict(data)
    for warning in migration_warnings:
        logger.warning(warning)

    search_data = data.get("search_defaults", {})
    search_defaults = SearchDefaults(
        top_k=search_data.get("top_k", 10),
        rrf_k=search_data.get("rrf_k", 60),
        vector_weight=search_data.get("vector_weight", 0.7),
        fts_weight=search_data.get("fts_weight", 0.3),
    )

    reranker_data = data.get("reranker", {})
    reranker_endpoint = reranker_data.get("endpoint")
    reranker_config = RerankerConfig(
        model=reranker_data.get("model", DEFAULT_RERANKER_MODEL),
        min_score=reranker_data.get("min_score", 0.0),
        enabled=reranker_data.get("enabled", reranker_endpoint is not None),
        endpoint=reranker_endpoint,
    )

    # obsidian_vaults: still populated for URI construction (obsidian:// links),
    # but indexing now goes through the watch pipeline.
    obsidian_vaults_raw = data.get("obsidian_vaults", [])
    obsidian_vaults = tuple(_expand_path(v, config_dir) for v in obsidian_vaults_raw)
    obsidian_exclude_folders = tuple(data.get("obsidian_exclude_folders", []))

    calibre_raw = data.get("calibre_libraries", [])
    calibre_libraries = tuple(_expand_path(v, config_dir) for v in calibre_raw)

    watch_raw: dict[str, tuple[Path, ...]] = {}
    for w_name, w_paths in data.get("watch", {}).items():
        if w_name in RESERVED_COLLECTION_NAMES:
            raise ValueError(f"watch name '{w_name}' conflicts with system collection name")
        if isinstance(w_paths, str):
            watch_raw[w_name] = (_expand_path(w_paths, config_dir),)
        else:
            watch_raw[w_name] = tuple(_expand_path(p, config_dir) for p in w_paths)
    watch: MappingProxyType[str, tuple[Path, ...]] = MappingProxyType(watch_raw)

    disabled_collections = frozenset(data.get("disabled_collections", []))

    # Parse home
    home_raw = data.get("home")
    home = _expand_path(home_raw, config_dir) if home_raw is not None else None

    # Parse global_paths
    global_paths = tuple(_expand_path(p, config_dir) for p in data.get("global_paths", []))

    # Parse users
    users: dict[str, UserConfig] = {}
    for user_name, user_data in data.get("users", {}).items():
        if "api_key" not in user_data:
            raise ValueError(f"User '{user_name}' missing required 'api_key' field in config")
        raw_mappings = user_data.get("path_mappings", {})
        expanded_mappings = {_expand_path_str(k, config_dir): v for k, v in raw_mappings.items()}
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
    emclient_db_path = _expand_path(
        emclient_raw if emclient_raw is not None else emclient_default, config_dir
    )

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
    netnewswire_db_path = _expand_path(nnw_raw if nnw_raw is not None else nnw_default, config_dir)

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

    db_path = _expand_path(data.get("db_path", str(DEFAULT_DB_PATH)), config_dir)

    # query_log_path: absent → default alongside db, null → disabled, string → use it
    if "query_log_path" in data:
        qlp_raw = data["query_log_path"]
        query_log_path = _expand_path(qlp_raw, config_dir) if qlp_raw is not None else None
    else:
        query_log_path = db_path.parent / "query_log.jsonl"

    config = Config(
        db_path=db_path,
        embedding_model=data.get("embedding_model", "bge-m3"),
        embedding_dimensions=data.get("embedding_dimensions", 1024),
        chunk_size_tokens=data.get("chunk_size_tokens", 256),
        chunk_overlap_tokens=data.get("chunk_overlap_tokens", 50),
        obsidian_vaults=obsidian_vaults,
        obsidian_exclude_folders=obsidian_exclude_folders,
        emclient_db_path=emclient_db_path,
        calibre_libraries=calibre_libraries,
        netnewswire_db_path=netnewswire_db_path,
        watch=watch,
        disabled_collections=disabled_collections,
        git_history_in_months=data.get("git_history_in_months", 6),
        git_commit_subject_blacklist=tuple(data.get("git_commit_subject_blacklist", [])),
        search_defaults=search_defaults,
        reranker=reranker_config,
        asr=asr_config,
        enrichments=enrichments_config,
        shared_db_path=_expand_path(
            data.get("shared_db_path", str(DEFAULT_SHARED_DB_PATH)), config_dir
        ),
        group_name=data.get("group_name", "default"),
        group_db_dir=_expand_path(data.get("group_db_dir", str(DEFAULT_GROUP_DB_DIR)), config_dir),
        home=home,
        global_paths=global_paths,
        users=MappingProxyType(users),
        ollama_host=data.get("ollama_host"),
        query_log_path=query_log_path,
    )

    return config
