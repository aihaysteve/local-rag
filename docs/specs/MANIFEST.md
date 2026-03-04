# Subsystem Specifications

Index of all SPEC.md files in the ragling codebase.

## Index

| Subsystem | SPEC.md Path | Purpose |
|---|---|---|
| Core | `src/ragling/SPEC.md` | Configuration, search, storage, indexing orchestration, MCP server, CLI |
| Indexers | `src/ragling/indexers/SPEC.md` | Source-specific indexing pipelines |
| Parsers | `src/ragling/parsers/SPEC.md` | Format-specific content extraction for indexing |
| Skills | `.claude/skills/SPEC.md` | Reusable agent instruction documents |

## Cross-Cutting Concerns

| Concern | Relevant Specs | Notes |
|---|---|---|
| WAL mode and concurrent access | Core (INV-3), Indexers | All SQLite databases use WAL; retry logic shared between db.py and doc_store.py |
| Single-writer threading | Core (INV-4) | IndexingQueue worker is the only thread that writes to index DB; indexers rely on this contract but have no own invariant for it |
| Content-addressed caching | Core (INV-5), Parsers | DocStore deduplicates by SHA-256 hash + config_hash; parsers produce the conversion result that gets cached |
