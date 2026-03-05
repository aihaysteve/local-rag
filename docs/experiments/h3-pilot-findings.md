# H3 Pilot Findings: Production Recommendation

**Issue:** #45
**Branch:** `experiment/h3-pilot-45`

## What We Tested

RAG-selected spec context vs full SPEC.md dumps for implementer subagents, across
3 models (Haiku, Sonnet, Opus), 2 task types (read-only, write), 24 total runs.

## Key Findings

### 1. Context format doesn't affect correctness

All models that can follow invariants (Sonnet, Opus) scored 6/6 regardless of
whether they received full SPEC dumps or RAG-selected sections. Model capability
is binary — Haiku can't, Sonnet/Opus can.

### 2. RAG saves ~20% total session tokens

Despite 84% reduction in spec context, total session savings are only 20-22%.

**Why:** Spec context is only ~14% of a session's token budget.

| Component | ~Tokens | % of Session |
|---|---|---|
| Model output + reasoning | ~35,500 | 59% |
| Code file reads | ~12,400 | 21% |
| Spec context | 8,600 | 14% |
| System prompt (Claude Code) | ~3,250 | 5% |
| Task instructions | ~300 | <1% |

### 3. Indirect savings from fewer tool calls

RAG condition averaged 8.3 tool calls vs 12.0 for full dump (Sonnet). Focused
context helps agents make faster decisions, saving ~5k tokens beyond the raw
context reduction.

### 4. VSA is the bigger lever for code reads

Code file reads (21% of budget) are the next optimization target. The agent reads
1200-line `mcp_server.py` when it needs ~50 lines of pattern. Smaller, focused
files eliminate waste without any retrieval overhead.

| Approach | Code read tokens | Savings |
|---|---|---|
| Current (monolithic files) | ~12,400 | baseline |
| VSA (focused files) | ~2,000-3,000 | 75-85% |

## Production Recommendation

### What to ship: RAG-as-tool (pull model)

Replace static SPEC.md dumps in agent prompts with a single instruction:

> "Before implementing, call `rag_search_task` with the task description."

**Changes required:**
- Add one line to agent system prompts
- Remove SPEC.md concatenation from prompt templates

**Complexity delta: negative.** Prompt gets shorter, agent uses a tool it already
knows how to call. Zero new concepts.

### What to pursue next: VSA refactoring

Smaller files make every `Read` inherently high-signal. No retrieval system needed —
the file *is* the chunk. Combined with RAG spec savings, could bring 60k sessions
down to ~35-40k.

**Changes to agent instructions: none.** Agents automatically benefit from smaller
files.

### Combined potential

| Optimization | Slice targeted | Savings on slice | Total session savings |
|---|---|---|---|
| RAG specs (ship now) | 14% (spec context) | 84% | ~20% |
| VSA refactoring (next) | 21% (code reads) | 75-85% | ~15-18% |
| Both | 35% combined | — | ~33-35% |

## Open Questions for Brainstorming

1. **RAG integration point:** Should `rag_search_task` be called by the orchestrator
   before spawning the subagent, or by the subagent itself as its first action?
   Trade-off: orchestrator call is more reliable but less adaptive; subagent call
   lets it refine queries based on what it discovers.

2. **VSA scope:** Which files are highest-value to decompose first? `mcp_server.py`
   (1200 lines, read in every implementation task) is the obvious candidate. What's
   the right granularity — one file per MCP tool handler?

3. **Fallback behavior:** If RAG returns nothing relevant (new subsystem, empty
   index), should the agent fall back to reading SPEC.md files directly? Or is
   that an indexing problem to fix upstream?

4. **Measurement:** How do we track session cost in production to confirm the
   savings materialize outside controlled experiments?
