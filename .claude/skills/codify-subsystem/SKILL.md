---
name: codify-subsystem
description: Use when a subsystem directory needs a SPEC.md — analyzes code, interviews the developer about invariants and failure modes, and produces a machine-readable specification
---

# Codify Subsystem

## Overview

Create or update a SPEC.md for a subsystem directory. Analyzes the code,
interviews the developer about purpose, invariants, and failure modes,
then produces a specification that agents load when working on that subsystem.

**Announce at start:** "I'm using the codify-subsystem skill to create a specification for [directory]."

## When to Use

- A directory has 3+ source files and no SPEC.md
- A new feature directory is created
- An agent encounters a subsystem it doesn't understand
- After significant refactoring that changes a subsystem's invariants
- During onboarding to document existing subsystems

## Checklist

You MUST complete these steps in order:

1. **Identify target directory** — confirm with user which directory to codify
2. **Analyze code** — read all files, identify patterns, entry points, exports
3. **Draft initial spec** — produce a first draft from code analysis alone
4. **Interview developer** — ask about invariants, failure modes, and testing (one question at a time)
5. **Finalize SPEC.md** — incorporate interview answers into the spec
6. **Update subsystem map** — add entry to CLAUDE.md's Subsystem Map table
7. **Update MANIFEST.md** — add entry to `docs/specs/MANIFEST.md`

## The Process

### Step 1: Identify Target

Ask the user which directory to codify, or accept the path they provided.
Confirm the directory exists and list its files.

### Step 2: Analyze Code

Read all source files in the directory. Identify:
- Entry points and public API
- Internal data flow
- Dependencies (imports, external calls)
- Existing tests and their coverage
- Patterns and conventions used

### Step 3: Draft Initial Spec

Using the format from `docs/spec-template.md`, draft a SPEC.md from what the
code analysis reveals. Mark sections where you're uncertain with `[NEEDS INPUT]`.

Present the draft to the developer.

### Step 4: Interview Developer

Ask about each `[NEEDS INPUT]` section plus these critical areas, one question
at a time:

**Invariants:** "What must ALWAYS be true about this subsystem? What rules, if
broken, would cause bugs?" (Examples: "order of operations matters", "this
value is never null after init", "these two fields must stay in sync")

**Failure modes:** "What are the known ways this breaks? What symptoms have you
seen, and what caused them?"

**Testing:** "How do you verify this subsystem works? What's the exact command?
Any special setup needed?"

**Purpose:** "Anything about *why* this subsystem exists that isn't obvious from
the code?" (Sometimes the code shows *what* but not *why* — design decisions,
alternatives considered, constraints from external systems.)

### Step 5: Finalize SPEC.md

Incorporate all answers. Write the final SPEC.md to the target directory.

**INV comments in tests:** After writing the SPEC.md, add `# Tests INV-X`
or `# Tests FAIL-X` inline comments to existing test methods that verify
spec items. This keeps invariant-test traceability in the code where it
stays in sync naturally, rather than in a markdown table that drifts.

**Size check:** If the spec exceeds 400 lines, suggest splitting the subsystem
or summarizing verbose sections.

### Step 6: Update Subsystem Map

Add an entry to the `### Subsystem Map` table in `CLAUDE.md`:

```markdown
| [Subsystem Name] | [path/to/directory] | [One-line purpose] |
```

### Step 7: Update Manifest

Add an entry to the `## Index` table in `docs/specs/MANIFEST.md`:

```markdown
| [Subsystem Name] | [path/to/SPEC.md] | [One-line summary] |
```

If the spec covers cross-cutting concerns, also add to the
`## Cross-Cutting Concerns` table.

## Key Principles

- **One question at a time** — don't overwhelm the developer
- **Code analysis first** — draft from code before asking questions
- **Invariants are the most important section** — push for specifics
- **100-400 lines** — under 100 means missing detail, over 400 means split
- **Machine-readable format** — consistent sections, tables for structured data
- **Commit the SPEC.md** — specs are load-bearing artifacts, version-controlled

## Integration

**Related skills:**
- **brainstorming** — may recommend codify-subsystem when subsystem boundaries are identified
- **writing-plans** — loads SPEC.md into task context
- **subagent-driven-development** — prepends SPEC.md context when dispatching implementer subagents
- **executing-plans** — loads nearest SPEC.md before executing each task
- **verification-before-completion** — checks SPEC.md invariants after verification
