"""Tests for reranked flag in search tool responses."""

from __future__ import annotations

from ragling.tools.helpers import _build_search_response


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
