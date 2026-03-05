"""MCP tool: rag_collection_stats — aggregate statistics across all collections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_collection_stats tool."""

    @mcp.tool()
    def rag_collection_stats() -> dict[str, Any]:
        """Return aggregate statistics across all visible collections.

        Returns a dict with:
        - total_collections: number of collections visible to the current user
        - total_sources: total source files indexed across visible collections
        - total_chunks: total document chunks across visible collections
        - collections_by_type: dict mapping collection_type to count
        - oldest_last_indexed: earliest last_indexed_at timestamp across all
          visible sources, or None if no sources have been indexed
        - newest_last_indexed: most recent last_indexed_at timestamp across all
          visible sources, or None if no sources have been indexed
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
                    "collections_by_type": {},
                    "oldest_last_indexed": None,
                    "newest_last_indexed": None,
                }

            collection_ids = [r["id"] for r in rows]

            # Build a parameterised IN clause — SQLite placeholders
            placeholders = ",".join("?" * len(collection_ids))

            total_sources: int = conn.execute(
                f"SELECT COUNT(*) as cnt FROM sources WHERE collection_id IN ({placeholders})",  # noqa: S608
                collection_ids,
            ).fetchone()["cnt"]

            total_chunks: int = conn.execute(
                f"SELECT COUNT(*) as cnt FROM documents WHERE collection_id IN ({placeholders})",  # noqa: S608
                collection_ids,
            ).fetchone()["cnt"]

            oldest: str | None = conn.execute(
                f"SELECT MIN(last_indexed_at) as ts FROM sources WHERE collection_id IN ({placeholders})",  # noqa: S608
                collection_ids,
            ).fetchone()["ts"]

            newest: str | None = conn.execute(
                f"SELECT MAX(last_indexed_at) as ts FROM sources WHERE collection_id IN ({placeholders})",  # noqa: S608
                collection_ids,
            ).fetchone()["ts"]

            # Aggregate by collection_type
            by_type: dict[str, int] = {}
            for r in rows:
                ctype = r["collection_type"]
                by_type[ctype] = by_type.get(ctype, 0) + 1

            return {
                "total_collections": len(rows),
                "total_sources": total_sources,
                "total_chunks": total_chunks,
                "collections_by_type": by_type,
                "oldest_last_indexed": oldest,
                "newest_last_indexed": newest,
            }
        finally:
            conn.close()
