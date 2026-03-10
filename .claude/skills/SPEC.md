# Skills Subsystem

## Purpose

The skills directory provides reusable agent instructions as Markdown documents.
Each skill is a self-contained directory with a SKILL.md frontmatter file that
Claude Code loads automatically based on keyword matching in the `description`
field. Skills encode proven techniques, processes, and domain expertise that
agents apply during specific task types (brainstorming, planning, testing, etc.).

Skills come from two sources: **project-local skills** in `.claude/skills/`
(project-specific tools like `ragling`, `nanoclaw`) and **plugin skills** from
installed Claude Code plugins (workflow skills like `brainstorming`,
`writing-plans`, `documentation-standards` from `dev-workflow-toolkit`). Both
are discovered and loaded identically by Claude Code.

## Core Mechanism

Claude Code discovers skills by scanning `.claude/skills/*/SKILL.md` for YAML
frontmatter. The `name` field maps to `/skill-name` invocation, and the
`description` field drives automatic keyword-based triggering. Skills are
self-contained directories with all support files co-located.

Some skills invoke other skills as sub-steps. For example, the
`documentation-standards` skill is invoked by `brainstorming` (draft mode,
after design approval) and `finishing-a-development-branch` (validate mode,
as a hard gate before PR creation). Cross-skill invocations are documented
in each skill's Integration section.

**Key files:**
- `*/SKILL.md` — Entry point for each skill (YAML frontmatter + Markdown body)

## Public Interface

| Export | Used By | Contract |
|---|---|---|
| YAML frontmatter `name` | Claude Code skill router | Must be unique, lowercase, hyphenated |
| YAML frontmatter `description` | Claude Code keyword matcher | Must contain trigger keywords |
| `/skill-name` invocation | Users and other skills | Must be stable across sessions |
| Cross-skill references | Skills referencing each other | Use skill name, not file path |

## Invariants

| ID | Invariant | Why It Matters |
|---|---|---|
| INV-1 | Every skill directory contains exactly one `SKILL.md` with valid YAML frontmatter (`name` + `description`) | Claude Code cannot discover or load skills without frontmatter |
| INV-2 | Skill names are unique across all `SKILL.md` files | Duplicate names cause routing ambiguity |
| INV-3 | Every tracked skill directory has a negated gitignore entry (`!.claude/skills/<name>/`) | Without the negation, git ignores the skill due to the `.claude/skills/*` blanket rule |
| INV-4 | Skills that reference other skills use the skill name (not file path) in their Integration section | Skill directories may move; names are the stable identifier |
| INV-5 | Support files (prompts, templates, examples) live inside the skill's own directory | Skills must be self-contained — an agent loads one directory |
| INV-6 | Skills that invoke other skills document the invocation in their Integration section, including the mode and trigger condition | Agents must understand the full skill chain to avoid skipping required steps or invoking skills out of order |

## Failure Modes

| ID | Symptom | Cause | Fix |
|---|---|---|---|
| FAIL-1 | Skill not discovered by Claude Code | Missing or malformed YAML frontmatter in SKILL.md | Add `---` fenced frontmatter with `name` and `description` fields |
| FAIL-2 | Wrong skill triggered for a task | Overly broad keywords in `description` field | Narrow the description; use specific trigger phrases |
| FAIL-3 | Skill changes lost after git operations | Missing negated gitignore entry for new skill directory | Add `!.claude/skills/<name>/` to `.gitignore` |
| FAIL-4 | Skill references broken after rename | Cross-references use file paths instead of skill names | Update references to use `/skill-name` form |

## Dependencies

| Dependency | Type | SPEC.md Path |
|---|---|---|
| Claude Code skill router | external | N/A — built into Claude Code runtime |
| dev-workflow-toolkit plugin | external | N/A — provides workflow skills (brainstorming, writing-plans, etc.) |
| docs/spec-template.md | internal | N/A — template reference, not a subsystem |
