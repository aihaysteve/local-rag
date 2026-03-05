# H2 Results: Cross-Cutting Discovery Analysis

**Warm-tier simulation:** Based on modified .py file directories only (not SPEC.md changes in diff)

## Per-Commit Data

### b8665d3 — extract serve orchestration into ServerOrchestrator (control)

**Modified .py files:** `src/ragling/cli.py`, `src/ragling/server.py` (new)

**warm_tier_specs:** Core (`src/ragling/SPEC.md`)

**RAG search used:** Commit message ("extract serve orchestration into ServerOrchestrator") + manual ("MCP server leader election config watching startup orchestration"). Both returned same set.

**rag_specs:** Core, Indexers

**discovered_specs:** Indexers (`src/ragling/indexers/SPEC.md`)

**relevant_discovered:** 0

**Control false positives:** 1 (Indexers returned despite no indexer code changes)

**Analysis:** The Indexers SPEC appeared because "orchestration" and "IndexingQueue" co-occur in Core's description. The commit refactored `cli.py::serve()` into `ServerOrchestrator` — a pure CLI/Core refactor with no indexer logic changes. No Indexers invariant was implicated. This is a false positive.

---

### 0cdc98a — centralize indexer dispatch in factory.py (cross-cutting)

**Modified .py files:** `src/ragling/cli.py`, `src/ragling/indexers/factory.py` (new), `src/ragling/indexing_queue.py`

**warm_tier_specs:** Core (`src/ragling/SPEC.md`), Indexers (`src/ragling/indexers/SPEC.md`)

**RAG search used:** Commit message ("centralize indexer dispatch in factory.py") + manual ("indexer factory pattern collection name dispatch obsidian email calibre"). Best results from manual query.

**rag_specs:** Core, Indexers

**discovered_specs:** none

**relevant_discovered:** 0

**invariants_found:** n/a

**Analysis:** RAG returned exactly the warm-tier set. No additional discovery. The factory centralizes creation of all indexer types — Core and Indexers are the two relevant subsystems, and RAG correctly identified both without surfacing false extras.

---

### bca25f7 — parse_markdown INV-5 gap + document SPEC invariants (cross-cutting)

**Modified .py files:** `src/ragling/parsers/markdown.py`, `tests/test_parsers.py`

**warm_tier_specs:** Parsers (`src/ragling/parsers/SPEC.md`)

**Note:** `src/ragling/document/SPEC.md` was also modified in this commit, but per warm-tier simulation rules it is excluded (SPEC.md is documentation, not a .py file boundary).

**RAG search used:** Commit message ("parse_markdown INV-5 gap document SPEC invariants") + manual ("parser error handling never raise exception fallback graceful failure"). Manual query returned cleaner Parsers-focused results; commit message query surfaced Core invariants.

**rag_specs (commit message query):** Parsers, Core, Core, Parsers, Indexers

**rag_specs (manual query):** Parsers, Parsers, Core, Parsers, Parsers

**Best rag_specs used (commit message — wider discovery):** Parsers, Core, Indexers

**discovered_specs:** Core (`src/ragling/SPEC.md`), Indexers (`src/ragling/indexers/SPEC.md`)

**relevant_discovered:** 0

**invariants_found:** none

**Analysis of discovered specs:**

- **Core SPEC:** The Core invariants returned (INV-10, INV-11, INV-12 around file watching, path deduplication, and rate-limiting) have no connection to parser exception handling. Core INV-9 (embedding batch failures fall back to individual embedding) is the closest structural parallel but applies to embeddings, not parsers. No Core invariant directly constrains how `parse_markdown()` must handle exceptions.

- **Indexers SPEC (INV-9 via testing section):** The Indexers testing table references `TestObsidianIndexerStatusReporting::test_status_file_processed_called_per_file` for INV-9 — "Per-file processing continues after each file (error isolation)". This is the *consumer-side* guarantee that depends on Parsers INV-5. However, the diff adds the top-level try/except *inside* `parse_markdown()` itself — no Indexers code was touched. Indexers' INV-9 is relevant as context (it explains *why* Parsers INV-5 matters) but is not a constraint the diff needed to satisfy directly. Marking as not directly relevant.

Both discovered specs are false positives for this commit.

---

### 6f3c56b — SPEC.md indexing + project onboarding (cross-cutting)

**Modified .py files:** `src/ragling/cli.py`, `src/ragling/config.py`, `src/ragling/indexers/project.py`, `tests/test_cli.py`

**warm_tier_specs:** Core (`src/ragling/SPEC.md`), Indexers (`src/ragling/indexers/SPEC.md`)

**RAG search used:** Commit message ("SPEC.md indexing + project onboarding") + manual ("project init command reserved collection name config file discovery watch directory"). Commit message query returned Indexers + Core. Manual query returned no results.

**rag_specs:** Core, Indexers

**discovered_specs:** none

**relevant_discovered:** 0

**invariants_found:** n/a

**Analysis:** RAG returned exactly the warm-tier set. The commit added the `init` CLI command (Core — `cli.py`, `config.py`) and a comment fix in `project.py` (Indexers). RAG matched the correct two subsystems with no false positives or missed specs.

---

### cbd2ac3 — spec parser cleanup and Core subsystem refactor (cross-cutting)

