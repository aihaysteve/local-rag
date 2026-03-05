# H3 Pilot: RAG-Injected Context vs Full SPEC.md Dumps

**Issue:** #45
**Branch:** `experiment/h3-pilot-45`
**Prerequisite:** H1 (query reformulation) and H2 (subsystem filtering) validated

## Hypothesis

Implementer subagents given RAG-selected spec sections produce fewer invariant
violations than those given full SPEC.md dumps.

## Pilot 1: `rag_stats` Tool (Read-Only Task)

### Task

**"Add a `rag_stats` MCP tool that returns per-collection indexing statistics."**

Why this task:
- Crosses 3+ subsystems: Core (config, DB), Search (query counts), Indexers (source counts), MCP server (tool registration)
- Has clear invariants to violate (INV-3 WAL mode, INV-4 single-writer, INV-5 DocStore keying, INV-6 RRF monotonicity)
- Small enough to complete in one subagent turn
- Complex enough that context quality matters (not a trivial one-liner)

### Conditions

| Condition | Context Injection | Measured Size |
|---|---|---|
| **A: Full dump** | Concatenate all 7 SPEC.md files verbatim | 34,350 chars (~8,600 tokens) |
| **B: RAG-selected** | `rag_search_task(query, task_type="implementation", task_context={"subsystems": ["Core", "Search", "Indexers"]})` | 4,268 chars (~1,070 tokens) |

Both conditions received identical:
- Task description (same prompt)
- Full codebase read access (worktree isolation)
- Instructions to write output to `/tmp/h3_pilot/{condition}_{run}/implementation.py`

**Note on SPEC.md access:** The initial runs did not explicitly prohibit
Condition B agents from reading SPEC.md files. A confirmation run (B-Run4) with
an explicit "do NOT read any SPEC.md files" instruction produced structurally
identical output, confirming the original runs were not contaminated.

### RAG Retrieval Results

`rag_search_task()` returned 16 chunks across all 7 subsystems:
- **Requested:** Core, Search, Indexers (3 subsystems)
- **Expanded via dependencies:** Watchers, Parsers, Document, Auth (4 subsystems)
- **Content:** Primarily invariant statements (INV-N) and purpose sections
- **Coverage:** 7/7 subsystems found

### Scoring Rubric

A reviewer agent checked each implementation against this checklist.
Each item scored PASS / FAIL / N/A:

| ID | Invariant | How to check |
|---|---|---|
| Core-INV-3 | SQLite DBs use WAL mode | Does the code open raw `sqlite3.connect()`? Using `get_connection` + `init_db` is PASS. |
| Core-INV-4 | Only IndexingQueue worker writes to index DB | Any INSERT/UPDATE/DELETE is FAIL. Read-only queries are PASS. |
| Indexers-INV-9 | Per-item errors don't cascade | Single collection failure aborts everything = soft FAIL. |
| Parsers-INV-5 | Parsers never raise exceptions | N/A if no parsing. |
| Search-INV-6 | RRF scores monotonically decreasing | N/A if no search. |
| MCP-pattern | Tools follow existing registration pattern | `@mcp.tool()` decorator, closure helpers, matching signatures. |
| Error-handling | Graceful error handling | Catches exceptions, returns `{"error": ...}`. |
| Conn-lifecycle | Connection closed in finally | `conn.close()` in `finally` block. |

### Results

| Run | Condition | Core-INV-3 | Core-INV-4 | Idx-INV-9 | Par-INV-5 | Srch-INV-6 | MCP-pattern | Error-handling | Conn-lifecycle | Violations |
|---|---|---|---|---|---|---|---|---|---|---|
| A-Run1 | Full SPEC | PASS | PASS | N/A | N/A | N/A | PASS | PASS | PASS | **0** |
| A-Run2 | Full SPEC | PASS | PASS | N/A | N/A | N/A | FAIL | PASS | PASS | **1** |
| A-Run3 | Full SPEC | PASS | PASS | N/A | N/A | N/A | PASS | PASS | PASS | **0** |
| B-Run1 | RAG only | PASS | PASS | N/A | N/A | N/A | PASS | PASS | PASS | **0** |
| B-Run2 | RAG only | PASS | PASS | N/A | N/A | N/A | FAIL | FAIL | PASS | **2** |
| B-Run3 | RAG only | PASS | PASS | N/A | N/A | N/A | FAIL | PASS | PASS | **1** |

