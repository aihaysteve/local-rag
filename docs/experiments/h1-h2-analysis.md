# H1/H2 Analysis and Phase 3 Decision

**Date:** 2026-03-04
**Issue:** #45
**Branch:** experiment/rag-spec-retrieval-45

## H1: Token Precision

RAG achieves strong token reduction across the sample: the mean reduction ratio is **0.41** (59% average token reduction), and **8/10 commits** fall below the 0.70 threshold. These numbers suggest that commit-message-driven RAG retrieval does successfully narrow the SPEC context when the right chunks are returned.

Coverage, however, tells a more complicated story. **6/10 commits** have full coverage, but 4 of those 6 are vacuously full — the commits contained no INV-N identifiers in their diffs (pure refactors: type annotation fixes, NamedTuple introductions, factory method splits). Vacuous coverage does not validate the hypothesis; it simply reflects that those commits had no invariant exposure to begin with.

The 4 partial-coverage misses — `decd7f5` (INV-4), `91e8c52` (INV-3, INV-5), `69f4b2d` (INV-3, INV-4 Indexers), `3588421` (INV-5) — share a structural pattern. In every case the implicated invariants live in the SPEC `invariants` section, which contains short declarative property statements: "Only the IndexingQueue worker thread writes…", "DocStore uses SHA-256 content-addressed cache…". Commit messages and manual task descriptions use procedural language — dispatch logic, context managers, git helpers. The semantic distance between these two registers is large enough that the search consistently returns `core_mechanism` or `public_interface` prose chunks instead of the `invariants` section, even when the invariant is the primary contract at risk.

One additional failure mode: `69f4b2d` (an Indexers commit about extracting `git_commands.py`) returned Core `invariants` chunks because the string "git" in the query matched Core's invariants section, which references git-related indexing behavior. This is wrong-subsystem retrieval driven by incidental lexical overlap rather than semantic relevance.

Only **5/10 commits** meet both the ratio < 0.70 and full-coverage criteria simultaneously. The success threshold was 8/10.

**Verdict:** Not supported

---

## H2: Cross-Cutting Discovery

RAG discovered zero relevant specs beyond the warm tier across all four cross-cutting commits. The discovery rate is **0/4**; the success threshold was 3/4.

The commit-by-commit picture is instructive:

- **0cdc98a** and **6f3c56b**: RAG returned exactly the warm-tier set. No discovery, no false positives. These are clean null results — RAG neither helped nor hurt.
- **bca25f7** (near-miss): RAG returned Core and Indexers beyond the warm-tier Parsers spec. Indexers SPEC.md contains INV-9 — "per-file processing continues after each file (error isolation)" — which is the consumer-side guarantee that explains *why* Parsers INV-5 matters. The dependency chain was surfaced, but the discovered specs were not directly constraining the diff and cannot be counted as relevant discoveries under the experiment criteria.
- **cbd2ac3** (catastrophic miss): This 7-subsystem structural refactor returned only Core and Indexers — 2 of 7 warm-tier specs. Auth, Document, Parsers, Search, and Watchers were missed entirely. This is the inverse of H2's prediction: instead of RAG finding cross-cutting constraints that warm-tier path matching missed, RAG failed to retrieve a majority of the specs that warm-tier matching would have surfaced automatically.

The root cause of the pattern is visible in the aggregate: Core (1658 tokens) and Indexers (2396 tokens) dominate the SPEC corpus and are referenced extensively across the codebase's documentation language. Auth (516 tokens), Search (591 tokens), and Watchers (613 tokens) are small and use sparse, distinctive vocabulary. Retrieval is driven by this size-and-cross-reference asymmetry, not by the semantic content of what each subsystem's invariants constrain.

**Note on control (b8665d3):** The single false positive — Indexers SPEC returned for a pure CLI/Core `ServerOrchestrator` refactor — is a mild concern but not disqualifying on its own. The mechanism is clear: "orchestration" in the query co-occurs with "IndexingQueue" in Core's SPEC description, which in turn is proximate to Indexers content in the vector space. This indicates that the embedding model conflates infrastructure-level coordination concepts across subsystems. For a production system, one false positive per control would add noise to agent context but might be tolerable; the larger concern is that the false positive rate may worsen as the number of subsystems grows, since each new SPEC adds vocabulary overlap opportunities.

**Verdict:** Not supported

