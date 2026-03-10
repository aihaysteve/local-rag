# <Subsystem Name>

## Purpose

What this subsystem does and why it exists. Lead with the core responsibility,
then state the key design decision that shapes the implementation.

Two paragraphs max.

## Core Mechanism

Two to three sentences on the key design decisions — focus on *why*, not *what*.
The Purpose section covers what the subsystem does; this section explains the
architectural choices that aren't obvious from reading the code.

Use a **Key files:** list to enumerate the important source files.

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| `function_or_class` | Consuming module or subsystem | What callers can rely on |

Only list exports consumed outside this subsystem's directory. Internal helpers
are implementation details.

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | Statement that must always be true | Consequence of violation |

Number sequentially. Each invariant should be testable — if you can't write a
test for it, it's a guideline, not an invariant.

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | What the user or system observes | Root cause | How to resolve |

Number sequentially. Focus on failures that have happened or are likely, not
every theoretical possibility.

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| Module or subsystem | internal/external | Path to its SPEC.md, or N/A |

---

**SPEC.md tree walk:** Not every directory needs its own SPEC.md. A subsystem
is covered by walking up the directory tree to the nearest SPEC.md. For example,
`src/ragling/tools/` is documented in its parent `src/ragling/SPEC.md` under
"Key files." A directory only needs its own SPEC.md when it has independent
invariants and failure modes that warrant separate tracking.

After creating a new SPEC.md, register it in [`docs/specs/MANIFEST.md`](specs/MANIFEST.md)
and add any cross-cutting concerns to the table there.
