"""MCP tool: rag_indexing_status — check indexing progress."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_indexing_status tool."""

    @mcp.tool()
    def rag_indexing_status() -> dict[str, Any]:
        """Check current indexing status across all collections.

        Returns the current state of any in-progress indexing operations.
        Use this after calling rag_index to monitor progress.

        Returns:
            Dict with 'active' bool and, when active, 'total_remaining'
            count and per-collection breakdown in 'collections'.
        """
        if ctx.indexing_status is None:
            return {"active": False}
        status = ctx.indexing_status.to_dict()
        if status is None:
            return {"active": False}
        return status
