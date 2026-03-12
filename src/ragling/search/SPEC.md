# Search

## Purpose

Hybrid vector + full-text search with Reciprocal Rank Fusion. Combines
sqlite-vec embedding distance with FTS5 keyword matching, merges ranked lists
via RRF, and marks stale results whose source files have changed.

## Core Mechanism

Hybrid search runs vector (sqlite-vec) and keyword (FTS5) queries in parallel,
then merges via Reciprocal Rank Fusion with configurable weights (default:
vector 0.7, FTS 0.3, k=60). Stale results are detected by comparing file
mtime to indexed timestamp.

Search supports 8 filter types applied in-memory after retrieval: collection
(by name or type, with hierarchical prefix matching using `/` delimiter),
source_type, visible_collection_ids, sender, author, subsystem, section_type,
and date range. Filtered queries use 50x oversampling (vs 3x for unfiltered)
to ensure sufficient candidates survive filtering.

Cross-encoder rescoring optionally runs after RRF merge. The `rescore()` function
sends top candidates to an Infinity `/rerank` endpoint, replaces RRF scores with
calibrated relevance scores (0.0–1.0), and filters by `min_score`. Rescoring
degrades gracefully — on any failure, original RRF scores are preserved.

**Key files:**
- `search.py` -- hybrid vector + FTS search with RRF
- `search_utils.py` -- FTS query escaping
- `rescore.py` -- cross-encoder rescoring via Infinity API

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `search(conn, query, config, ...)` | MCP server, CLI | Returns `list[SearchResult]` with RRF-merged hybrid results |
| `perform_search(query, filters, config)` | MCP server | High-level search across groups; returns `list[SearchResult]` |
| `perform_batch_search(queries, config)` | MCP server | Batch search; returns `list[list[SearchResult]]` |
| `SearchResult` | MCP server | Dataclass for search output with score, stale flag, metadata |
| `SearchFilters` | MCP server | Dataclass for search input filters (collection, source_type, dates, etc.) |
| `BatchQuery` | MCP server | Dataclass wrapping query + filters for batch search |
| `rrf_merge(vector_results, fts_results, ...)` | Tests, search.py | Merges two ranked lists by Reciprocal Rank Fusion |
| `escape_fts_query(query)` | search.py | Wraps query in quotes, doubles internal quotes per FTS5 spec |
| `rescore(query, results, config, min_score)` | search.py, MCP tools | Rescores results via cross-encoder; returns `(results, reranked_flag)` |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | `rrf_merge()` produces scores that decrease monotonically when iterated in order | Callers rely on results being sorted by relevance |
| INV-2 | `perform_search()` and `perform_batch_search()` validate embedding dimensions match config before searching | Mismatched dimensions corrupt the sqlite-vec index or produce meaningless similarity scores |
| INV-3 | Filtered queries use 50x oversampling; unfiltered use 3x | Ensures sufficient candidates survive in-memory filtering without over-fetching for simple queries |
| INV-4 | Metadata cache is shared between vector and FTS search paths within a single `search()` call | Avoids duplicate database lookups for documents appearing in both result sets |
| INV-5 | `rescore()` preserves all results when `min_score=0` | Consumers expect result count to be stable unless explicitly filtering |
| INV-6 | Rescoring failure returns original RRF results with `reranked=False` | Search must never fail due to an optional reranker being unavailable |
| INV-7 | `reranked` flag accurately reflects whether rescoring was applied | Consumers need to know if scores are calibrated (0–1) or compressed RRF scores |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | Search returns stale results marked `stale=True` | Source file modified or deleted after indexing | Re-index the affected collection; stale marking is informational |
| FAIL-2 | FTS query returns empty results despite matching content existing | Malformed FTS5 query syntax (special characters) | `_fts_search()` catches `sqlite3.OperationalError`, logs warning, returns empty list; search continues with vector results only |
| FAIL-3 | `ValueError` raised before search executes | Query embedding dimensions don't match `config.embedding_dimensions` | Ensure the embedding model matches config; re-embed if model was changed |
| FAIL-4 | Search returns results with compressed RRF scores instead of calibrated scores | Reranker endpoint unavailable, timed out, or returned malformed response | `rescore()` logs warning, returns original results with `reranked=False`; search continues normally |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `db.py` (get_connection, init_db) | internal | `src/ragling/SPEC.md` |
| `embeddings.py` (get_embedding) | internal | `src/ragling/SPEC.md` |
| sqlite-vec | external | N/A -- SQLite extension for vector similarity search |
| httpx | external | N/A -- HTTP client for Infinity reranking API |
