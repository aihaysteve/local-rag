---
name: contributing
description: Use when developing ragling — modifying source code, adding features, fixing bugs, refactoring, or working on the ragling codebase
---

# Contributing to Ragling

## Overview

Ragling is a Docling-powered local RAG system. This skill defines the development workflow, required skills, quality gates, and constraints for any agent working on the codebase.

**Core principle:** Process is not overhead — it's how quality is maintained. The four-check gate and TDD workflow exist because "quick fixes" compound into technical debt.

## Required Skills Pipeline

Every change to ragling follows this pipeline. **No exceptions.**

| Phase | Skill | When |
|-------|-------|------|
| Design | **brainstorming-design** | Before any creative work — features, components, behavior changes |
| Planning | **writing-plans** | Multi-step tasks, before touching code |
| Implementation | **test-driven-development** | Every feature and bugfix — test FIRST |
| Debugging | **systematic-debugging** | Any bug, test failure, or unexpected behavior |
| Verification | **verification-before-completion** | Before claiming work is done |
| Simplification | **code-simplification** | After verification passes |
| Review | **requesting-code-review** | Before merging or completing major work |
| Feedback | **receiving-code-review** | When processing review comments |
| Completion | **finishing-a-development-branch** | When implementation is complete and tests pass |

**REQUIRED:** Use brainstorming-design before implementing. Use test-driven-development before writing code. Use verification-before-completion before claiming done.

## The Quality Gate

All four must pass before any step is complete:

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

Not just pytest. Not "I'll run the others later." All four. Every time.

## TDD Workflow

Strict red-green-refactor. No implementation code without a failing test driving it.

1. **Red**: Write a test that fails for the behavior you're about to implement
2. **Green**: Write the simplest code that makes the test pass
3. **Refactor**: Clean up while keeping tests green

If the test is wrong (bad assertion, flawed assumption), fix the test — don't bend implementation to satisfy an incorrect test.

## Tooling

| Tool | Purpose | Command |
|------|---------|---------|
| uv | Package management, venv, running | `uv run ...` |
| ruff | Linting and formatting | `uv run ruff check .` / `uv run ruff format .` |
| pytest | Testing | `uv run pytest` |
| mypy | Static type checking | `uv run mypy src/` |

Run tests frequently: `uv run pytest -x` to stop on first failure.

## Coding Standards

- Type hints on all function signatures
- Dataclasses for structured data (Chunk, SearchResult, etc.)
- Docstrings on public functions
- No global state — pass db connections and config explicitly
- Use `logging` module, not print statements
- Tests for all new functionality

## Key Constraints

- **Everything runs locally.** No cloud APIs, no API keys, no data leaves the machine.
- **Read-only external databases.** eM Client, Calibre, NetNewsWire opened in SQLite read-only mode.
- **Incremental indexing by default.** SHA-256 hashes for change detection. `--force` to re-index.
- **Content-addressed doc store.** SHA-256 file hash + config hash in `doc_store.sqlite`. Never re-convert a cached document.
- **Per-group isolation.** Each MCP instance gets its own embedding index. Groups share doc store but not vectors.
- **WAL mode for all SQLite databases.** Enables concurrent reads from multiple MCP instances.
- **Graceful error handling.** Never crash mid-index — log errors and continue.

## Project Structure

Key modules in `src/ragling/`:

- `cli.py` — Click CLI entry point
- `config.py` — Configuration loading and validation
- `db.py` — Database init, migrations, connections
- `search.py` — Hybrid search engine (vector + FTS + RRF)
- `mcp_server.py` — MCP server (stdio + SSE transports)
- `doc_store.py` — Content-addressed document cache
- `docling_convert.py` — Docling DocumentConverter wrapper
- `indexers/` — Per-source indexers (obsidian, email, calibre, rss, git, project)
- `parsers/` — Format parsers (markdown, email, calibre, rss, code, epub)

For detailed architecture: read `docs/architecture.md`.

## PR Workflow

- Work inside `local-rag/` — that's the codebase being modified
- Atomic commits per plan step with clear messages
- Keep diffs reviewable: no unrelated changes, no unnecessary reformatting
- Preserve backwards compatibility where possible
- Update docs if behavior changes

## Red Flags — STOP and Reconsider

- Writing code before writing a test
- Running only pytest and skipping mypy/ruff
- "This is too simple to need a test"
- "I'll add tests after"
- "Time pressure — just make the change"
- Skipping brainstorming-design for a new feature
- Claiming work is complete without running the four-check gate

**All of these mean: slow down, follow the process.**

## Reference

- [docs/architecture.md](docs/architecture.md) — system design and data flow
- [docs/hybrid-search-and-rrf.md](docs/hybrid-search-and-rrf.md) — search algorithm
- [docs/ollama-and-embeddings.md](docs/ollama-and-embeddings.md) — embedding setup