**Modified .py files (subsystems):**
- Core: `src/ragling/cli.py`, `src/ragling/mcp_server.py`
- Auth: `src/ragling/auth/__init__.py`, `src/ragling/auth.py` → `src/ragling/auth/auth.py`, `src/ragling/tls.py` → `src/ragling/auth/tls.py`, `src/ragling/token_verifier.py` → `src/ragling/auth/token_verifier.py`
- Document: `src/ragling/document/__init__.py`, `src/ragling/chunker.py` → `src/ragling/document/chunker.py`, `src/ragling/docling_bridge.py` → `src/ragling/document/docling_bridge.py`, `src/ragling/docling_convert.py` → `src/ragling/document/docling_convert.py`, `src/ragling/audio_metadata.py` → `src/ragling/document/audio_metadata.py`
- Indexers: `src/ragling/indexers/base.py`, `src/ragling/indexers/calibre_indexer.py`, `src/ragling/indexers/email_indexer.py`, `src/ragling/indexers/git_indexer.py`, `src/ragling/indexers/project.py`, `src/ragling/indexers/rss_indexer.py`
- Parsers: `src/ragling/parsers/spec.py`
- Search: `src/ragling/search/__init__.py`, `src/ragling/search.py` → `src/ragling/search/search.py`, `src/ragling/search_utils.py` → `src/ragling/search/search_utils.py`
- Watchers: `src/ragling/watchers/__init__.py`, `src/ragling/config_watcher.py` → `src/ragling/watchers/config_watcher.py`, `src/ragling/system_watcher.py` → `src/ragling/watchers/system_watcher.py`, `src/ragling/watcher.py` → `src/ragling/watchers/watcher.py`

**warm_tier_specs:** Core, Auth, Document, Indexers, Parsers, Search, Watchers (all 7)

**RAG search used:** Commit message ("spec parser cleanup and Core subsystem refactor") + manual ("module reorganization subsystem package import path rename auth document search watchers"). Both returned only Core + Indexers.

**rag_specs:** Core, Indexers

**discovered_specs:** none (RAG returned a strict subset of the warm-tier set)

**relevant_discovered:** 0 (RAG missed 5 relevant specs: Auth, Document, Parsers, Search, Watchers)

**invariants_found:** n/a

**Analysis:** RAG significantly underperformed the warm-tier for this large structural refactor. The commit renamed modules across 7 subsystems, with each subsystem having specific invariants that constrained the rename. For example:
- Auth INV-7 (`hmac.compare_digest` timing safety) and INV-12 (rate-limit backoff): relevant because `token_verifier.py` changed its internal import path.
- Document INV-1 (DocumentConverter singleton via lru_cache): relevant because `chunker.py`, `docling_convert.py`, `docling_bridge.py` all moved and changed import paths.
- Search INV-6 (`rrf_merge()` monotonic output): relevant because `search.py` moved to `search/search.py`.
- Watchers INV-10 and INV-11: relevant because all three watcher modules were relocated.
- Parsers INV-5 (never raise): relevant because `spec.py` changed its import of `Chunk`, `split_into_windows`, `word_count`.

RAG returned only Core + Indexers, missing the 5 subsystem SPECs most directly implicated by the renames.

---

## Summary Table

| SHA | Type | warm_tier_specs | rag_specs | discovered_specs | relevant_discovered | invariants_found |
|---|---|---|---|---|---|---|
| b8665d3 | control | Core | Core, Indexers | Indexers | 0 (false positive) | none |
| 0cdc98a | cross-cutting | Core, Indexers | Core, Indexers | none | 0 | n/a |
| bca25f7 | cross-cutting | Parsers | Parsers, Core, Indexers | Core, Indexers | 0 | none |
| 6f3c56b | cross-cutting | Core, Indexers | Core, Indexers | none | 0 | n/a |
| cbd2ac3 | cross-cutting | Core, Auth, Document, Indexers, Parsers, Search, Watchers | Core, Indexers | none | 0 (RAG missed 5 specs) | n/a |

## Aggregate Metrics

- Cross-cutting commits where RAG found >= 1 relevant discovered spec: **0/4**
- Total relevant invariants surfaced by RAG beyond warm tier: **0**
- Control false positives: **1** spec returned for b8665d3 beyond Core (Indexers — not implicated by the diff)
- RAG recall on cbd2ac3 (7-subsystem): **2/7** warm-tier specs returned (Core + Indexers only); missed Auth, Document, Parsers, Search, Watchers

## H2 Verdict

H2 is **not supported** by this dataset. RAG discovered zero relevant specs beyond the warm tier across all four cross-cutting commits. In two commits (0cdc98a and 6f3c56b), RAG matched the warm-tier exactly — no discovery but also no false positives. In bca25f7, RAG returned Core and Indexers beyond the warm-tier Parsers spec, but neither contained a directly applicable invariant for the parser exception-handling change. Most critically, for the largest cross-cutting commit (cbd2ac3, 7 subsystems), RAG returned only 2 of 7 relevant specs, missing the Auth, Document, Parsers, Search, and Watchers subsystems entirely — the inverse of the H2 prediction. The pattern suggests RAG retrieval is driven by semantic similarity to "Core" and "Indexers" terms in the index (which dominate the SPEC corpus by token count and cross-subsystem references), making it reliable for those two subsystems but unreliable for discovering constraints in smaller subsystems (Auth, Search, Watchers) or for structurally-diverse commits like mass module renames.
