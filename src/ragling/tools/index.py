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

    # Code groups: one job per repo
    if collection in config.code_groups:
        for repo_path in config.code_groups[collection]:
            job = IndexJob("directory", repo_path, collection, IndexerType.CODE)
            q.submit(job)
        return {
            "status": "submitted",
            "collection": collection,
            "repos": len(config.code_groups[collection]),
            "indexing": indexing_status.to_dict() if indexing_status else None,
        }

    # Watch collections: discover nested vaults and repos
    if collection in config.watch:
        from ragling.indexers.discovery import discover_sources

        job_count = 0
        for watch_path in config.watch[collection]:
            if not watch_path.is_dir():
                continue
            discovery = discover_sources(watch_path)
            if not discovery.vaults and not discovery.repos:
                job = IndexJob("directory", watch_path, collection, IndexerType.PROJECT)
                q.submit(job)
                job_count += 1
            else:
                for vault in discovery.vaults:
                    if config.is_collection_enabled("obsidian"):
                        job = IndexJob("directory", vault.path, "obsidian", IndexerType.OBSIDIAN)
                        q.submit(job)
                        job_count += 1
                for repo in discovery.repos:
                    job = IndexJob("directory", repo.path, collection, IndexerType.CODE)
                    q.submit(job)
                    job_count += 1
                if discovery.leftover_paths:
                    job = IndexJob("directory", watch_path, collection, IndexerType.PROJECT)
                    q.submit(job)
                    job_count += 1
        return {
            "status": "submitted",
            "collection": collection,
            "jobs": job_count,
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
