"""MCP tool: rag_list_collections — list available collections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_list_collections tool."""

    @mcp.tool()
    def rag_list_collections() -> dict[str, Any]:
        """List all available collections with source file counts, chunk counts, and metadata.

        Collections of type 'code' represent code groups that may contain multiple git repos.
        """
        from ragling.db import get_connection, init_db
        from ragling.tools.helpers import (
            _build_list_response,
            _get_visible_collections,
        )

        config = ctx.get_config()
        conn = get_connection(config)
        init_db(conn, config)

        visible = _get_visible_collections(ctx.server_config)

        try:
            rows = conn.execute("""
                SELECT c.name, c.collection_type, c.description, c.created_at,
                       (SELECT COUNT(*) FROM sources s WHERE s.collection_id = c.id) as source_count,
                       (SELECT COUNT(*) FROM documents d WHERE d.collection_id = c.id) as chunk_count,
                       (SELECT MAX(s.last_indexed_at) FROM sources s WHERE s.collection_id = c.id) as last_indexed
                FROM collections c
                ORDER BY c.name
            """).fetchall()

            collections = [
                {
                    "name": row["name"],
                    "type": row["collection_type"],
                    "description": row["description"],
                    "source_count": row["source_count"],
                    "chunk_count": row["chunk_count"],
                    "last_indexed": row["last_indexed"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
            if visible:
                collections = [c for c in collections if c["name"] in visible]
            return _build_list_response(collections, ctx.indexing_status, ctx.role_getter)
        finally:
            conn.close()
