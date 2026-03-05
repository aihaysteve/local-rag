# H2 Final Test: Invariant-Level Chunking Results

**Hypothesis:** Invariant-level chunking (one chunk per INV-N) enables retrieval of small specs that are invisible at section level.

**Index state:** Ragling collection re-indexed with invariant-level chunks for the invariants section. All other sections remain section-level.

## Per-Commit Analysis

### b8665d3 — extract serve orchestration into ServerOrchestrator (control)

**warm_tier_specs:** Core

**rag_specs_section_level (top_k=10):** Core, Indexers

**rag_specs_invariant_level (top_k=5):** Core, Indexers

**newly_discovered:** Indexers (consistent with section-level retrieval)

**relevant_newly_discovered:** 0 (same false positive as before)

**Verdict:** No improvement. Invariant-level chunking does not change the retrieval pattern for this control commit. Indexers remains a false positive (commit only touched Core orchestration, not indexer logic).

---

### 0cdc98a — centralize indexer dispatch in factory.py (cross-cutting)

**warm_tier_specs:** Core, Indexers

**rag_specs_section_level (top_k=10):** Core, Indexers

**rag_specs_invariant_level (top_k=5):** Core, Indexers

**newly_discovered:** none

**relevant_newly_discovered:** 0

**Verdict:** No change. Both section-level and invariant-level retrieval matched the warm tier exactly. The factory commit is correctly identified as Core + Indexers with no excess or missing specs.

---

### bca25f7 — parse_markdown INV-5 gap + document SPEC invariants (cross-cutting)

**warm_tier_specs:** Parsers

**rag_specs_section_level (top_k=10):** Parsers, Core, Indexers

**rag_specs_invariant_level (top_k=5):** Parsers, Core, Parsers, Indexers, Parsers

**newly_discovered (invariant vs section):** None (Core and Indexers already found at section level)

**relevant_newly_discovered:** 0 (Core INV-10/11/12 and Indexers INV-9 from testing section remain false positives)

**Note on invariant-level:** The invariant-level search returned Parsers multiple times (3/5 of top-5 results), indicating stronger semantic affinity for Parsers when chunks are broken down to invariant granularity. However, no *new* specs were discovered beyond what section-level already found.

**Verdict:** No improvement in discovery. The false positives (Core and Indexers) persist. The stronger Parsers signal in invariant-level results confirms the commit's relevance but does not reveal missed specs.

---

### 6f3c56b — SPEC.md indexing + project onboarding (cross-cutting)

**warm_tier_specs:** Core, Indexers

**rag_specs_section_level (top_k=10):** Core, Indexers

**rag_specs_invariant_level (top_k=5):** Indexers, Indexers, Core, Indexers, Core

**newly_discovered:** none

**relevant_newly_discovered:** 0

**Verdict:** No change in the set of discovered specs. Both retrieval methods identified the correct two subsystems. Invariant-level chunking reorders the results (more Indexers early) but returns the same subsystem set.

---

### cbd2ac3 — spec parser cleanup and Core subsystem refactor (cross-cutting, 7 subsystems)

**warm_tier_specs:** Core, Auth, Document, Indexers, Parsers, Search, Watchers (all 7)

**rag_specs_section_level (top_k=10):** Core, Indexers

**rag_specs_invariant_level (top_k=5):** Indexers, Core, Indexers, Indexers, Indexers

**newly_discovered (invariant vs section):** none (same two subsystems, just reordered)

**relevant_newly_discovered:** 0 (RAG still missed Auth, Document, Parsers, Search, Watchers)

**Verdict:** Critical failure. Even with invariant-level chunking, the largest cross-cutting commit (7 subsystems) is still retrieved as only Core + Indexers. The invariant-level approach does not recover the missing 5 specs. Invariant-level chunking made Indexers more prominent (4/5 results), but failed to surface Auth, Document, Parsers, Search, or Watchers — the very subsystems that should be discovered via invariant-level search if the hypothesis were true.

---

## Summary Table

