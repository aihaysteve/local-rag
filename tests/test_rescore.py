"""Tests for ragling.search.rescore module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from ragling.config import RerankerConfig
from ragling.search.search import SearchResult

_DUMMY_REQUEST = httpx.Request("POST", "https://infinity.example.com/rerank")


def _make_results(scores: list[float]) -> list[SearchResult]:
    """Create SearchResult objects with given scores for testing."""
    return [
        SearchResult(
            content=f"Document {i} content about topic {i}",
            title=f"Doc {i}",
            metadata={},
            score=score,
            collection="test",
            source_path=f"/path/doc{i}.md",
            source_type="markdown",
        )
        for i, score in enumerate(scores)
    ]


def _reranker_config(
    min_score: float = 0.0,
    endpoint: str = "https://infinity.example.com",
    model: str = "mixedbread-ai/mxbai-rerank-xsmall-v1",
) -> RerankerConfig:
    return RerankerConfig(
        model=model,
        min_score=min_score,
        enabled=True,
        endpoint=endpoint,
    )


def _mock_client_with_response(response: httpx.Response) -> MagicMock:
    """Create a mock HTTP client that returns the given response from .post()."""
    client = MagicMock()
    client.post.return_value = response
    return client


def _mock_client_with_error(error: Exception) -> MagicMock:
    """Create a mock HTTP client whose .post() raises the given error."""
    client = MagicMock()
    client.post.side_effect = error
    return client


class TestRescore:
    """Tests for rescore() function."""

    def test_scores_replaced_and_resorted(self):
        """Rescore replaces RRF scores with reranker scores and re-sorts."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014, 0.012])
        config = _reranker_config()

        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.10},
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 2, "relevance_score": 0.50},
                ]
            },
            request=_DUMMY_REQUEST,
        )

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_response(mock_response),
        ):
            rescored, reranked = rescore("test query", results, config)

        assert reranked is True
        assert [r.score for r in rescored] == [0.95, 0.50, 0.10]
        assert [r.title for r in rescored] == ["Doc 1", "Doc 2", "Doc 0"]

    def test_inv5_rescore_preserves_all_results_at_zero_min_score(self):  # Tests INV-5
        """All results preserved when min_score=0."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014, 0.012])
        config = _reranker_config(min_score=0.0)

        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.01},
                    {"index": 1, "relevance_score": 0.02},
                    {"index": 2, "relevance_score": 0.03},
                ]
            },
            request=_DUMMY_REQUEST,
        )

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_response(mock_response),
        ):
            rescored, reranked = rescore("test query", results, config)

        assert len(rescored) == 3
        assert reranked is True

    def test_min_score_filters_low_relevance(self):
        """Results below min_score are filtered out."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014, 0.012, 0.010])
        config = _reranker_config(min_score=0.3)

        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.95},
                    {"index": 1, "relevance_score": 0.50},
                    {"index": 2, "relevance_score": 0.10},
                    {"index": 3, "relevance_score": 0.02},
                ]
            },
            request=_DUMMY_REQUEST,
        )

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_response(mock_response),
        ):
            rescored, reranked = rescore("test query", results, config)

        assert len(rescored) == 2
        assert rescored[0].score == 0.95
        assert rescored[1].score == 0.50

    def test_min_score_override(self):
        """Per-query min_score overrides config default."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014])
        config = _reranker_config(min_score=0.0)

        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.95},
                    {"index": 1, "relevance_score": 0.10},
                ]
            },
            request=_DUMMY_REQUEST,
        )

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_response(mock_response),
        ):
            rescored, reranked = rescore("test query", results, config, min_score=0.5)

        assert len(rescored) == 1
        assert rescored[0].score == 0.95

    def test_inv6_rescore_failure_returns_original_results(self):  # Tests INV-6
        """Connection error returns original results with reranked=False."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014, 0.012])
        original_scores = [r.score for r in results]
        config = _reranker_config()

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_error(httpx.ConnectError("connection refused")),
        ):
            rescored, reranked = rescore("test query", results, config)

        assert reranked is False
        assert [r.score for r in rescored] == original_scores

    def test_timeout_returns_original_results(self):
        """Timeout returns original results with reranked=False."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014])
        config = _reranker_config()

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_error(httpx.TimeoutException("timed out")),
        ):
            rescored, reranked = rescore("test query", results, config)

        assert reranked is False
        assert len(rescored) == 2

    def test_malformed_response_returns_original(self):
        """Malformed JSON response returns original results."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014])
        config = _reranker_config()

        mock_response = httpx.Response(200, json={"unexpected": "format"}, request=_DUMMY_REQUEST)

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_response(mock_response),
        ):
            rescored, reranked = rescore("test query", results, config)

        assert reranked is False

    def test_http_error_returns_original(self):
        """HTTP 500 returns original results."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014])
        config = _reranker_config()

        mock_response = httpx.Response(500, text="Internal Server Error", request=_DUMMY_REQUEST)

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_response(mock_response),
        ):
            rescored, reranked = rescore("test query", results, config)

        assert reranked is False

    def test_inv7_reranked_flag_reflects_rescoring(self):  # Tests INV-7
        """reranked=True only when rescoring actually succeeded."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016])
        config = _reranker_config()

        # Success case
        mock_response = httpx.Response(
            200,
            json={"results": [{"index": 0, "relevance_score": 0.80}]},
            request=_DUMMY_REQUEST,
        )
        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_response(mock_response),
        ):
            _, reranked = rescore("test query", results, config)
        assert reranked is True

        # Failure case
        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_error(httpx.ConnectError("down")),
        ):
            _, reranked = rescore("test query", results, config)
        assert reranked is False

    def test_empty_results_returns_empty(self):
        """Empty input returns empty output without calling the endpoint."""
        from ragling.search.rescore import rescore

        config = _reranker_config()

        with patch("ragling.search.rescore._get_client") as mock_get_client:
            rescored, reranked = rescore("test query", [], config)

        mock_get_client.assert_not_called()
        assert rescored == []
        assert reranked is False

    def test_sends_correct_payload(self):
        """Verify the POST payload sent to Infinity."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014])
        config = _reranker_config(
            endpoint="https://infinity.example.com",
            model="test-model",
        )

        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.1},
                ]
            },
            request=_DUMMY_REQUEST,
        )

        mock_client = _mock_client_with_response(mock_response)
        with patch("ragling.search.rescore._get_client", return_value=mock_client):
            rescore("my query", results, config)

        mock_client.post.assert_called_once_with(
            "https://infinity.example.com/rerank",
            json={
                "model": "test-model",
                "query": "my query",
                "documents": [
                    "Document 0 content about topic 0",
                    "Document 1 content about topic 1",
                ],
                "return_documents": False,
            },
        )

    def test_out_of_bounds_index_returns_original(self):
        """Out-of-bounds index in reranker response falls back gracefully."""
        from ragling.search.rescore import rescore

        results = _make_results([0.016, 0.014])
        config = _reranker_config()

        mock_response = httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 999, "relevance_score": 0.5},
                ]
            },
            request=_DUMMY_REQUEST,
        )

        with patch(
            "ragling.search.rescore._get_client",
            return_value=_mock_client_with_response(mock_response),
        ):
            rescored, reranked = rescore("test query", results, config)

        assert reranked is False
        assert len(rescored) == 2
        assert rescored[0].score == 0.016
