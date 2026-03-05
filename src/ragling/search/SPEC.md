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

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-3 | Search returns stale results marked `stale=True` | Source file modified or deleted after indexing | Re-index the affected collection; stale marking is informational |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `db.py` (get_connection, init_db) | internal | `src/ragling/SPEC.md` |
| `embeddings.py` (get_embedding) | internal | `src/ragling/SPEC.md` |
| sqlite-vec | external | N/A -- SQLite extension for vector similarity search |
