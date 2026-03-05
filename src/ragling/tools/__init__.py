"""Tool registration for the MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register_all_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register all MCP tools on the server."""
    from ragling.tools import (
        batch_search,
        collection_info,
        convert,
        doc_store_info,
        index,
        indexing_status,
        list_collections,
        search,
        search_task,
    )

    search.register(mcp, ctx)
    batch_search.register(mcp, ctx)
    list_collections.register(mcp, ctx)
    collection_info.register(mcp, ctx)
    index.register(mcp, ctx)
    indexing_status.register(mcp, ctx)
    doc_store_info.register(mcp, ctx)
    search_task.register(mcp, ctx)
    convert.register(mcp, ctx)
