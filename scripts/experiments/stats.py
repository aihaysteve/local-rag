"""MCP tool: rag_stats — per-collection indexing statistics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_stats tool."""

    @mcp.tool()
    def rag_stats() -> dict[str, Any]:
        """Return per-collection indexing statistics.

        Returns a dict with:
        - total_collections: number of collections visible to the current user
        - total_sources: total source files indexed across visible collections
        - total_chunks: total document chunks across visible collections
        - collections: list of per-collection stats, each with:
          - name: collection name
          - collection_type: collection type (e.g., 'system', 'project')
          - source_count: number of sources in this collection
          - chunk_count: number of chunks in this collection
          - last_indexed: most recent last_indexed_at timestamp for sources
                          in this collection, or None
        """
        from ragling.db import get_connection, init_db
        from ragling.tools.helpers import _get_visible_collections

        config = ctx.get_config()
        conn = get_connection(config)
        init_db(conn, config)

        visible = _get_visible_collections(ctx.server_config)

        try:
            # Fetch all collections respecting visibility filter
            rows = conn.execute(
                "SELECT id, name, collection_type FROM collections ORDER BY name"
            ).fetchall()

            if visible is not None:
                rows = [r for r in rows if r["name"] in visible]

            if not rows:
                return {
                    "total_collections": 0,
                    "total_sources": 0,
                    "total_chunks": 0,
                    "collections": [],
                }

            # Collect per-collection statistics
            collections_list = []
            total_sources = 0
            total_chunks = 0

            for row in rows:
                coll_id = row["id"]
                coll_name = row["name"]
                coll_type = row["collection_type"]

                # Get source count for this collection
                source_count: int = conn.execute(
                    "SELECT COUNT(*) as cnt FROM sources WHERE collection_id = ?",
                    (coll_id,),
                ).fetchone()["cnt"]

                # Get chunk count for this collection
                chunk_count: int = conn.execute(
                    "SELECT COUNT(*) as cnt FROM documents WHERE collection_id = ?",
                    (coll_id,),
                ).fetchone()["cnt"]

                # Get last indexed timestamp for this collection
                last_indexed: str | None = conn.execute(
                    "SELECT MAX(last_indexed_at) as ts FROM sources WHERE collection_id = ?",
                    (coll_id,),
                ).fetchone()["ts"]

                collections_list.append(
                    {
                        "name": coll_name,
                        "collection_type": coll_type,
                        "source_count": source_count,
                        "chunk_count": chunk_count,
                        "last_indexed": last_indexed,
                    }
                )

                total_sources += source_count
                total_chunks += chunk_count

            return {
                "total_collections": len(rows),
                "total_sources": total_sources,
                "total_chunks": total_chunks,
                "collections": collections_list,
            }
        finally:
            conn.close()