### Summary

| Metric | Condition A (full) | Condition B (RAG) |
|---|---|---|
| Total violations | 1 | 3 |
| Mean violations | 0.33 | 1.00 |
| Context tokens | ~8,600 | ~1,070 |
| Token reduction | — | **88%** |

### Analysis

**Invariant violations: none in either condition.** All six implementations
correctly used `get_connection()` + `init_db()` (Core-INV-3), performed only
read-only queries (Core-INV-4), and closed connections in `finally` blocks.
The SPEC.md invariants were not violated by any run.

**Pattern violations concentrated in Condition B.** Two of three B runs had
`@mcp.tool()` decorator issues (one commented out, one missing entirely).
These are task-instruction failures — the agents wrote standalone files
rather than closure-ready snippets — not spec-awareness failures. A-Run2
had a related issue (non-standard wrapper function).

**Token savings: strong signal.** 88% context reduction with no invariant-
level quality loss.

**Task was too easy.** The `rag_stats` tool is inherently read-only, so
Core-INV-4 (single-writer) could not be violated. Most invariants scored
N/A because the task doesn't involve parsing, searching, or writing.
A harder task is needed to differentiate the conditions.

### Conclusion

**Weak anti-signal on violations** (B slightly worse, but violations are
pattern-related, not invariant-related). **Strong signal on token savings.**
The task ceiling was too low to test the hypothesis — both conditions had
ample information to avoid invariant violations on a read-only tool.

**Next step:** Repeat with a harder task that requires writes, crosses
subsystem boundaries in non-obvious ways, or has invariants that are easy
to violate without explicit awareness.

## Pilot 2: `rag_delete_source` Tool (Write Task, Haiku Model)

### Design Changes from Pilot 1

Two variables changed to increase discriminating power:

1. **Harder task** — deletion requires database writes, creating the INV-4
   trap: the naive implementation calls `delete_source()` directly, but the
   correct approach submits a PRUNE job to the IndexingQueue.
2. **Less capable model** — Haiku instead of Sonnet, lowering the baseline
   so context quality matters more.

### Task

**"Add a `rag_delete_source` MCP tool that removes a source and its
documents/embeddings from a collection."**

Why this is harder than Pilot 1:
- **INV-4 trap:** Direct `DELETE` from MCP handler violates single-writer.
  Correct: submit `IndexJob` with `IndexerType.PRUNE` to the queue.
- **Follower mode:** Must check `_get_queue()` and return error if None
  (read-only follower), matching the `rag_index` pattern.
- **Indexers-INV-1:** Deletion must be atomic (existing `delete_source()`
  handles this, but hand-rolled DELETE statements would not).

### Conditions

| Condition | Context Injection | Measured Size |
|---|---|---|
| **A: Full dump** | All 7 SPEC.md files verbatim | 34,350 chars (~8,600 tokens) |
| **B: RAG-selected** | `rag_search_task(query, task_type="implementation", task_context={"subsystems": ["Core", "Indexers"]})` | 5,353 chars (~1,340 tokens) |

Both conditions received:
- Same task description
- Full codebase read access (worktree isolation)
- Explicit instruction: "Do NOT read any SPEC.md files"
- Instructions to read `rag_index` and `indexing_queue.py` for patterns
- Model: Haiku

### RAG Retrieval Results (Condition B)

