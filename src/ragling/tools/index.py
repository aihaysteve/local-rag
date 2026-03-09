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
    def rag_index(collection: str, path: str | None = None, plan: bool = False) -> dict[str, Any]:
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
            plan: When True, run a dry-run walk and return the formatted manifest
                without any indexing, parsing, or database writes.
        """
        from ragling.tools.helpers import _get_visible_collections

        visible = _get_visible_collections(ctx.server_config)
        if visible and collection not in visible:
            return {"error": f"Collection '{collection}' is not accessible."}

        config = ctx.get_config()

        if not config.is_collection_enabled(collection):
            return {"error": f"Collection '{collection}' is disabled in config."}

        if plan:
            return _rag_index_plan(collection, path, config)

        q = ctx.get_queue()
        if q is not None:
            return _rag_index_dispatch(collection, path, config, q, ctx)

        # queue_getter present but returned None -> follower mode
        if ctx.queue_getter is not None:
            return {
                "error": "This instance is a read-only follower. "
                "Indexing is handled by the leader process for this group."
            }

        # No queue_getter -> no indexing queue available
        return {"error": "No indexing queue available. Use 'ragling serve' to start the server."}


def _rag_index_plan(
    collection: str,
    path: str | None,
    config: Config,
) -> dict[str, Any]:
    """Run walk-only dry-run and return a formatted manifest."""
    from pathlib import Path as P

    from ragling.indexers.walker import ExclusionConfig, format_plan, walk
    from ragling.tools.helpers import _SYSTEM_COLLECTION_JOBS

    if collection in _SYSTEM_COLLECTION_JOBS:
        return {"error": f"Plan mode is not supported for system collection '{collection}'."}

    # Collect paths to walk (code_groups are auto-migrated into watch by load_config)
    paths: list[P] = []
    if collection in config.watch:
        paths = [p for p in config.watch[collection] if p.is_dir()]
    elif path:
        paths = [P(path)]
    else:
        return {"error": f"Unknown collection '{collection}'. Provide a path for plan mode."}

    exclusion_config = ExclusionConfig(
        global_ragignore_path=P.home() / ".ragling" / "ragignore",
    )

    plan_parts: list[str] = []
    for walk_path in paths:
        result = walk(walk_path, exclusion_config=exclusion_config)
        plan_parts.append(format_plan(result, watch_name=collection, watch_root=walk_path))

    return {
        "status": "plan",
        "collection": collection,
        "plan": "\n---\n".join(plan_parts),
    }


def _rag_index_dispatch(
    collection: str,
    path: str | None,
    config: Config,
    q: IndexingQueue,
    ctx: ToolContext,
) -> dict[str, Any]:
    """Dispatch indexing: queue for system collections, synchronous walker for directories.

    System collections (email, calibre, rss) are submitted to the queue (non-blocking).
    Directory sources (code groups, watch) run the walker pipeline synchronously —
    the MCP tool call blocks until indexing completes.
    """
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

    # Directory sources (code_groups are auto-migrated into watch by load_config)
    if collection in config.watch:
        from ragling.db import get_connection, init_db
        from ragling.sync import sync_directory_source

        conn = get_connection(config)
        init_db(conn, config)
        try:
            total_indexed = 0
            for watch_path in config.watch[collection]:
                if not watch_path.is_dir():
                    continue
                result = sync_directory_source(
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
