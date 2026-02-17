"""Hybrid search engine with vector + FTS and Reciprocal Rank Fusion."""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from ragling.config import Config, load_config
from ragling.db import get_connection, init_db
from ragling.embeddings import get_embedding, serialize_float32
from ragling.search_utils import escape_fts_query

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""

    content: str
    title: str
    metadata: dict
    score: float
    collection: str
    source_path: str
    source_type: str
    stale: bool = False


@dataclass
class SearchFilters:
    """Optional filters for search queries."""

    collection: str | None = None
    source_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sender: str | None = None
    author: str | None = None
    visible_collection_ids: set[int] | None = None

    def is_active(self) -> bool:
        """Return True if any filter field is set."""
        return bool(
            self.collection
            or self.source_type
            or self.sender
            or self.author
            or self.date_from
            or self.date_to
            or self.visible_collection_ids is not None
        )


_FILTERED_OVERSAMPLING = 50
_UNFILTERED_OVERSAMPLING = 3


def _candidate_limit(top_k: int, filters: SearchFilters | None) -> int:
    """Compute how many raw candidates to fetch from an index."""
    has_filters = filters and filters.is_active()
    return top_k * _FILTERED_OVERSAMPLING if has_filters else top_k * _UNFILTERED_OVERSAMPLING


def _apply_filters(
    conn: sqlite3.Connection,
    candidates: list[tuple[int, float]],
    top_k: int,
    filters: SearchFilters | None,
) -> list[tuple[int, float]]:
    """Batch-load metadata and filter candidates in-memory.

    If no filters are active, returns the first top_k candidates unchanged.
    """
    if not filters or not filters.is_active():
        return candidates[:top_k]

    all_ids = [doc_id for doc_id, _ in candidates]
    meta = _batch_load_metadata(conn, all_ids)

    filtered = []
    for doc_id, score in candidates:
        row_meta = meta.get(doc_id)
        if row_meta and _check_filters(row_meta, filters):
            filtered.append((doc_id, score))
            if len(filtered) >= top_k:
                break

    return filtered


def _vector_search(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int,
    filters: SearchFilters | None,
) -> list[tuple[int, float]]:
    """Run vector similarity search via sqlite-vec.

    Returns list of (document_id, distance) tuples.
    """
    query_blob = serialize_float32(query_embedding)

    rows = conn.execute(
        """
        SELECT document_id, distance
        FROM vec_documents
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?
        """,
        (query_blob, _candidate_limit(top_k, filters)),
    ).fetchall()

    candidates = [(row["document_id"], row["distance"]) for row in rows]
    return _apply_filters(conn, candidates, top_k, filters)


