# Contributing

This project uses [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills to maintain contribution quality. Contributors are expected to use Claude Code with the `dev-workflow-toolkit` plugin installed.

## Quick Start

1. Fork and clone the repo
2. Install dependencies: `uv sync`
3. Run the quality gate to verify setup: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
4. Install the `dev-workflow-toolkit` plugin (provides workflow skills)

## Workflow

Every change — feature, fix, refactor, docs, or skill — follows this process:

### 1. File a GitHub issue

File a GitHub issue describing the problem and proposed solution. Use the feature request or bug report template. Small fixes can reference an existing issue.

### 2. Create a branch

Use `/using-git-worktrees` to create an isolated worktree for your work, or create a branch manually.

### 3. Brainstorm the design

Run `/brainstorming` to explore the problem space before writing code. This skill asks clarifying questions, considers alternatives, and produces a design you can review before committing to an approach.

### 4. Write an implementation plan

Run `/writing-plans` to produce a structured plan in `docs/plans/` (a local working directory, not committed). The plan breaks the work into self-contained tasks with exact file paths, code, and test commands. Paste the plan into your PR body when you open it.

### 5. Execute the plan

Run `/executing-plans` to implement the plan with checkpoints between tasks, or `/subagent-driven-development` for same-session execution with fresh subagents per task.

### 6. Verify before claiming done

`/verification-before-completion` triggers automatically before any completion claim. It requires running verification commands and confirming output — no "it should work" allowed.

### 7. Self-review

Run `/requesting-code-review` to dispatch a code review subagent that checks your work against the plan and project standards.

### 8. Finalize

`/finishing-a-development-branch` triggers automatically when work is complete. It guides you through merge prep, PR creation, or cleanup.

### 9. Open a pull request

Use the PR template. Include:
- Reference to the GitHub issue
- The implementation plan (paste into the collapsible details block)
- Atomic commits — one logical change per commit

## Quality Gate

All four must pass before any step is complete:

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

## TDD Workflow

Strict red-green-refactor. No implementation code without a failing test driving it.

1. **Red**: Write a test that fails for the behavior you're about to implement
2. **Green**: Write the simplest code that makes the test pass
3. **Refactor**: Clean up while keeping tests green

If the test is wrong (bad assertion, flawed assumption), fix the test — don't bend implementation to satisfy an incorrect test.

## Skill Reference

Workflow skills are provided by the `dev-workflow-toolkit` plugin. Project-specific skills (`ragling`, `nanoclaw`, `nanoclaw-agents`) ship in `.claude/skills/`.

### Auto-triggered (no explicit invocation needed)

| Skill | When it triggers |
|---|---|
| `/verification-before-completion` | Before any success or completion claim |
| `/code-simplification` | After verification passes, as a pipeline step |
| `/finishing-a-development-branch` | When implementation is complete and tests pass |

### Explicit invocation

| Skill | When to use |
|---|---|
| `/brainstorming` | Before creative work — features, components, behavior changes |
| `/writing-plans` | When you have requirements and need an implementation plan |
| `/executing-plans` | To execute a written plan with checkpoints |
| `/subagent-driven-development` | Same-session execution with fresh subagents and two-stage review |
| `/requesting-code-review` | Before submitting a PR, to self-review |
| `/systematic-debugging` | When encountering bugs or test failures |
| `/test-driven-development` | Before writing any implementation code |
| `/using-git-worktrees` | To create an isolated worktree for feature work |
| `/writing-clearly-and-concisely` | Final editing pass on prose (docs, commit messages) |
| `/writing-skills` | When creating or modifying skills in `.claude/skills/` |
| `/codify-subsystem` | To create or update a subsystem SPEC.md |
| `/dispatching-parallel-agents` | For 2+ independent tasks that can run in parallel |

## Project-Specific Guidelines

- **Dependencies.** If you add a dependency, update `pyproject.toml` and run `uv lock`.
- **Documentation.** If your change affects architecture, update `docs/ARCHITECTURE.md`. If it introduces or changes design patterns, update `docs/DESIGN.md`. If it modifies subsystem contracts, update the relevant `SPEC.md`. If it affects usage, output, or setup, update `README.md` and relevant user docs.
- **Coding standards.** Type hints on all function signatures. Dataclasses for structured data. Docstrings on public functions. No global state. Use `logging`, not print. Tests for all new functionality.
- **Key constraints.** Everything runs locally (no cloud APIs). Read-only access to external databases. Incremental indexing by default. Content-addressed doc store. Per-group isolation. WAL mode for all SQLite databases.

## Contributing Skills

Skills live in `.claude/skills/<skill-name>/SKILL.md`. To add or modify a skill:

1. Use `/writing-skills` — it applies TDD to process documentation
2. Follow the same issue, plan, PR workflow as any other contribution
3. Test the skill by running it in a fresh Claude Code session

## PR Target

All PRs should target `aihaysteve/local-rag`. Use `-R aihaysteve/local-rag` with `gh pr create`. Do **not** create PRs against the upstream `sebastianhutter/local-rag`.

## Attribution

Workflow skills are provided by the [`dev-workflow-toolkit`](https://github.com/stvhay/my-claude-plugins) plugin, which incorporates skills from [obra/superpowers](https://github.com/obra/superpowers) (MIT License, see [LICENSE.superpowers](LICENSE.superpowers)).

If you contribute a project-local skill derived from another source, add appropriate attribution and a license file.

## Code of Conduct

Be kind, be constructive, assume good intent.