---

## Interaction between H1 and H2

H1 and H2 are not independent null results. Both failures trace back to a single root cause: **semantic mismatch between the language used to query the index (procedural, structural, task-oriented) and the language of SPEC content that captures hard constraints (declarative, property-asserting, invariant-focused).**

In H1, commit messages describe operations — "extract git commands", "refactor dispatch to use lookup dict", "fix resource leak" — while the invariant statements that matter for correctness describe properties — "Only the IndexingQueue worker thread writes", "SHA-256 content-addressed cache prevents redundant Docling conversion". A retrieval system that matches on semantic similarity to the query will find procedural SPEC sections (`core_mechanism`, `public_interface`) and miss the declarative `invariants` section, because the two sections speak different registers of language about the same system.

In H2, the same mismatch explains the size-bias finding. The large specs (Core, Indexers) are large precisely because they contain extensive procedural descriptions of how the system works. Small specs (Auth, Search, Watchers) contain mostly invariants and interface contracts with minimal procedural narrative. When a commit message or structural description is used as a query, retrieval selects for the procedural richness of large specs rather than the conceptual relevance of small ones.

The coherent failure mode is: **RAG retrieval optimized for semantic proximity to task language systematically underweights declarative constraint language, regardless of whether the failure manifests as missing an invariant within the correct spec (H1) or missing an entire spec whose invariants are implicated (H2).**

This has a further implication: the failure is not an artifact of this codebase's size or the current SPEC coverage. It is a structural property of how embedding models represent the difference between "what the code does" and "what the code must never do." Those two things are semantically related but not semantically close in the way that nearest-neighbor retrieval requires.

---

## What Would Need to Change

Four changes would address the identified failure modes:

**Query construction.** Commit messages and task descriptions should not be used as raw queries for invariant retrieval. An intermediate step that reformulates queries in the declarative register — e.g., "what invariants could this change violate?" — would close the semantic gap. Even appending "invariant" or "must never" to the existing query string would likely shift retrieval toward the `invariants` section in H1 experiments.

**Chunking strategy.** The current section-level chunking treats the entire `invariants` section as one chunk alongside `purpose`, `public_interface`, `core_mechanism`, and `failure_modes`. Splitting at the individual invariant level (one chunk per INV-N statement, each with its identifier, description, and rationale) would make invariant retrieval more precise and remove the coarse-grained competition between section types.

**Retrieval depth.** The H2 experiments used top_k=3 to 5. For cross-cutting commits touching 7 subsystems, a top_k of at least 14 (2 chunks per subsystem) would be needed to have any chance of surfacing all relevant specs. Higher top_k introduces noise, but the current setting structurally prevents H2 from succeeding on the largest commits regardless of semantic quality.

**Embedding model fit.** The current model (likely a general-purpose text embedding model) encodes semantic proximity in a space calibrated on broad natural language. A model fine-tuned or adapted on software specification language — or a two-stage pipeline that first classifies query type and then selects retrieval strategy — would better separate the "what changed" register from the "what must hold" register. This is the highest-effort change and should be preceded by cheaper experiments with query reformulation and chunking.

---

## Phase 3 Decision

**No-Go**

**Rationale:** Both H1 and H2 failed to meet their success criteria (5/10 for H1, 0/4 for H2), and the failures share a root cause that is structural rather than incidental. Running a live A/B experiment with subagents would expose agents to a retrieval system that reliably misses invariant constraints on the commits where those constraints matter most. The current configuration does not produce the retrieval quality necessary for Phase 3 to be a meaningful test: any outcome would be confounded by the known failure modes identified here. Phase 3 would only be warranted if invariant-targeted query construction and invariant-level chunking have first been validated in an offline re-run of H1 and H2 with the new configuration.

**Conclusion:** Recommend closing issue #45 as "hypotheses not supported at current scale/configuration." Before revisiting, two preparatory steps are worth doing: (1) re-run the H1 measurement with queries that append "invariant" or include explicit INV-N framing to test whether query reformulation alone closes the coverage gap; (2) re-run H2 with invariant-level chunking and top_k=10 to test whether the size-bias against small specs is a chunking artifact or a deeper embedding-space issue. If both re-runs show measurable improvement (H1: 8/10 coverage, H2: 3/4 discovery), the experiment would be in a position to proceed to Phase 3.
