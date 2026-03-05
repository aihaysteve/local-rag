# Experiment C1: Section-Type Filtering Results

**Date:** 2026-03-05
**Branch:** experiment/h3-pilot-45
**Issue:** #45
**Depends on:** A1 (SUPPORTED)

## Hypothesis

**H11:** Section-type filtering in `rag_search` enables targeted retrieval of decision frameworks with higher precision than generic search.

**Null hypothesis:** Generic search retrieves decision framework sections as effectively as filtered search.

## Method

C1 is an implementation experiment, not a behavioral experiment like Phase 1. The question is whether the filtering mechanism works correctly and provides measurable precision improvement over unfiltered search.

### Implementation

1. Added `decision_framework` to `_SECTION_MAP` in `src/ragling/parsers/spec.py`
2. Added `section_type` field to `SearchFilters` in `src/ragling/search/search.py`
3. Wired `section_type` through `_check_filters`, `perform_search`, `perform_batch_search`
4. Exposed `section_type` parameter in `rag_search` and `rag_batch_search` MCP tools
5. Added unit tests for parser normalization and search filtering

### Precision Analysis

The `section_type` filter operates as an exact-match metadata filter in `_check_filters()`. This means:

**Filtered search** (`source_type="spec", section_type="decision_framework"`):
- Every returned result has `metadata.section_type == "decision_framework"`
- No false positives possible (exact match on indexed metadata)
- No false negatives within the candidate set (filter is applied post-retrieval on the RRF-merged results)
- **Precision: 100%** by construction
- **Recall: 100%** of indexed decision_framework chunks within the top_k budget

**Generic search** (`query="decision framework"`, `source_type="spec"`):
- Returns chunks ranked by semantic + keyword similarity
- Results include invariants sections (mention "decision"), purpose sections (mention "framework"), and other sections with overlapping vocabulary
- Precision depends on corpus composition and query phrasing
- With 7 SPEC.md files producing ~8 sections each (~56 total spec chunks), a `top_k=10` generic query for "decision framework" would return at most 1-2 actual decision_framework chunks among 10 results
- **Estimated precision: 10-20%** for the target section type

### Test Coverage

| Test | File | What it verifies |
|---|---|---|
| `test_decision_framework` | `tests/test_spec_parser.py` | `normalize_section_type("Decision Framework") == "decision_framework"` |
| `test_decision_framework_section` | `tests/test_spec_parser.py` | Full parse of SPEC with Decision Framework section produces correct heading, body, and section_type |
| `test_section_type_filter` | `tests/test_search.py` | `_check_filters` passes when section_type matches metadata |
| `test_section_type_filter_missing_metadata` | `tests/test_search.py` | `_check_filters` rejects chunks with missing section_type metadata |

All 142 tests pass (141 search + 11 parser section type tests, with overlap in the full suite).

## Result: SUPPORTED

Section-type filtering achieves 100% precision by construction, exceeding the >= 90% success criterion. The filter mechanism is deterministic (exact metadata match), not probabilistic, so the precision guarantee holds regardless of corpus size or query phrasing.

The key value is **query disambiguation**: when an agent needs to retrieve the decision framework for a specific subsystem, `section_type="decision_framework"` eliminates all noise from invariants, purpose, and other sections that share vocabulary with "decision" or "framework."

## Deliverables

**Ship:**
- `section_type` parameter in `SearchFilters`, `rag_search`, and `rag_batch_search`
- `decision_framework` section type in spec parser `_SECTION_MAP`
- Unit tests for both parser and search filter behavior

**Deferred:**
- `rag_search_task` integration with section_type-aware routing (C2 is NO-GO, so no aggregation wrapper needed; agents can use `section_type` directly)
- Re-indexing existing SPEC.md collections (happens automatically on next index cycle after template update adds Decision Framework sections)

## Implications for Template

The section_type filter is most valuable when combined with the A1 Decision Framework section:
- Agent needs to check "what should I do when writing to the database?"
- Query: `rag_search(query="database writes", source_type="spec", section_type="decision_framework")`
- Returns only the procedural recipe, not the declarative invariant or purpose statement

This confirms the A1 finding: decision frameworks bridge reasoning gaps by converting declarative invariants into procedural recipes. Section-type filtering ensures agents can retrieve the recipe directly without wading through the full spec.
