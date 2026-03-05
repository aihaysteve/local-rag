"""MCP server exposing ragling search and index tools.

Thin facade: builds auth, creates ToolContext, delegates to tools/ package.
All helpers re-exported for backward compatibility with existing tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

from ragling.config import Config

# Re-export helpers so existing ``from ragling.mcp_server import X`` keeps working.
# Also re-export get_access_token and load_config for test patch targets.
from ragling.tools.helpers import (  # noqa: F401
    _apply_user_context_to_results,
    _build_list_response,
    _build_search_response,
    _build_source_uri,
    _convert_document,
    _get_allowed_paths,
    _get_user_context,
    _result_to_dict,
    get_access_token,
    load_config,
)

if TYPE_CHECKING:
    from ragling.indexing_queue import IndexingQueue
    from ragling.indexing_status import IndexingStatus


def create_server(
    group_name: str = "default",
    config: Config | None = None,
    indexing_status: IndexingStatus | None = None,
    indexing_queue: IndexingQueue | None = None,
    config_getter: Callable[[], Config] | None = None,
    queue_getter: Callable[[], IndexingQueue | None] | None = None,
    role_getter: Callable[[], str] | None = None,
) -> FastMCP:
    """Create and configure the MCP server with all tools registered.

    Args:
        group_name: Group name for per-group indexes. Passed through to
            config so the correct database path is used.
        config: Optional pre-loaded Config. If None, tools will call
            load_config() on each invocation (backwards compatible).
        indexing_status: Optional IndexingStatus tracker for reporting
            indexing progress in search responses.
        indexing_queue: Optional IndexingQueue for routing indexing jobs
            through the single-writer queue (serve mode). When None and
            no queue_getter is provided, rag_index returns an error.
        queue_getter: Optional callable returning the current IndexingQueue.
            Called on each rag_index invocation for dynamic resolution
            (e.g. follower->leader promotion). Takes precedence over
            the static indexing_queue parameter when provided.
        role_getter: Optional callable returning ``"leader"`` or ``"follower"``.
            Included in ``rag_list_collections`` response when provided.
    """
    from ragling.tools import register_all_tools
    from ragling.tools.context import ToolContext

    server_config = config

    # Build effective queue_getter that falls back to static indexing_queue
    effective_queue_getter = queue_getter
    if effective_queue_getter is None and indexing_queue is not None:
        effective_queue_getter = lambda: indexing_queue  # noqa: E731

    ctx = ToolContext(
        group_name=group_name,
        server_config=server_config,
        indexing_status=indexing_status,
        config_getter=config_getter,
        queue_getter=effective_queue_getter,
        role_getter=role_getter,
    )

    mcp_kwargs: dict[str, Any] = {
        "instructions": "Local RAG system for searching personal knowledge.",
    }

    # Set up auth when users are configured (enables SSE Bearer token validation)
    if server_config and server_config.users:
        from pydantic import AnyHttpUrl

        from mcp.server.auth.settings import AuthSettings

        from ragling.auth.token_verifier import RaglingTokenVerifier

        mcp_kwargs["token_verifier"] = RaglingTokenVerifier(server_config)
        mcp_kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl(
                "https://localhost"
            ),  # Required placeholder; not used for simple bearer auth
            resource_server_url=None,
            required_scopes=[],
        )

    mcp = FastMCP("ragling", **mcp_kwargs)
    register_all_tools(mcp, ctx)
    return mcp
