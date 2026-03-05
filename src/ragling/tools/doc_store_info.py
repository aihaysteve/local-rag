"""MCP tool: rag_doc_store_info — list cached documents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_doc_store_info tool."""

    @mcp.tool()
    def rag_doc_store_info() -> list[dict[str, Any]]:
        """List all documents in the shared document cache.

        Shows all source files that have been converted by Docling,
        regardless of which group indexed them. Useful for checking
        what's cached and avoiding redundant conversions.

        Returns a list of dicts, each with:
        - source_path: Original file path
        - content_hash: SHA-256 hash of file contents
        - file_size: File size in bytes
        - file_modified_at: When the file was last modified
        - discovered_at: When the file was first seen
        """
        from ragling.doc_store import DocStore

        config = ctx.get_config()
        store = DocStore(config.shared_db_path)
        try:
            return store.list_sources()
        finally:
            store.close()
