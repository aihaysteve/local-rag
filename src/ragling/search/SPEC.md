# Search

## Purpose

Hybrid vector + full-text search with Reciprocal Rank Fusion. Combines
sqlite-vec embedding distance with FTS5 keyword matching, merges ranked lists
via RRF, and marks stale results whose source files have changed.

## Core Mechanism

`search.py` implements hybrid search via Reciprocal Rank Fusion.
`_vector_search()` queries sqlite-vec by embedding distance; `_fts_search()`
queries FTS5 by keyword match. `rrf_merge()` combines the two ranked lists
with configurable weights (default: vector 0.7, FTS 0.3, k=60).
`_mark_stale_results()` compares file mtime to indexed timestamp, marking
results whose source files have changed or been deleted.

`search_utils.py` provides `escape_fts_query()` for safe FTS5 input by
wrapping the query in quotes and doubling internal quotes per FTS5 spec.

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

## Testing

```bash
uv run pytest tests/test_search.py tests/test_search_utils.py -v
```

### Coverage

| Spec Item | Test | Description |
|---|---|---|
| INV-6 | `test_search.py::TestRRFMerge::test_sorted_by_score_descending` | Asserts scores are sorted in descending order |
| FAIL-3 | `test_search.py::TestMarkStaleResults::test_marks_missing_file_as_stale` | Deleted source file marked stale |
| FAIL-3 | `test_search.py::TestMarkStaleResults::test_marks_modified_file_as_stale` | Modified source file marked stale |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| `config.py` (Config) | internal | `src/ragling/SPEC.md` |
| `db.py` (get_connection, init_db) | internal | `src/ragling/SPEC.md` |
| `embeddings.py` (get_embedding) | internal | `src/ragling/SPEC.md` |
| sqlite-vec | external | N/A -- SQLite extension for vector similarity search |
