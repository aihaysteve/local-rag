# <Subsystem Name>

## Purpose

What this subsystem does and why it exists. Lead with the core responsibility,
then state the key design decision that shapes the implementation.

Two paragraphs max.

## Core Mechanism

How the subsystem works. Cover:
- Entry points and main data flow
- Key files and their roles
- Important internal patterns

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

## Testing

How to verify this subsystem works:

```bash
uv run pytest tests/test_<relevant>.py -v
```

### Coverage

| Spec Item | Test | Description |
|---|---|---|
| INV-1 | `test_inv1_description` | What the test verifies |
| FAIL-1 | `test_fail1_description` | What the test verifies |

Map existing tests to spec items. Flag items that lack tests. Tests don't need
to be renamed — document the existing name and the recommended name if different.

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| Module or subsystem | internal/external | Path to its SPEC.md, or N/A |
