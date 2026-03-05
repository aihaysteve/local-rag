# Ragling

Docling-powered local RAG system with hybrid vector + full-text search. Indexes personal knowledge from Obsidian vaults, emails, ebooks, RSS feeds, code repos, and project folders. Shared document cache with per-group vector indexes. Everything runs locally — no cloud APIs, no data leaves the machine.

## Using ragling

Use `/ragling` — MCP tools, search patterns, collection types, and best practices.

## Developing ragling

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow, quality gates, and skill reference. Key points:

- **Quality gate:** `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
- **TDD:** Strict red-green-refactor. No implementation code without a failing test.
- **Skills pipeline:** `/brainstorming` → `/writing-plans` → `/executing-plans` → `/verification-before-completion` → `/requesting-code-review` → `/finishing-a-development-branch`
- **PR target:** `aihaysteve/local-rag` (not upstream)

## NanoClaw integration

- `/nanoclaw` — set up ragling as the RAG backend for NanoClaw
- `/nanoclaw-agents` — reference for NanoClaw channel agents (scoping, path mappings, search patterns)

## Reference

- [docs/architecture.md](docs/architecture.md) — system design, schema, and data flow
- [docs/hybrid-search-and-rrf.md](docs/hybrid-search-and-rrf.md) — search algorithm details
- [docs/ollama-and-embeddings.md](docs/ollama-and-embeddings.md) — Ollama setup and embedding models
- [docs/project-setup.md](docs/project-setup.md) — add ragling to a project (init command, config, .mcp.json)

### Subsystem Map

| Subsystem | Path | Purpose |
|---|---|---|
| Core | `src/ragling/` | Configuration, storage, embeddings, indexing orchestration, MCP server facade, CLI |
| Tools | `src/ragling/tools/` | MCP tool modules — one tool per file with `register(mcp, ctx: ToolContext)` pattern |
| Document | `src/ragling/document/` | Document conversion, chunking, and format bridging |
| Auth | `src/ragling/auth/` | API key resolution, TLS certificates, token verification |
| Search | `src/ragling/search/` | Hybrid vector + full-text search with RRF |
| Watchers | `src/ragling/watchers/` | File system, database, and config change monitoring |
| Indexers | `src/ragling/indexers/` | Source-specific indexing pipelines |
| Parsers | `src/ragling/parsers/` | Format-specific content extraction for indexing |
| Skills | `.claude/skills/` | Reusable agent instruction documents |
