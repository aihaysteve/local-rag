"""Shared helper functions for MCP tool implementations."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from mcp.server.auth.middleware.auth_context import get_access_token
from ragling.auth.auth import UserContext
from ragling.config import Config, load_config
from ragling.indexer_types import IndexerType

if TYPE_CHECKING:
    from ragling.indexing_status import IndexingStatus
    from ragling.search.search import SearchResult

logger = logging.getLogger(__name__)

# System collection name -> (job_type, IndexerType) for _rag_index_via_queue dispatch
_SYSTEM_COLLECTION_JOBS: dict[str, tuple[str, IndexerType]] = {
    "email": ("system_collection", IndexerType.EMAIL),
    "calibre": ("system_collection", IndexerType.CALIBRE),
    "rss": ("system_collection", IndexerType.RSS),
}


def _build_source_uri(
    source_path: str,
    source_type: str,
    metadata: dict,
    collection: str,
    obsidian_vaults: Sequence[Any] | None = None,
) -> str | None:
    """Build a clickable URI for a search result's original source.

    Returns an obsidian://, vscode://, file://, https://, or None depending on the source:
    - Obsidian vault files: obsidian://open URI (opens directly in Obsidian app)
    - Code files: vscode://file URI (opens in VS Code at the correct line)
    - Other file-based sources (calibre, project): file:// URI
    - RSS articles: https:// URL from metadata
    - Email and git commits: None (no meaningful URI available)

    Args:
        source_path: The source_path from the sources table.
        source_type: The source_type from the sources table.
        metadata: Parsed metadata dict from the documents table.
        collection: The collection name the result belongs to.
        obsidian_vaults: List of configured Obsidian vault paths (needed
            to construct obsidian:// URIs).

    Returns:
        A URI string or None if no meaningful link can be constructed.
    """
    # RSS articles have a web URL in metadata
    if source_type == "rss":
        return metadata.get("url") or None

    # Email messages and git commits have no openable URI
    if source_type in ("email", "commit"):
        return None

    # Virtual paths (calibre description-only, git commit refs) are not openable
    if source_path.startswith(("calibre://", "git://")):
        return None

    # Obsidian vault files — use obsidian:// URI to open in the app
    if collection == "obsidian" and obsidian_vaults:
        obsidian_uri = _build_obsidian_uri(source_path, obsidian_vaults)
        if obsidian_uri:
            return obsidian_uri

    # Code files — use vscode:// URI to open in VS Code at the correct line
    if source_type == "code":
        start_line = metadata.get("start_line", 1)
        return f"vscode://file{quote(source_path, safe='/')}:{start_line}"

    # Everything else is a real file path — return as file:// URI
    return f"file://{quote(source_path, safe='/')}"


def _build_obsidian_uri(source_path: str, vault_paths: Sequence[Any]) -> str | None:
    """Build an obsidian://open URI for a file inside an Obsidian vault.

    Matches the source_path against known vault paths to extract the vault
    name and the file path relative to the vault root.

    The URI format is: obsidian://open?vault=VAULT_NAME&file=RELATIVE/PATH

    Args:
        source_path: Absolute file path of the indexed document.
        vault_paths: List of configured Obsidian vault root paths.

    Returns:
        An obsidian:// URI string, or None if the path doesn't match any vault.
    """
    for vault_path in vault_paths:
        vault_str = str(Path(vault_path).expanduser().resolve())
        if source_path.startswith(vault_str + "/"):
            vault_name = Path(vault_str).name
            relative_path = source_path[len(vault_str) + 1 :]
            return (
                f"obsidian://open?vault={quote(vault_name, safe='')}"
                f"&file={quote(relative_path, safe='/')}"
            )
    return None


def _apply_user_context_to_results(
    results: list[dict[str, Any]], user_ctx: UserContext
) -> list[dict[str, Any]]:
    """Apply path mappings to search results for a user.

    Creates copies of each result dict with source_path and source_uri
    mapped through the user's path mappings.

    Args:
        results: List of search result dicts with source_path and source_uri keys.
        user_ctx: User context containing path mappings.

    Returns:
        New list of result dicts with mapped paths.
    """
    from ragling.path_mapping import apply_forward, apply_forward_uri

    mapped = []
    for r in results:
        r = dict(r)  # copy to avoid mutating the original
        r["source_path"] = apply_forward(r["source_path"], user_ctx.path_mappings)
        r["source_uri"] = apply_forward_uri(r.get("source_uri"), user_ctx.path_mappings)
        mapped.append(r)
    return mapped


def _build_search_response(
    results: list[dict[str, Any]] | list[list[dict[str, Any]]],
    indexing_status: IndexingStatus | None = None,
) -> dict[str, Any]:
    """Build search response with optional indexing status.

    Args:
        results: List of search result dicts (single search) or list of
            per-query result lists (batch search).
        indexing_status: Optional indexing status tracker.

    Returns:
        Response dict with 'results' and 'indexing' keys.
    """
    return {
        "results": results,
        "indexing": indexing_status.to_dict() if indexing_status else None,
    }


def _result_to_dict(
    r: SearchResult,
    obsidian_vaults: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Convert a SearchResult to a response dict.

    Args:
        r: A SearchResult object.
        obsidian_vaults: Obsidian vault paths for URI construction.

    Returns:
        Dict with title, content, collection, source_type, source_path,
        source_uri, score, metadata, and stale fields.
    """
    return {
        "title": r.title,
        "content": r.content,
        "collection": r.collection,
        "source_type": r.source_type,
        "source_path": r.source_path,
        "source_uri": _build_source_uri(
            r.source_path,
            r.source_type,
            r.metadata,
            r.collection,
            obsidian_vaults,
        ),
        "score": round(r.score, 4),
        "metadata": r.metadata,
        "stale": r.stale,
    }


def _build_list_response(
    collections: list[dict[str, Any]],
    indexing_status: IndexingStatus | None = None,
    role_getter: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Build list-collections response with optional indexing status and role.

    Args:
        collections: List of collection dicts.
        indexing_status: Optional indexing status tracker.
        role_getter: Optional callable returning ``"leader"`` or ``"follower"``.

    Returns:
        Response dict with 'result' key, plus 'indexing' when active
        and 'role' when getter is provided.
    """
    response: dict[str, Any] = {"result": collections}
    if role_getter is not None:
        response["role"] = role_getter()
    if indexing_status:
        status = indexing_status.to_dict()
        if status:
            response["indexing"] = status
    return response


def _get_allowed_paths(config: Config) -> list[Path]:
    """Collect all configured source directories for path validation.

    Gathers resolved absolute paths from all configured sources: obsidian vaults,
    calibre libraries, home directory, global paths, and watch directories.

    Args:
        config: Application configuration.

    Returns:
        List of resolved Path objects representing allowed directories.
    """
    allowed: list[Path] = []

    for vault in config.obsidian_vaults:
        allowed.append(Path(vault).resolve())

    for lib in config.calibre_libraries:
        allowed.append(Path(lib).resolve())

    if config.home is not None:
        allowed.append(Path(config.home).resolve())

    for gp in config.global_paths:
        allowed.append(Path(gp).resolve())

    for watch_paths in config.watch.values():
        for watch_path in watch_paths:
            allowed.append(Path(watch_path).resolve())

    return allowed


def _convert_document(
    file_path: str,
    path_mappings: dict[str, str],
    restrict_paths: bool = False,
    config: Config | None = None,
) -> str:
    """Convert a document to markdown text.

    Applies reverse path mapping if needed, then reads or converts the file.
    When ``restrict_paths`` is True, the resolved host path must be within
    one of the configured source directories.

    Args:
        file_path: Path to the file (may be a container path).
        path_mappings: Host->container mappings (reversed for lookup).
        restrict_paths: When True, reject paths outside configured directories.
            Should be True for SSE (remote user) requests.
        config: Application config (required when restrict_paths is True).

    Returns:
        Markdown text content, or error message.
    """
    from pathlib import Path as P

    from ragling.path_mapping import apply_reverse

    host_path = apply_reverse(file_path, path_mappings)
    resolved = P(host_path).expanduser().resolve()

    if restrict_paths and config is not None:
        allowed = _get_allowed_paths(config)
        if not any(resolved.is_relative_to(ap) for ap in allowed):
            return "Error: file not accessible"

    if not resolved.exists():
        return "Error: file not found"

    # For markdown, just read directly
    if resolved.suffix.lower() == ".md":
        return resolved.read_text(encoding="utf-8", errors="replace")

    # For other formats, try Docling conversion via doc_store cache
    try:
        from ragling.doc_store import DocStore
        from ragling.document.docling_convert import convert_and_chunk

        effective_config = config or load_config()
        doc_store = DocStore(effective_config.shared_db_path)
        try:
            chunks = convert_and_chunk(resolved, doc_store)
            return "\n\n".join(c.text for c in chunks)
        finally:
            doc_store.close()
    except Exception:
        logger.exception("Document conversion failed for %s", resolved)
        return "Error: conversion failed"


def _get_user_context(config: Config | None) -> UserContext | None:
    """Derive UserContext from the current request's access token.

    Uses the contextvar set by FastMCP's AuthContextMiddleware.
    Returns None when unauthenticated (stdio) or when the user is unknown.

    Args:
        config: Application config with users.

    Returns:
        UserContext if authenticated and user exists in config, None otherwise.
    """
    if config is None or not config.users:
        return None
    try:
        access_token = get_access_token()
    except Exception:
        return None
    if access_token is None:
        return None
    username = access_token.client_id
    user_config = config.users.get(username)
    if user_config is None:
        return None
    return UserContext(
        username=username,
        system_collections=user_config.system_collections,
        path_mappings=user_config.path_mappings,
    )


def _get_visible_collections(server_config: Config | None) -> list[str] | None:
    """Compute the list of collections visible to the current user.

    Returns None when unauthenticated (all collections visible).
    """
    user_ctx = _get_user_context(server_config)
    if not user_ctx:
        return None
    global_coll = "global" if server_config and server_config.global_paths else None
    return user_ctx.visible_collections(global_collection=global_coll)


def _detect_subsystems_from_paths(file_paths: list[str]) -> list[str]:
    """Detect subsystem names from file paths by finding SPEC.md directories.

    Walks each file path upward to find the containing subsystem directory
    (identified by having a SPEC.md in the repo's subsystem layout).

    Uses the path structure convention: ``src/ragling/<subsystem>/`` maps
    to subsystem name ``<subsystem>``, and ``src/ragling/`` itself maps to
    ``Core`` (the root subsystem).
    """
    # Known subsystem directories from the project layout
    _SUBSYSTEM_DIRS = {
        "src/ragling/auth": "Auth",
        "src/ragling/document": "Document",
        "src/ragling/indexers": "Indexers",
        "src/ragling/parsers": "Parsers",
        "src/ragling/search": "Search",
        "src/ragling/watchers": "Watchers",
    }
    _CORE_PREFIX = "src/ragling/"

    subsystems: list[str] = []
    seen: set[str] = set()

    for fp in file_paths:
        # Normalize path
        fp = fp.lstrip("./")
        matched = False
        for prefix, name in _SUBSYSTEM_DIRS.items():
            if fp.startswith(prefix + "/") or fp == prefix:
                if name not in seen:
                    subsystems.append(name)
                    seen.add(name)
                matched = True
                break
        if not matched and fp.startswith(_CORE_PREFIX) and "Core" not in seen:
            subsystems.append("Core")
            seen.add("Core")

    return subsystems