def _fts_search(
    conn: sqlite3.Connection,
    query_text: str,
    top_k: int,
    filters: SearchFilters | None,
) -> list[tuple[int, float]]:
    """Run full-text search via FTS5.

    Returns list of (document_id, rank_score) tuples.
    """
    safe_query = escape_fts_query(query_text)
    if not safe_query:
        return []

    try:
        rows = conn.execute(
            """
            SELECT rowid, rank
            FROM documents_fts
            WHERE documents_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, _candidate_limit(top_k, filters)),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("FTS query failed for '%s': %s", safe_query, e)
        return []

    candidates = [(row["rowid"], row["rank"]) for row in rows]
    return _apply_filters(conn, candidates, top_k, filters)


_COLLECTION_TYPES = {"system", "project", "code"}


def _batch_load_metadata(conn: sqlite3.Connection, doc_ids: list[int]) -> dict[int, sqlite3.Row]:
    """Load metadata for multiple documents in a single query.

    Returns a dict mapping document ID to its joined row data.
    """
    if not doc_ids:
        return {}
    placeholders = ",".join("?" * len(doc_ids))
    rows = conn.execute(
        f"""
        SELECT d.id, d.content, d.title, d.metadata,
               d.collection_id, c.name AS collection_name,
               c.collection_type, s.source_type, s.source_path,
               s.file_modified_at
        FROM documents d
        JOIN collections c ON d.collection_id = c.id
        JOIN sources s ON d.source_id = s.id
        WHERE d.id IN ({placeholders})
        """,
        doc_ids,
    ).fetchall()
    return {row["id"]: row for row in rows}


def _check_filters(row: sqlite3.Row | dict, filters: SearchFilters) -> bool:
    """Check if a metadata row passes the given filters (in-memory)."""
    if filters.visible_collection_ids is not None:
        if row["collection_id"] not in filters.visible_collection_ids:
            return False

    if filters.collection:
        if filters.collection in _COLLECTION_TYPES:
            if row["collection_type"] != filters.collection:
                return False
        elif row["collection_name"] != filters.collection:
            return False

    if filters.source_type and row["source_type"] != filters.source_type:
        return False

    if filters.sender or filters.author or filters.date_from or filters.date_to:
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}

        if filters.sender:
            doc_sender = metadata.get("sender", "")
            if filters.sender.lower() not in doc_sender.lower():
                return False

        if filters.author:
            authors = metadata.get("authors", [])
            author_lower = filters.author.lower()
            if not any(author_lower in a.lower() for a in authors):
                return False

        if filters.date_from or filters.date_to:
            doc_date = metadata.get("date", "")
            if filters.date_from and doc_date and doc_date < filters.date_from:
                return False
            if filters.date_to and doc_date and doc_date > filters.date_to:
                return False

    return True


def _mark_stale_results(
    results: list[SearchResult],
    file_modified_at_map: dict[str, str | None],
) -> None:
    """Mark results whose source files have changed or been deleted.

    Args:
        results: Search results to check (mutated in-place).
        file_modified_at_map: Map from source_path to file_modified_at timestamp.
    """
    for result in results:
        try:
            st = os.stat(result.source_path)
        except (FileNotFoundError, OSError):
            result.stale = True
            continue

        indexed_at_str = file_modified_at_map.get(result.source_path)
        if not indexed_at_str:
            continue  # no recorded mtime — can't determine staleness

        try:
            indexed_mtime = datetime.fromisoformat(indexed_at_str).replace(tzinfo=timezone.utc)
            file_mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            if file_mtime > indexed_mtime:
                result.stale = True
        except (ValueError, OSError):
            pass


def rrf_merge(
    vec_results: list[tuple[int, float]],
    fts_results: list[tuple[int, float]],
    k: int = 60,
    vector_weight: float = 0.7,
    fts_weight: float = 0.3,
) -> list[tuple[int, float]]:
    """Merge two ranked lists using Reciprocal Rank Fusion.

    Args:
        vec_results: (document_id, distance) from vector search.
        fts_results: (document_id, rank) from FTS search.
        k: RRF parameter (default 60).
        vector_weight: Weight for vector search scores.
        fts_weight: Weight for FTS search scores.

    Returns:
        Merged list of (document_id, rrf_score) sorted by score descending.
    """
    scores: dict[int, float] = {}

    for rank, (doc_id, _) in enumerate(vec_results):
        scores[doc_id] = scores.get(doc_id, 0.0) + vector_weight / (k + rank + 1)

    for rank, (doc_id, _) in enumerate(fts_results):
        scores[doc_id] = scores.get(doc_id, 0.0) + fts_weight / (k + rank + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def search(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    query_text: str,
    top_k: int,
    filters: SearchFilters | None,
    config: Config,
    visible_collections: list[str] | None = None,
) -> list[SearchResult]:
    """Run hybrid search combining vector similarity and full-text search.

    Args:
        conn: SQLite connection.
        query_embedding: Embedding vector for the query.
        query_text: The raw query text for FTS.
        top_k: Number of results to return.
        filters: Optional search filters.
        config: Application configuration.
        visible_collections: Optional list of collection names to restrict results to.
            None means no restriction (all collections visible).
            Empty list means no collections visible (returns no results).

    Returns:
        List of SearchResult objects sorted by relevance.
    """
    if visible_collections is not None:
        if not visible_collections:
            return []  # empty list = no access
        rows = conn.execute(
            f"SELECT id FROM collections WHERE name IN ({','.join('?' * len(visible_collections))})",
            visible_collections,
        ).fetchall()
        allowed_ids = {row["id"] for row in rows}
        if not allowed_ids:
            return []  # none of the named collections exist
        if filters:
            filters = replace(filters, visible_collection_ids=allowed_ids)
        else:
            filters = SearchFilters(visible_collection_ids=allowed_ids)

    vec_results = _vector_search(conn, query_embedding, top_k, filters)
    fts_results = _fts_search(conn, query_text, top_k, filters)

    merged = rrf_merge(
        vec_results,
        fts_results,
        k=config.search_defaults.rrf_k,
        vector_weight=config.search_defaults.vector_weight,
        fts_weight=config.search_defaults.fts_weight,
    )

    top_merged = merged[:top_k]
    result_ids = [doc_id for doc_id, _ in top_merged]
    meta = _batch_load_metadata(conn, result_ids)

    results: list[SearchResult] = []
    file_modified_at_map: dict[str, str | None] = {}
    for doc_id, score in top_merged:
        row = meta.get(doc_id)
        if row:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            results.append(
                SearchResult(
                    content=row["content"],
                    title=row["title"] or "",
                    metadata=metadata,
                    score=score,
                    collection=row["collection_name"],
                    source_path=row["source_path"],
                    source_type=row["source_type"],
                )
            )
            file_modified_at_map[row["source_path"]] = row["file_modified_at"]

    _mark_stale_results(results, file_modified_at_map)

    return results


def perform_search(
    query: str,
    collection: str | None = None,
    top_k: int = 10,
    source_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sender: str | None = None,
    author: str | None = None,
    group_name: str = "default",
    config: Config | None = None,
    visible_collections: list[str] | None = None,
) -> list[SearchResult]:
    """Run a full hybrid search: load config, connect, embed, search, cleanup.

    This is a high-level convenience wrapper that handles the complete
    config → connection → embedding → search → cleanup flow. Used by both
    the CLI and MCP server to avoid duplicating the same boilerplate.

    Args:
        query: The search query text.
        collection: Optional collection name or type to filter results.
        top_k: Number of results to return.
        source_type: Filter by source type (e.g., 'pdf', 'markdown', 'email').
        date_from: Only results after this date (YYYY-MM-DD).
        date_to: Only results before this date (YYYY-MM-DD).
        sender: Filter by email sender (case-insensitive substring match).
        author: Filter by book author (case-insensitive substring match).
        group_name: Group name for per-group indexes (default "default").
        config: Optional pre-loaded Config. If None, calls load_config().
        visible_collections: Optional list of collection names to restrict results to.
            None means no restriction (all collections visible).

    Returns:
        List of SearchResult objects sorted by relevance.

    Raises:
        ragling.embeddings.OllamaConnectionError: If Ollama is not reachable.
    """
    config = (config or load_config()).with_overrides(group_name=group_name)
    conn = get_connection(config)
    init_db(conn, config)

    try:
        query_embedding = get_embedding(query, config)

        filters = SearchFilters(
            collection=collection,
            source_type=source_type,
            date_from=date_from,
            date_to=date_to,
            sender=sender,
            author=author,
        )

        return search(
            conn,
            query_embedding,
            query,
            top_k,
            filters,
            config,
            visible_collections=visible_collections,
        )
    finally:
        conn.close()