`rag_search_task()` returned 18 chunks across all 7 subsystems:
- **Core:** INV-4 (single-writer), Purpose (single-writer architecture),
  Public Interface (IndexingQueue, IndexJob, IndexerType including PRUNE)
- **Indexers:** Public Interface (delete_source, prune_stale_sources),
  Core Mechanism, INV-5 (prune skips virtual URIs)
- **Dependency expansion:** Watchers, Parsers, Document, Search, Auth

Critically, the RAG context included both the invariant (INV-4) and the
public interface listing `IndexerType.PRUNE` as the correct mechanism.

### Scoring Rubric

| ID | Invariant | How to check |
|---|---|---|
| Core-INV-4 | Only IndexingQueue worker writes to DB | Submits job to queue = PASS. Direct delete_source() call = FAIL. Queue with fallback to direct = PARTIAL. |
| Core-INV-3 | SQLite DBs use WAL mode | Uses get_connection+init_db = PASS. |
| Indexers-INV-1 | Atomic delete | Uses existing delete_source() = PASS. Hand-rolled DELETEs = FAIL. |
| MCP-pattern | Follows existing tool patterns | @mcp.tool(), closure helpers, matches rag_index for writes. |
| Error-handling | Graceful error handling | Returns {"error": ...} on failure. |
| Conn-lifecycle | Connection closed in finally | conn.close() in finally block. |
| Follower-mode | Handles read-only follower | Checks _get_queue(), errors if None. |

### Results

| Run | Condition | INV-4 | INV-3 | Idx-INV-1 | MCP-pattern | Error | Conn | Follower | Violations |
|---|---|---|---|---|---|---|---|---|---|
| A-Run1 | Full SPEC | FAIL | PASS | PASS | FAIL | PASS | PASS | FAIL | **3** |
| A-Run2 | Full SPEC | FAIL | PASS | PASS | PARTIAL | PASS | PASS | FAIL | **2+1P** |
| A-Run3 | Full SPEC | FAIL | PASS | PASS | FAIL | PASS | PASS | FAIL | **3** |
| B-Run1 | RAG only | FAIL | PASS | PASS | FAIL | PASS | PASS | FAIL | **3** |
| B-Run2 | RAG only | PARTIAL | PASS | PASS | FAIL | PASS | PASS | FAIL | **2+1P** |
| B-Run3 | RAG only | FAIL | PASS | PASS | FAIL | PASS | PASS | FAIL | **3** |

### Summary

| Metric | Condition A (full) | Condition B (RAG) |
|---|---|---|
| Total hard fails | 8 | 8 |
| Core-INV-4 violations | 3/3 FAIL | 2/3 FAIL + 1/3 PARTIAL |
| Follower-mode violations | 3/3 FAIL | 3/3 FAIL |
| Context tokens | ~8,600 | ~1,340 |
| Token reduction | — | **84%** |

### Analysis

**Core-INV-4 universally violated.** All six implementations perform direct
database writes from the MCP handler. No implementation correctly submits a
PRUNE job to the IndexingQueue and returns immediately — the pattern used
by `rag_index`. This is the single most important architectural invariant
and neither condition prevented the violation.

**B-Run2 showed the most architectural awareness.** It was the only
implementation that imported `IndexJob`, attempted queue submission, and
explicitly cited INV-4 in its docstring. However, it negated this by
falling back to direct writes when the queue is absent — exactly the wrong
behavior for follower mode. This represents a PARTIAL on INV-4: the model
understood the constraint but could not implement it correctly.

**Surface-level invariants universally respected.** All six correctly used
`get_connection()` + `init_db()` (INV-3), delegated to the existing
`delete_source()` function (INV-1), handled exceptions gracefully, and
closed connections in `finally` blocks. These are pattern-matchable from
reading `mcp_server.py`.

**Follower mode universally missed.** No implementation checks `_get_queue()`
or returns an error when the queue is absent. This is tightly coupled to
the INV-4 failure: a model that doesn't route through the queue also
doesn't know to fail-safe when the queue is unavailable.