| SHA | Type | warm_tier | rag_section_level | rag_invariant_level | newly_discovered | relevant_newly | Verdict |
|---|---|---|---|---|---|---|---|
| b8665d3 | control | Core | Core, Indexers | Core, Indexers | none | 0 (false positive persists) | No improvement |
| 0cdc98a | cross-cutting | Core, Indexers | Core, Indexers | Core, Indexers | none | 0 | Perfect match both levels |
| bca25f7 | cross-cutting | Parsers | Parsers, Core, Indexers | Parsers, Core, Parsers, Indexers, Parsers | none | 0 | No new specs; false positives remain |
| 6f3c56b | cross-cutting | Core, Indexers | Core, Indexers | Indexers, Core, Indexers, Core, Indexers | none | 0 | Same specs, different order |
| cbd2ac3 | cross-cutting | All 7 | Core, Indexers | Indexers, Core, Indexers, Indexers, Indexers | none | 0 (missed 5 specs) | Critical failure; no recovery |

## Aggregate Metrics

- **Commits with newly discovered relevant specs (invariant vs section):** 0/4 cross-cutting commits
- **cbd2ac3 recall:** 2/7 (section-level: 2/7, invariant-level: 2/7) — **no improvement**
- **Control false positives:** 1 (b8665d3 Indexers) — persists in both chunking levels
- **Cross-cutting commits with exact warm-tier match:** 2/4 (0cdc98a, 6f3c56b)
- **Cross-cutting commits with false positives:** 2/4 (bca25f7, cbd2ac3)

## H2 Final Verdict

**Invariant-level chunking does NOT meet the H2 threshold (3+/4 cross-cutting with relevant discovery).**

- **Expected outcome:** Small specs (Auth, Search, Watchers) become retrievable with invariant-level granularity
- **Actual outcome:** Same retrieval patterns as section-level chunking. Zero new specs discovered across all 4 cross-cutting commits.
- **cbd2ac3 (most critical test case):** Missed all 5 renamed subsystems (Auth, Document, Parsers, Search, Watchers) at both section level AND invariant level — indicating the problem is not chunking granularity but semantic corpus skew (Core and Indexers dominate index token density and cross-subsystem references).

### Root Cause Analysis

The hypothesis assumed that breaking invariants into individual chunks would improve retrieval of small, invariant-dense subsystems. However, the results show:

1. **No new specs discovered:** Even with 5x finer granularity (invariants as separate chunks), the search results remain the same subsystems as section-level chunking.
2. **Stronger Indexers/Core signal:** Invariant-level chunking actually amplified retrieval of Core and Indexers (4/5 results for cbd2ac3 were Indexers), suggesting these subsystems have more distinctive invariant terminology.
3. **Missing subsystems invisible even at invariant level:** Auth, Document, Parsers, Search, Watchers have invariants with less distinctive vocabulary, or their invariants are too brief to match commit message semantics. The problem is not granularity but semantic distance.

### Recommendation

**Do not proceed with invariant-level chunking as the solution for H2.** The experiment conclusively shows that finer chunking granularity alone does not recover missing specs in cross-cutting commits. The root issue is:

- Commits that touch many subsystems (like renames across 7 modules) use language ("module", "import", "path", "rename") that does not appear in the SPEC invariants.
- Small subsystems (Auth, Search, Watchers) have fewer, less semantically distinctive invariants than Core and Indexers.
- The warm-tier simulation (based on modified .py file directories) is a strong signal, but RAG fails to replicate it via semantic search.

**Next phase options:**
1. Abandon pure semantic RAG for SPEC discovery; use structured cross-reference indexing (e.g., import graph analysis) to map code changes to specs.
2. Augment specs with commit-simulation data (synthetic training examples of cross-cutting changes and their required specs).
3. Accept H2 as unsupported by semantic search and document the limitations.

---

## Appendix: Invariant Samples by Subsystem

To understand why some subsystems remained invisible even with invariant-level chunks:

**Core (11 invariants, highly distinctive):**
- INV-1: "frozen dataclass"
- INV-6: "rrf_merge scores decrease monotonically"
- INV-8: "fcntl.flock() kernel releases"

**Auth (brief invariants, less distinctive):**
- INV-7: "hmac.compare_digest timing safety"
- INV-12: "exponential backoff capped at 300 seconds"

**Search (brief, structural):**
- INV-6: "rrf_merge() monotonic output"

**Watchers (action-focused):**
- INV-10: "filters by extension, skips hidden dirs"
- INV-11: "deduplicates paths"

**Result:** Commits with general refactoring language ("module", "organize", "structure") do not semantically align with specific invariant language ("frozen dataclass", "fcntl.flock", "backoff"). Chunking granularity cannot fix this mismatch.
