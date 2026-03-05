# H1 Results: Token Precision Analysis

**Token counting:** len(text) // 4 (character-based approximation)
**Query strategy:** commit message first; manual task description as fallback when commit message returned empty results

## Results Table

| SHA | Subsystem | full_tokens | rag_tokens | reduction_ratio | coverage | missed_invariants | query_used |
|---|---|---|---|---|---|---|---|
| decd7f5 | Core | 1658 | 498 | 0.30 | partial | INV-4 | manual |
| 91e8c52 | Core | 1658 | 1187 | 0.72 | partial | INV-3, INV-5 | message |
| 1c1a8d6 | Core | 1658 | 527 | 0.32 | full | — | manual |
| 6587df9 | Indexers | 2396 | 492 | 0.21 | full | — | message |
| 8b244d1 | Parsers | 1660 | 906 | 0.55 | full | — | manual |
| 69f4b2d | Indexers | 2396 | 185 | 0.08 | partial | INV-3, INV-4 | manual |
| 339d14d | Core | 1658 | 384 | 0.23 | full | — | manual |
| 3588421 | Core | 1658 | 1033 | 0.62 | partial | INV-5 | manual |
| e5f5e69 | Core | 1658 | 1219 | 0.74 | full | — | manual |
| 6c55a4b | Indexers | 2396 | 866 | 0.36 | full | — | manual |

## Coverage Notes Per Commit

- **decd7f5** — Refactors `_rag_index_via_queue` in `mcp_server.py` to use a `_SYSTEM_COLLECTION_JOBS` lookup dict. Core INV-4 ("Only the IndexingQueue worker thread writes; the MCP `rag_index` tool requires a running queue") is the directly implicated invariant. The RAG result was a `core_mechanism` chunk describing the IndexingQueue dispatch pattern in prose, but the explicit INV-4 statement was absent. **Missed: INV-4.**

- **91e8c52** — Introduces `_db_context` and `_db_and_docstore` context managers; deduplicates all `index_*` CLI commands. Touches SQLite connection management (INV-3: WAL journal mode) and DocStore lifecycle (INV-5: SHA-256 content-addressed cache). RAG returned Indexers invariants (wrong subsystem) and Core `core_mechanism` prose; neither chunk contained the INV-3 or INV-5 statement text. **Missed: INV-3, INV-5.**

- **1c1a8d6** — Extracts `_result_to_dict` helper and routes `rag_batch_search` through `_build_search_response`. No INV-N identifiers appear anywhere in the diff — this is a pure internal refactor. Coverage is vacuously full. RAG returned Core `public_interface` mentioning `SearchResult` and `perform_batch_search`, which is the relevant contract area.

- **6587df9** — Extracts `format_routing.py` with `EXTENSION_MAP`, `SUPPORTED_EXTENSIONS`, `is_supported_extension()`, `parse_and_chunk()`; updates Indexers SPEC.md. No INV-N identifiers in the diff itself. Coverage is vacuously full. RAG returned parsers/purpose and indexers/dependencies — wrong subsystems for the change but no invariant text was needed.

- **8b244d1** — Removes `.md` and `.txt` from `_CODE_EXTENSION_MAP` in `code.py`; updates tests. No INV-N identifiers in diff. Coverage vacuously full. RAG correctly targeted Parsers SPEC.md, returning `testing`, `core_mechanism`, and `failure_modes` sections.

- **69f4b2d** — Extracts `git_commands.py` with pure git subprocess helpers; delegates from `git_indexer.py`. Indexers INV-3 (HEAD SHA comparison for change detection) and INV-4 (git repo watermarks in `collections.description`) are directly implicated. RAG returned a Core `invariants` chunk (wrong subsystem — INV-9 through INV-12 from Core). The Indexers INV-3 and INV-4 text was absent. **Missed: INV-3, INV-4 (Indexers).**

- **339d14d** — Changes `r: Any` to `r: SearchResult` in `_result_to_dict` type annotation. Pure type annotation fix; no INV-N text in diff. Coverage vacuously full. RAG returned partial Core `public_interface` and Indexers `failure_modes` — low relevance but no invariant missed.

- **3588421** — Fixes `_db_and_docstore` resource leak (DocStore created inside the inner try block) and restores path validation for obsidian/calibre. Core INV-5 (DocStore content-addressed cache) is implicated by the resource leak fix. RAG returned Core `public_interface` chunks mentioning DocStore but not the INV-5 invariant text. **Missed: INV-5.**

- **e5f5e69** — Replaces `list[tuple[str, BaseIndexer, bool]]` with `IndexSource` NamedTuple in `index_all`. Pure structural refactor in `cli.py`. No INV-N identifiers in diff. Coverage vacuously full. RAG returned Indexers `public_interface` chunks (wrong subsystem for a CLI change).

- **6c55a4b** — Simplifies factory by splitting into `_build_indexer` + `_resolve_indexer_type` and removing `_create_by_type`. No INV-N identifiers in diff; factory construction pattern has no explicit SPEC invariant. Coverage vacuously full. RAG returned Indexers `public_interface` and `purpose` — correct subsystem.

## Summary

- Mean reduction ratio: **0.41**
- Commits with >30% reduction (ratio < 0.70): **8/10**
- Commits with full coverage: **6/10** (4 partial: decd7f5, 91e8c52, 69f4b2d, 3588421)
- Commits meeting both criteria (ratio < 0.70 AND full coverage): **5/10**

## H1 Verdict

H1 is **not supported** by this dataset. While RAG achieves strong token reduction (8/10 commits below the 0.70 threshold, mean ratio 0.41), coverage falls short: only 6/10 commits have full invariant coverage, and the experiment requires 8/10 on both criteria simultaneously. The four misses share a structural pattern: the invariants implicated by the diffs (Core INV-4, INV-3, INV-5; Indexers INV-3, INV-4) live in the SPEC `invariants` section, but RAG consistently retrieves `core_mechanism`, `public_interface`, or even wrong-subsystem chunks instead. The commit messages and manual descriptions are semantically closer to *what changed* (dispatch logic, context managers, git helpers) than to the *invariant properties* those changes touch, causing the search to miss the `invariants` section. A query strategy that explicitly targets the invariants section (e.g., by appending "invariant" to the query) would likely improve coverage without sacrificing the token reduction.
