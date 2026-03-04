"""Hybrid vector + full-text search with Reciprocal Rank Fusion.

Re-exports for external consumers.  Internal code imports from submodules
directly (e.g. ``from ragling.search.search import ...``) so that test
``patch()`` targets resolve to the defining module.
"""

from ragling.search.search import (
    BatchQuery,
    SearchFilters,
    SearchResult,
    perform_batch_search,
    perform_search,
    rrf_merge,
    search,
)
from ragling.search.search_utils import escape_fts_query

__all__ = [
    "BatchQuery",
    "SearchFilters",
    "SearchResult",
    "escape_fts_query",
    "perform_batch_search",
    "perform_search",
    "rrf_merge",
    "search",
]
