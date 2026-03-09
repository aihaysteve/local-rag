"""MCP tool: rag_index — trigger collection indexing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.config import Config
    from ragling.indexing_queue import IndexingQueue
    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_index tool."""

    @mcp.tool()
    def rag_index(collection: str, path: str | None = None) -> dict[str, Any]:
        """Trigger indexing for a collection.

        Submits an indexing job and returns immediately. Use rag_indexing_status
        to check progress. Returns 'already_indexing' if the collection already
        has queued work.

        For system collections ('obsidian', 'email', 'calibre', 'rss'), uses configured paths.
        For code groups (matching a key in config code_groups), indexes all repos in that group.
        For watch collections (matching a key in config watch), indexes all paths in that entry.
        For project collections, a path argument is required.

        Args:
            collection: Collection name ('obsidian', 'email', 'calibre', 'rss', a code group
                name, a watch collection name, or a project name).
            path: Path to index (required for project collections, or to add a single repo
                to a code group).
        """
        from ragling.tools.helpers import _get_visible_collections

        visible = _get_visible_collections(ctx.server_config)
        if visible and collection not in visible:
            return {"error": f"Collection '{collection}' is not accessible."}

        config = ctx.get_config()

        if not config.is_collection_enabled(collection):
            return {"error": f"Collection '{collection}' is disabled in config."}

        q = ctx.get_queue()
        if q is not None:
            return _rag_index_via_queue(collection, path, config, q, ctx)

        # queue_getter present but returned None -> follower mode
        if ctx.queue_getter is not None:
            return {
                "error": "This instance is a read-only follower. "
                "Indexing is handled by the leader process for this group."
            }

        # No queue_getter -> no indexing queue available
        return {"error": "No indexing queue available. Use 'ragling serve' to start the server."}


def _rag_index_via_queue(
    collection: str,
    path: str | None,
    config: Config,
    q: IndexingQueue,
    ctx: ToolContext,
) -> dict[str, Any]:
    """Route indexing through the IndexingQueue (non-blocking)."""
    from pathlib import Path as P

    from ragling.indexer_types import IndexerType
    from ragling.indexing_queue import IndexJob
    from ragling.tools.helpers import _SYSTEM_COLLECTION_JOBS

    indexing_status = ctx.indexing_status

    # Dedup: reject if collection already has queued work
    if indexing_status and indexing_status.is_collection_active(collection):
        return {
            "status": "already_indexing",
            "collection": collection,
            "indexing": indexing_status.to_dict(),
        }

    # System collections: single job with fixed (job_type, indexer_type)
    if collection in _SYSTEM_COLLECTION_JOBS:
        job_type, indexer_type = _SYSTEM_COLLECTION_JOBS[collection]
        job = IndexJob(job_type, P(path) if path else None, collection, indexer_type)
        q.submit(job)
        return {
            "status": "submitted",
            "collection": collection,
            "indexing": indexing_status.to_dict() if indexing_status else None,
        }

    # Code groups: use unified walker pipeline
    if collection in config.code_groups:
        from ragling.db import get_connection, init_db
        from ragling.sync import _sync_directory_source

        conn = get_connection(config)
        init_db(conn, config)
        try:
            total_indexed = 0
            for repo_path in config.code_groups[collection]:
                if not repo_path.is_dir():
                    continue
                result = _sync_directory_source(
                    conn, config, collection, repo_path, status=indexing_status
                )
                total_indexed += result.indexed
        finally:
            conn.close()
        return {
            "status": "completed",
            "collection": collection,
            "repos": len(config.code_groups[collection]),
            "indexed": total_indexed,
            "indexing": indexing_status.to_dict() if indexing_status else None,
        }

    # Watch collections: use unified walker pipeline
    if collection in config.watch:
        from ragling.db import get_connection, init_db
        from ragling.sync import _sync_directory_source

        conn = get_connection(config)
        init_db(conn, config)
        try:
            total_indexed = 0
            for watch_path in config.watch[collection]:
                if not watch_path.is_dir():
                    continue
                result = _sync_directory_source(
                    conn, config, collection, watch_path, status=indexing_status
                )
                total_indexed += result.indexed
        finally:
            conn.close()
        return {
            "status": "completed",
            "collection": collection,
            "paths": len(config.watch[collection]),
            "indexed": total_indexed,
            "indexing": indexing_status.to_dict() if indexing_status else None,
        }

    # Fallback: project collection (requires path)
    if path:
        job = IndexJob("directory", P(path), collection, IndexerType.PROJECT)
        q.submit(job)
        return {
            "status": "submitted",
            "collection": collection,
            "indexing": indexing_status.to_dict() if indexing_status else None,
        }

    return {"error": f"Unknown collection '{collection}'. Provide a path for project indexing."}
