# Subsystem Specifications

Index of all SPEC.md files in the ragling codebase.

## Index

| Subsystem | SPEC.md Path | Purpose |
|---|---|---|
| Core | `src/ragling/SPEC.md` | Configuration, storage, embeddings, indexing orchestration, MCP server, CLI |
| Document | `src/ragling/document/SPEC.md` | Document conversion, chunking, and format bridging |
| Auth | `src/ragling/auth/SPEC.md` | API key resolution, TLS certificates, token verification |
| Search | `src/ragling/search/SPEC.md` | Hybrid vector + full-text search with RRF |
| Watchers | `src/ragling/watchers/SPEC.md` | File system, database, and config change monitoring |
| Indexers | `src/ragling/indexers/SPEC.md` | Source-specific indexing pipelines |
| Parsers | `src/ragling/parsers/SPEC.md` | Format-specific content extraction for indexing |
| Skills | `.claude/skills/SPEC.md` | Reusable agent instruction documents |

## Cross-Cutting Concerns

| Concern | Relevant Specs | Notes |
|---|---|---|
| WAL mode and concurrent access | Core (INV-3), Indexers | All SQLite databases use WAL; retry logic shared between db.py and doc_store.py |
| Single-writer threading | Core (INV-4), Indexers (consumer) | IndexingQueue worker is the only thread that writes to index DB; indexers rely on this contract but have no own invariant for it |
| Content-addressed caching | Core (INV-5), Parsers | DocStore deduplicates by SHA-256 hash + config_hash; parsers produce the conversion result that gets cached |