**No meaningful difference between conditions.** Both produced the same
failure profile. The full SPEC.md dump (8,600 tokens) provided no
advantage over RAG-selected context (1,340 tokens) for preventing the
critical INV-4 violation.

### Key Finding

The experiment revealed a **model capability floor**, not a context quality
difference. Haiku cannot correctly implement the single-writer queue
pattern regardless of how much spec context it receives. The constraint
requires understanding a cross-cutting architectural invariant (thread
ownership of writes) that goes beyond pattern-matching from existing code.

Both conditions had the information needed:
- **Condition A** had the full Core SPEC.md explaining single-writer
  architecture, IndexingQueue, and INV-4 in detail.
- **Condition B** had INV-4 explicitly, plus the Public Interface table
  listing `IndexingQueue`, `IndexJob`, and `IndexerType.PRUNE`.
- **Both** were told to read `rag_index` and `indexing_queue.py` for
  patterns.

Despite this, the model consistently chose the naive direct-write approach.
This suggests the bottleneck is **model reasoning about architectural
constraints**, not context availability.

### Conclusion

**No signal for H3.** Neither condition differentiated on the critical
invariant. The task successfully exposed real invariant violations (unlike
Pilot 1's read-only ceiling), but the model capability floor prevented
either condition from succeeding.

**Strong signal for token savings.** 84% context reduction with identical
quality outcomes.

**Implications:**
- H3 hypothesis (RAG context reduces violations vs full dumps) is **not
  supported** at the Haiku capability level — violations are model-limited,
  not context-limited.
- A follow-up with Sonnet on this same task would test whether a more
  capable model can leverage the spec context to avoid INV-4 violations,
  and whether the conditions then differentiate.
- The B-Run2 partial success (queue attempt) suggests that with slightly
  more capability, RAG-selected context containing explicit invariant
  statements plus public interface tables might be sufficient to guide
  correct implementation.

## Pilot 2b: `rag_delete_source` Tool (Write Task, Sonnet Model)

### Design

Same task and conditions as Pilot 2 (Haiku), re-run with Sonnet to test
whether a more capable model can leverage spec context to avoid INV-4
violations that Haiku universally failed on.

### Results

| Run | Condition | INV-4 | INV-3 | Idx-INV-1 | MCP-pattern | Error | Conn | Follower | Violations |
|---|---|---|---|---|---|---|---|---|---|
| A-S-Run1 | Full SPEC | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| A-S-Run2 | Full SPEC | PASS | PASS | PASS | PARTIAL | PASS | PASS | PASS | **0+1P** |
| A-S-Run3 | Full SPEC | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| B-S-Run1 | RAG only | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| B-S-Run2 | RAG only | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| B-S-Run3 | RAG only | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |

### Summary

| Metric | Condition A (full) | Condition B (RAG) |
|---|---|---|
| INV-4 violations | 0/3 | 0/3 |
| Follower-mode violations | 0/3 | 0/3 |
| Total hard fails | 0 | 0 |
| MCP-pattern issues | 1 PARTIAL (decorator) | 0 |
| Context tokens | ~8,600 | ~1,340 |
| Token reduction (context only) | — | **84%** |

### Total Agent Token Usage

The spec context is only a fraction of total session cost. Measured total
tokens per agent session (all API round-trips including system prompt,
file reads, reasoning, and output):

| Run | Condition | Total Tokens | Tool Uses |
|---|---|---|---|
| A-S-Run1 | Full SPEC | 56.2k | 10 |
| A-S-Run2 | Full SPEC | 60.8k | 14 |
| A-S-Run3 | Full SPEC | 62.3k | 12 |
| B-S-Run1 | RAG only | 51.3k | 8 |
| B-S-Run2 | RAG only | 45.8k | 9 |
| B-S-Run3 | RAG only | 45.8k | 8 |

| Metric | Condition A | Condition B | Delta |
|---|---|---|---|
| Mean total tokens | 59,767 | 47,633 | **-20%** |
| Mean tool uses | 12.0 | 8.3 | -31% |

The **actual total session savings are ~20%**, not 84%. The 84% applies
only to the injected spec context portion. The remainder of the token
budget — system prompt, task instructions, reading `mcp_server.py` and
`indexing_queue.py`, writing output, and model reasoning — is roughly
the same for both conditions.

The B agents also used ~31% fewer tool calls, suggesting the smaller
context led to faster decision-making with fewer exploratory reads.

### Analysis

**Sonnet universally passes INV-4.** All six implementations correctly:
1. Submit `IndexJob` with `IndexerType.PRUNE` to the IndexingQueue
2. Check `_get_queue()` and handle follower mode with descriptive errors
3. Perform read-only pre-flight checks on separate WAL connections
4. Close connections in `finally` blocks
5. Never call `delete_source()` directly from the MCP handler

This is a complete inversion from Haiku (0/6 PASS → 6/6 PASS).

**No difference between conditions.** Both A and B produced zero INV-4
violations. The RAG-selected context (1,340 tokens) was equally effective
as the full SPEC.md dump (8,600 tokens) at guiding Sonnet to the correct
queue-based architecture.

**Implementation quality is high and consistent.** All six runs:
- Used `job_type="file_deleted"` + `IndexerType.PRUNE` (correct)
- Called `_get_queue()` with follower-mode error handling (correct)
- Did read-only existence checks before queueing (good practice)
- Referenced INV-4 explicitly in docstrings or comments

The only blemish: A-S-Run2 had `@mcp.tool()` commented out (same
decorator-in-standalone-file issue seen across all pilots).

### Key Finding: Model Capability Is the Dominant Variable

| Model | INV-4 Pass Rate | Context Condition |
|---|---|---|
| Haiku + Full SPEC | 0/3 (0%) | 8,600 tokens |
| Haiku + RAG | 0/3 (0%) + 1 PARTIAL | 1,340 tokens |
| Sonnet + Full SPEC | 3/3 (100%) | 8,600 tokens |
| Sonnet + RAG | 3/3 (100%) | 1,340 tokens |

The results show a clean **model-capability threshold effect**:
- Below the threshold (Haiku): fails regardless of context volume
- Above the threshold (Sonnet): succeeds regardless of context volume

Context condition (A vs B) had **no measurable effect** at either
capability level. The 84% token reduction from RAG produces identical
quality outcomes.

## Pilot 2c: `rag_delete_source` Tool (Write Task, Opus Model)

### Design

Same task and conditions as Pilots 2/2b, run with Opus to test whether
the highest-capability model shows any differentiation between conditions
that Sonnet did not.

### Results

| Run | Condition | INV-4 | INV-3 | Idx-INV-1 | MCP-pattern | Error | Conn | Follower | Violations |
|---|---|---|---|---|---|---|---|---|---|
| A-O-Run1 | Full SPEC | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| A-O-Run2 | Full SPEC | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| A-O-Run3 | Full SPEC | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| B-O-Run1 | RAG only | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| B-O-Run2 | RAG only | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |
| B-O-Run3 | RAG only | PASS | PASS | PASS | PASS | PASS | PASS | PASS | **0** |

### Total Agent Token Usage

| Run | Condition | Total Tokens | Tool Uses |
|---|---|---|---|
| A-O-Run1 | Full SPEC | 57.4k | 11 |
| A-O-Run2 | Full SPEC | 60.4k | 7 |
| A-O-Run3 | Full SPEC | 60.9k | 9 |
| B-O-Run1 | RAG only | 47.2k | 7 |
| B-O-Run2 | RAG only | 45.0k | 7 |
| B-O-Run3 | RAG only | 47.7k | 11 |

| Metric | Condition A | Condition B | Delta |
|---|---|---|---|
| Mean total tokens | 59,567 | 46,633 | **-22%** |
| Mean tool uses | 9.0 | 8.3 | -8% |

### Analysis

**Opus confirms the Sonnet ceiling.** All six runs pass every invariant
with zero violations. No differentiation between conditions.

**Qualitative improvements over Sonnet:**
- All 6 runs have `@mcp.tool()` decorator present (Sonnet A-Run2 had it
  commented out)
- Two runs (B-O-Run1, B-O-Run3) used `submit_and_wait()` instead of
  `submit()` for synchronous confirmation — a more robust UX choice
- A-O-Run1 and A-O-Run2 included SSE path mapping via `apply_reverse()`
  — a detail neither Haiku nor Sonnet B runs picked up

**Token savings consistent with Sonnet:** ~22% total session reduction for
Condition B, closely matching Sonnet's ~20%. The savings are driven by
the smaller context file, not by behavioral differences.

## Overall H3 Conclusions

### Hypothesis Status: Not Supported (But Informative)

H3 predicted that RAG-selected spec sections would produce *fewer*
invariant violations than full SPEC.md dumps. Across all four pilots
(24 total runs), **context condition never differentiated**:

| Pilot | Task | Model | A violations | B violations |
|---|---|---|---|---|
| 1 | rag_stats (read) | Sonnet | 0.33 mean | 1.00 mean* |
| 2 | rag_delete_source (write) | Haiku | 2.67 mean | 2.67 mean |
| 2b | rag_delete_source (write) | Sonnet | 0+1P | 0 |
| 2c | rag_delete_source (write) | Opus | 0 | 0 |

*Pilot 1 violations were MCP-pattern issues, not invariant violations.

### What We Learned Instead

1. **Model capability dominates context format.** The Haiku→Sonnet jump
   produced a 0%→100% pass rate on the critical invariant. Sonnet→Opus
   showed no further improvement (already at ceiling). Context format
   (full vs RAG) produced 0% variation at all three capability levels.

2. **RAG reduces total agent session cost by ~20%.** Measured across both
   Sonnet (20%) and Opus (22%) runs. The spec context itself is 84%
   smaller, but total session cost is dominated by system prompt, file
   reads, and reasoning. Condition B agents also used fewer tool calls,
   suggesting smaller context enables faster decision-making.

3. **Architectural invariants require model reasoning, not just context.**
   Haiku had INV-4 explicitly in both conditions and was told to read
   `rag_index` for the queue pattern, yet consistently chose direct
   writes. The bottleneck was reasoning about thread ownership, not
   information availability.

4. **Surface-level patterns are universally learned.** WAL mode, connection
   lifecycle, error handling, and use of existing helper functions were
   correct across all 24 runs regardless of model or context. These are
   locally pattern-matchable from code examples.

5. **The capability threshold is between Haiku and Sonnet.** Haiku (0%
   INV-4 pass rate) cannot reason about cross-cutting architectural
   constraints. Sonnet (100%) and Opus (100%) can. There is no further
   gradient above Sonnet for this task.

### Practical Implications

- **Use RAG context for subagent injection.** ~20% total session savings
  with equivalent quality. Savings scale with the ratio of spec context
  to total session cost — larger for quick tasks, smaller for
  exploration-heavy ones.
- **Model selection matters more than context engineering** for complex
  architectural constraints. Use Sonnet or above for implementation tasks
  that touch cross-cutting invariants. Haiku is insufficient regardless
  of context quality.
- **The three-tier context architecture works.** RAG (cold tier) surfaces
  the right invariants at ~20% lower total cost. The warm tier
  (filesystem walk to nearest SPEC.md) can be reserved for cases where
  full spec context is actually needed.
- **Opus is not necessary for this class of task.** Sonnet produces
  identical invariant compliance at lower cost. Opus adds minor polish
  (SSE path mapping, synchronous wait) but no safety improvements.
