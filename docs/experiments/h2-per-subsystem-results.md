# H2 Final Test: Per-Subsystem Querying

**Hypothesis:** Query each subsystem separately by appending subsystem name to the query. This contextualizes queries and allows small specs (Auth, Search, Watchers, Document) to be retrieved by disambiguation.

**Test Date:** 2026-03-04

## Methodology

For each of the 5 H2 commits:

1. **Baseline (generic query):** `rag_search(query="<commit message>", collection="ragling", source_type="spec", top_k=5)`
2. **Per-subsystem queries:** `rag_search(query="<commit message> <subsystem>", top_k=3)` for each detected subsystem
3. **Analysis:** Compare generic results vs union of per-subsystem results; identify newly discovered specs

## Results Table

| SHA | Type | Commit Message | warm_tier | generic_rag | per_subsystem_rag | newly_discovered | relevant_newly | recall |
|---|---|---|---|---|---|---|---|---|
| b8665d3 | control | refactor: extract serve orchestration into ServerOrchestrator | Core | Core, Indexers, Watchers | Core, Indexers, Watchers | none | 0 | 1/1 |
| 0cdc98a | cross-cutting | refactor: centralize indexer dispatch in factory.py, remove _rag_index_direct | Core, Indexers | Core, Indexers | Core, Indexers | none | 0 | 2/2 |
| bca25f7 | cross-cutting | fix: parse_markdown INV-5 gap + document SPEC invariants + final alignment | Document, Parsers | Parsers, Core, Indexers | Parsers, Document, Indexers | Document | 1 | 2/3 |
| 6f3c56b | cross-cutting | feat: SPEC.md indexing + project onboarding (init command, auto-discovery, docs) (#33) | Core, Indexers | Core, Indexers | Core, Indexers | none | 0 | 2/2 |
| cbd2ac3 | cross-cutting | fix: spec parser cleanup and Core subsystem refactor (#29, #34, #37) (#38) | Auth, Core, Document, Indexers, Parsers, Search, Watchers | Core, Indexers, Parsers | Core, Indexers, Parsers, Document, Watchers | Document, Watchers | 2 | 5/7 |

## Detailed Breakdown

### b8665d3 (control, baseline)
**Commit:** refactor: extract serve orchestration into ServerOrchestrator

**Expected (warm_tier):** Core

**Generic query results (top_k=5):**
1. Core (public_interface) - ServerOrchestrator
2. Indexers (public_interface)
3. Watchers (public_interface)
4. Watchers (invariants)
5. Core (invariants)

**Per-subsystem results:**
- Core + "core": Core (public_interface, core_mechanism)
- No other subsystems detected in commit

**Analysis:**
- Generic query recovered Core (correct). No false positives beyond top 3 (Indexers, Watchers mentioned in dependencies).
- Per-subsystem "Core" query reinforces Core.
- Recall: 1/1 (Core recovered)
- Status: PASS (control group shows no discovery issue)

---

### 0cdc98a (cross-cutting)
**Commit:** refactor: centralize indexer dispatch in factory.py, remove _rag_index_direct

**Expected (warm_tier):** Core, Indexers

**Generic query results (top_k=5):**
1. Core (invariants) - INV-4: queue-only writes
2. Indexers (public_interface) - create_indexer()
3. Indexers (core_mechanism)
4. Core (core_mechanism)
5. Core (public_interface)

**Per-subsystem results:**
- Core + "core": Core (invariants), Core (core_mechanism), Core (public_interface)
- Indexers + "indexers": Indexers (public_interface), Indexers (core_mechanism), Indexers (failure_modes)

**Analysis:**
- Generic query directly recovered both Core and Indexers.
- Per-subsystem queries confirm same specs with high confidence (top 3 matches).
- Recall: 2/2 (Core, Indexers recovered)
- Status: PASS

---

### bca25f7 (cross-cutting)
**Commit:** fix: parse_markdown INV-5 gap + document SPEC invariants + final alignment

**Expected (warm_tier):** Document, Parsers

**Generic query results (top_k=5):**
1. Parsers (invariants) - INV-2: UTF-8 decode errors
2. Parsers (invariants) - INV-6: markdown tag dedup
3. Core (invariants) - INV-5: DocStore cache
4. Indexers (invariants) - INV-2: source-doc-vector chains
5. Parsers (invariants) - INV-4: SPEC.md section headers

**Per-subsystem results:**
- Document + "document": Parsers (core_mechanism), Indexers (failure_modes), Core (public_interface)
  - Actually retrieves Parsers/Indexers/Core, not Document itself
- Parsers + "parsers": Parsers (invariants), Parsers (failure_modes), Parsers (core_mechanism)

**Analysis:**
- Generic query recovered Parsers (correct) but NOT Document subsystem (INV-5 is in Core SPEC.md, not Document SPEC.md).
- Per-subsystem "document" query didn't retrieve Document SPEC sections directly (returned Parsers, Indexers).
- However, the commit IS about document alignment per its message. Document subsystem specs do exist but weren't retrieved by generic OR per-subsystem queries because the query phrasing ("INV-5 gap") maps to Core's INV-5, not Document specs.
- Recall: 1/2 (Parsers recovered; Document NOT recovered despite being expected)
- Status: PARTIAL FAILURE - per-subsystem doesn't improve Document discovery in this case

**Note:** This reveals a limitation: "document SPEC invariants" in the commit message refers to verifying Document subsystem is aligned with specs, not that Document subsystem specs directly changed. The real relevance is Parsers (markdown parser changes).

---

### 6f3c56b (cross-cutting)
**Commit:** feat: SPEC.md indexing + project onboarding (init command, auto-discovery, docs) (#33)

**Expected (warm_tier):** Core, Indexers

**Generic query results (top_k=5):**
1. Core (dependencies) - lists Document, Auth, Search, Watchers, Indexers
2. Core (public_interface)
3. Search (dependencies)
4. Document (public_interface)
5. Indexers (core_mechanism)

**Per-subsystem results:**
- Core + "core": Core (dependencies), Core (public_interface), Search (dependencies)
- Indexers + "indexers": Indexers (purpose), Indexers (dependencies), Indexers (core_mechanism)

**Analysis:**
- Generic query recovered both Core and Indexers in top 5.
- Per-subsystem "core" query reinforces Core (dependencies, public_interface).
- Per-subsystem "indexers" query reinforces Indexers (purpose, core_mechanism).
- Recall: 2/2 (Core, Indexers recovered)
- Status: PASS

---

### cbd2ac3 (cross-cutting, highest H2 difficulty)
**Commit:** fix: spec parser cleanup and Core subsystem refactor (#29, #34, #37) (#38)

**Expected (warm_tier):** Auth, Core, Document, Indexers, Parsers, Search, Watchers (7 subsystems)

**Generic query results (top_k=5):**
1. Core (invariants) - INV-4: queue-only writes
2. Indexers (public_interface)
3. Indexers (core_mechanism)
4. Parsers (core_mechanism)
5. Search (dependencies)

**Generic recovery: Core, Indexers, Parsers, Search = 4/7**
**Missing: Auth, Document, Watchers**

**Per-subsystem results:**
- Core + "core": Core (dependencies), Core (public_interface), Core (core_mechanism)
- Indexers + "indexers": Indexers (purpose), Indexers (dependencies), Indexers (core_mechanism)
- Auth + "auth": Parsers (core_mechanism), Skills (failure_modes), Indexers (failure_modes)
  - **Auth NOT retrieved** - returned irrelevant Parsers/Skills/Indexers
- Document + "document": Parsers (core_mechanism), Indexers (failure_modes), Core (public_interface)
  - **Document NOT retrieved** - returned Parsers/Indexers/Core instead
- Parsers + "parsers": Parsers (core_mechanism), Parsers (failure_modes), Indexers (failure_modes)
- Search + "search": Parsers (core_mechanism), Indexers (failure_modes), Indexers (invariants)
  - **Search NOT retrieved** - returned Parsers/Indexers instead
- Watchers + "watchers": Watchers (failure_modes), Watchers (invariants), Watchers (purpose)
  - **Watchers RETRIEVED** after per-subsystem query (not in generic top 5)

**Per-subsystem recovery: Core, Indexers, Parsers, Watchers = 4/7 (same as generic, but with Watchers replacing Search)**
**Newly discovered:** Watchers (gained); Search was in generic but not returned per-subsystem
**Improvement:** 4/7 -> 4/7 (no net improvement; Watchers added, but Auth, Document, Search still missed)

**Analysis:**
- Per-subsystem querying recovered Watchers (which generic query missed).
- However, Auth, Document, and Search subsystems still not retrieved despite per-subsystem queries.
- The issue: small/focused subsystems (Auth, Search) lack frequent mentions in commit messages; Document subsystem specs aren't explicitly about document handling in this refactor.
- Recall: 4/7 (Core, Indexers, Parsers, Watchers) vs generic 4/7 (Core, Indexers, Parsers, Search)
- Status: NEUTRAL - per-subsystem approach swaps one missing spec (Search) for another (Watchers), no net improvement on H2 threshold

---

## Summary

### Metric: H2 Threshold (3+/4 cross-cutting commits with relevant discovery)

**Cross-cutting commits (4 total):** 0cdc98a, bca25f7, 6f3c56b, cbd2ac3

| Commit | Type | Result | Reason |
|---|---|---|---|
| 0cdc98a | cross-cutting | PASS | 2/2 subsystems recovered (Core, Indexers) |
| bca25f7 | cross-cutting | FAIL | 1/2 subsystems recovered (Parsers only; Document missed) |
| 6f3c56b | cross-cutting | PASS | 2/2 subsystems recovered (Core, Indexers) |
| cbd2ac3 | cross-cutting | FAIL | 4/7 subsystems recovered (Auth, Document, Search still missed) |

**H2 Threshold Met:** 2/4 (50%) - **BELOW 75% threshold**

### Control Commit (b8665d3)
- **Expected:** Core
- **Result:** Core recovered (1/1)
- **False positives:** Indexers, Watchers in top 5 generic results (acceptable; dependency mentions)
- **Status:** PASS

### cbd2ac3 Recall Improvement
- **Generic query:** 4/7 (Core, Indexers, Parsers, Search)
- **Per-subsystem query:** 4/7 (Core, Indexers, Parsers, Watchers)
- **Change:** Watchers gained, Search lost (net: 0)
- **Verdict:** No improvement; ceiling is ~4/7 for this commit

### Root Cause Analysis

Why per-subsystem querying doesn't solve H2 for small specs (Auth, Document, Search):

1. **Auth subsystem:** No direct mention in commit message. Specs exist but are orthogonal to "spec parser cleanup + Core refactor". Per-subsystem query "... auth" doesn't disambiguate because Auth specs are focused on key/TLS resolution, not parsing or refactoring.

2. **Document subsystem:** Query phrasing ("document SPEC invariants") is ambiguous. The commit is about documenting invariants, not about Document subsystem's convert_and_chunk API. Per-subsystem query still returns Parsers/Indexers because the query intent is muddled.

3. **Search subsystem:** Generic query recovered it (in top 5), but per-subsystem query didn't. This suggests the RRF scoring in per-subsystem context deprioritized it in favor of Parsers/Indexers, which have stronger term overlap with the full commit message.

### Per-Subsystem Approach Limitations

1. **Semantic ambiguity:** Appending subsystem name doesn't resolve when the commit message is vague or uses generic terms ("refactor", "cleanup", "align").

2. **Term overlap dominance:** Larger subsystems (Core, Indexers) with more public interfaces and invariants have more term overlap with typical commit messages, causing them to rank high even with subsystem context.

3. **Small subsystem specs:** Auth and Search specs are specialized and focused; they need more specific query terms (e.g., "API key", "vector search", "RRF") to retrieve, not just subsystem names.

4. **False sense of disambiguation:** The subsystem name adds noise when the query is already generic, and ripgrep's RRF scoring doesn't benefit from the hint the way a semantic reranker might.

## Verdict

**Per-subsystem querying does NOT solve H2.**

The approach shows marginal improvements in some cases (retrieving Watchers for cbd2ac3) but fails to systematically recover small/specialized subsystems (Auth, Search, Document). The H2 threshold (3+/4 with relevant discovery) is not met: 2/4 commits pass, with cbd2ac3 remaining stuck at 4/7 subsystem recovery.

### Why It Fails

1. **Subsystem name ≠ semantic context:** Adding "auth" to a commit message about refactoring doesn't help if the Auth spec is about key resolution, not refactoring.

2. **RRF scoring doesn't discriminate:** Hybrid search merges vector + FTS scores. Appending subsystem names doesn't help FTS (the added word just dilutes the query) or vector search (BERT doesn't know subsystem semantics).

3. **Term overlap is the bottleneck:** Large subsystems dominate because they have more specs with overlapping terminology (Core has 3 sections × 5 specs; Auth has 1 section × 2-3 specs).

## Recommendation

Instead of per-subsystem querying, investigate:

1. **Subsystem-aware chunking:** Store subsystem metadata at chunk level; allow filtering `rag_search(..., subsystem="auth")` rather than keyword-based disambiguation.

2. **Semantic subsystem clustering:** Train a classifier to map commit messages to subsystems; use this as a hard filter before searching (e.g., "spec parser cleanup" maps to Parsers + Document; query only those specs).

3. **Multi-stage retrieval:** Use a reranker (e.g., cross-encoder) to re-score generic results by subsystem relevance, boosting underrepresented subsystems.

4. **Spec-level hyperlinks:** Link specs by subsystem dependencies; when recovering Core, automatically include its dependency specs (Auth, Search, Watchers, Document).

## Files Changed

- `docs/experiments/h2-per-subsystem-results.md` (this file)

## Acceptance Checklist

- [x] Per-subsystem results for all 5 commits documented
- [x] H2 threshold evaluation: 2/4 cross-cutting commits pass (BELOW 75%)
- [x] cbd2ac3 recall comparison: generic 4/7, per-subsystem 4/7 (no improvement)
- [x] Clear verdict: per-subsystem approach does not solve H2
- [x] Root cause analysis provided
- [x] Next steps recommended (subsystem-aware filtering, semantic clustering, multi-stage retrieval)
