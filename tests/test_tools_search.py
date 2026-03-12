"""Tests for reranked flag in search tool responses."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ragling.config import Config, RerankerConfig
from ragling.search.search import SearchResult
from ragling.tools.helpers import _build_search_response


def _make_result(content: str = "chunk", score: float = 0.5) -> SearchResult:
    return SearchResult(
        content=content,
        title="T",
        metadata={},
        score=score,
        collection="col",
        source_path="/tmp/x.md",
        source_type="markdown",
    )


class TestBuildSearchResponseReranked:
    """Tests for reranked flag in _build_search_response."""

    def test_reranked_true_in_response(self):
        """reranked=True appears in response."""
        response = _build_search_response([], None, reranked=True)
        assert response["reranked"] is True

    def test_reranked_false_in_response(self):
        """reranked=False appears in response."""
        response = _build_search_response([], None, reranked=False)
        assert response["reranked"] is False

    def test_reranked_defaults_to_false(self):
        """reranked defaults to False when not provided."""
        response = _build_search_response([], None)
        assert response["reranked"] is False


class TestRagSearchPassesRerankParams:
    """Tests that rag_search passes rerank/min_score through to perform_search."""

    @patch("ragling.tools.helpers._get_visible_collections", return_value=None)
    @patch("ragling.tools.helpers._get_user_context", return_value=None)
    @patch("ragling.search.search.perform_search")
    def test_rag_search_passes_rerank_false(self, mock_ps, _uc, _vc):
        """rag_search passes rerank=False to perform_search."""
        mock_ps.return_value = ([], False)

        from ragling.tools.context import ToolContext

        ctx = MagicMock(spec=ToolContext)
        ctx.group_name = "default"
        ctx.server_config = Config(embedding_dimensions=4)
        ctx.indexing_status = None
        ctx.get_config.return_value = Config(query_log_path=None)

        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        from ragling.tools.search import register

        register(mcp, ctx)

        # Call the registered tool function directly
        tool_fn = mcp._tool_manager._tools["rag_search"].fn
        tool_fn(query="test", rerank=False)

        _, kwargs = mock_ps.call_args
        assert kwargs["rerank"] is False

    @patch("ragling.tools.helpers._get_visible_collections", return_value=None)
    @patch("ragling.tools.helpers._get_user_context", return_value=None)
    @patch("ragling.search.search.perform_search")
    def test_rag_search_passes_min_score(self, mock_ps, _uc, _vc):
        """rag_search passes min_score through to perform_search."""
        mock_ps.return_value = ([], False)

        from ragling.tools.context import ToolContext

        ctx = MagicMock(spec=ToolContext)
        ctx.group_name = "default"
        ctx.server_config = Config(embedding_dimensions=4)
        ctx.indexing_status = None
        ctx.get_config.return_value = Config(query_log_path=None)

        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        from ragling.tools.search import register

        register(mcp, ctx)

        tool_fn = mcp._tool_manager._tools["rag_search"].fn
        tool_fn(query="test", min_score=0.5)

        _, kwargs = mock_ps.call_args
        assert kwargs["min_score"] == 0.5


class TestRagBatchSearchPassesRerankParams:
    """Tests that rag_batch_search passes rerank/min_score through."""

    @patch("ragling.tools.helpers._get_visible_collections", return_value=None)
    @patch("ragling.tools.helpers._get_user_context", return_value=None)
    @patch("ragling.search.search.perform_batch_search")
    def test_batch_search_passes_rerank_and_min_score(self, mock_pbs, _uc, _vc):
        """rag_batch_search passes rerank and min_score to perform_batch_search."""
        mock_pbs.return_value = ([[]], [False])

        from ragling.tools.context import ToolContext

        ctx = MagicMock(spec=ToolContext)
        ctx.group_name = "default"
        ctx.server_config = Config(embedding_dimensions=4)
        ctx.indexing_status = None

        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        from ragling.tools.batch_search import register

        register(mcp, ctx)

        tool_fn = mcp._tool_manager._tools["rag_batch_search"].fn
        tool_fn(queries=[{"query": "test"}], rerank=False, min_score=0.3)

        _, kwargs = mock_pbs.call_args
        assert kwargs["rerank"] is False
        assert kwargs["min_score"] == 0.3

    @patch("ragling.tools.helpers._get_visible_collections", return_value=None)
    @patch("ragling.tools.helpers._get_user_context", return_value=None)
    @patch("ragling.search.search.perform_batch_search")
    def test_batch_reranked_all_or_nothing(self, mock_pbs, _uc, _vc):
        """Batch reranked flag is True only when ALL queries were reranked."""
        # One True, one False -> overall False
        mock_pbs.return_value = ([[], []], [True, False])

        from ragling.tools.context import ToolContext

        ctx = MagicMock(spec=ToolContext)
        ctx.group_name = "default"
        ctx.server_config = Config(embedding_dimensions=4)
        ctx.indexing_status = None

        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        from ragling.tools.batch_search import register

        register(mcp, ctx)

        tool_fn = mcp._tool_manager._tools["rag_batch_search"].fn
        result = tool_fn(queries=[{"query": "a"}, {"query": "b"}])

        assert result["reranked"] is False
