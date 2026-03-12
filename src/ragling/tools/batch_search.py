"""MCP tool: rag_batch_search — batched multi-query search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_batch_search tool."""

    @mcp.tool()
    def rag_batch_search(
        queries: list[dict[str, Any]],
        rerank: bool = True,
        min_score: float | None = None,
    ) -> dict[str, Any]:
        """Run multiple searches in a single call, returning all results at once.

        This is more efficient than calling rag_search multiple times because it
        shares one database connection and batches all embedding requests into a
        single Ollama call.

        Each query in the list accepts the same parameters as rag_search:
        query (required), collection, top_k, source_type, date_from, date_to,
        sender, author.

        Example input::

            queries=[
                {"query": "memory allocator", "collection": "code"},
                {"query": "error handling patterns", "top_k": 5},
                {"query": "build system", "collection": "obsidian"}
            ]

        Args:
            queries: List of search query dicts. Each must have a "query" key.
                Other keys match rag_search parameters.
            rerank: Whether to apply cross-encoder rescoring (default True).
                Set to False to skip reranking and use raw RRF scores.
            min_score: Minimum score threshold for results. Only results with
                a score >= this value are returned. None means no threshold.

        Returns:
            Dict with ``results`` (list of per-query result lists, same order as
            input) and optional ``indexing_status``.
        """
        from ragling.config import load_config
        from ragling.embeddings import OllamaConnectionError
        from ragling.search.search import BatchQuery, perform_batch_search
        from ragling.tools.helpers import (
            _apply_user_context_to_results,
            _build_search_response,
            _get_user_context,
            _get_visible_collections,
            _result_to_dict,
        )

        if not queries:
            return _build_search_response([], ctx.indexing_status)

        visible = _get_visible_collections(ctx.server_config)
        user_ctx = _get_user_context(ctx.server_config)

        batch_queries = []
        for q in queries:
            if not isinstance(q, dict) or "query" not in q:
                return {"error": "Each query must be a dict with a 'query' key."}
            batch_queries.append(
                BatchQuery(
                    query=q["query"],
                    collection=q.get("collection"),
                    top_k=q.get("top_k", 10),
                    source_type=q.get("source_type"),
                    date_from=q.get("date_from"),
                    date_to=q.get("date_to"),
                    sender=q.get("sender"),
                    author=q.get("author"),
                    subsystem=q.get("subsystem"),
                    section_type=q.get("section_type"),
                )
            )

        try:
            all_results, reranked_flags = perform_batch_search(
                queries=batch_queries,
                group_name=ctx.group_name,
                config=ctx.server_config,
                visible_collections=visible,
                rerank=rerank,
                min_score=min_score,
            )
            reranked = bool(reranked_flags) and all(reranked_flags)
        except OllamaConnectionError as e:
            return _build_search_response([{"error": str(e)}], ctx.indexing_status)

        obsidian_vaults = (ctx.server_config or load_config()).obsidian_vaults

        all_result_dicts = []
        for result_list in all_results:
            result_dicts = [_result_to_dict(r, obsidian_vaults) for r in result_list]
            if user_ctx:
                result_dicts = _apply_user_context_to_results(result_dicts, user_ctx)
            all_result_dicts.append(result_dicts)

        return _build_search_response(all_result_dicts, ctx.indexing_status, reranked=reranked)
