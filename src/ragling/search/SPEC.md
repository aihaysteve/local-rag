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

**Key files:**
- `search.py` -- hybrid vector + FTS search with RRF
- `search_utils.py` -- FTS query escaping

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

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-6 | `rrf_merge()` produces scores that decrease monotonically when iterated in order | Callers rely on results being sorted by relevance |
| INV-7 | `perform_search()` and `perform_batch_search()` validate embedding dimensions match config before searching | Mismatched dimensions corrupt the sqlite-vec index or produce meaningless similarity scores |
| INV-8 | Filtered queries use 50x oversampling; unfiltered use 3x | Ensures sufficient candidates survive in-memory filtering without over-fetching for simple queries |
| INV-9 | Metadata cache is shared between vector and FTS search paths within a single `search()` call | Avoids duplicate database lookups for documents appearing in both result sets |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-3 | Search returns stale results marked `stale=True` | Source file modified or deleted after indexing | Re-index the affected collection; stale marking is informational |
| FAIL-4 | FTS query returns empty results despite matching content existing | Malformed FTS5 query syntax (special characters) | `_fts_search()` catches `sqlite3.OperationalError`, logs warning, returns empty list; search continues with vector results only |
| FAIL-5 | `ValueError` raised before search executes | Query embedding dimensions don't match `config.embedding_dimensions` | Ensure the embedding model matches config; re-embed if model was changed |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `db.py` (get_connection, init_db) | internal | `src/ragling/SPEC.md` |
| `embeddings.py` (get_embedding) | internal | `src/ragling/SPEC.md` |
| sqlite-vec | external | N/A -- SQLite extension for vector similarity search |
