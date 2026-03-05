# H1 / H2 Commit Selection

Commit dataset for Issue #45: "Test whether RAG-powered SPEC.md retrieval improves agent efficiency."

Token counting convention: `len(text) // 4` (integer division, no tiktoken required).

## SPEC.md Token Counts

| SPEC.md path | Tokens |
|---|---|
| `src/ragling/SPEC.md` | 1658 |
| `src/ragling/search/SPEC.md` | 591 |
| `src/ragling/indexers/SPEC.md` | 2396 |
| `src/ragling/parsers/SPEC.md` | 1660 |
| `src/ragling/document/SPEC.md` | 1077 |
| `src/ragling/auth/SPEC.md` | 516 |
| `src/ragling/watchers/SPEC.md` | 613 |

---

## Table 1 — Phase 1 commits (H1, single-subsystem)

| SHA | Message (short) | Subsystem | Nearest SPEC.md | SPEC.md tokens | .py files changed |
|---|---|---|---|---|---|
| `decd7f5` | data-driven system collection dispatch | Core | `src/ragling/SPEC.md` | 1658 | `src/ragling/mcp_server.py` |
| `91e8c52` | context managers and CLI index command deduplication | Core | `src/ragling/SPEC.md` | 1658 | `src/ragling/cli.py` |
| `1c1a8d6` | extract _result_to_dict and unify batch search response | Core | `src/ragling/SPEC.md` | 1658 | `src/ragling/mcp_server.py` |
| `6587df9` | extract format routing into dedicated module | Indexers | `src/ragling/indexers/SPEC.md` | 2396 | `src/ragling/indexers/format_routing.py`, `src/ragling/indexers/obsidian.py`, `src/ragling/indexers/project.py` |
| `8b244d1` | remove .md and .txt from code extension map | Parsers | `src/ragling/parsers/SPEC.md` | 1660 | `src/ragling/parsers/code.py` |
| `69f4b2d` | extract git subprocess helpers into git_commands.py | Indexers | `src/ragling/indexers/SPEC.md` | 2396 | `src/ragling/indexers/git_commands.py`, `src/ragling/indexers/git_indexer.py` |
| `339d14d` | type _result_to_dict parameter as SearchResult | Core | `src/ragling/SPEC.md` | 1658 | `src/ragling/mcp_server.py` |
| `3588421` | restore path validation for obsidian/calibre | Core | `src/ragling/SPEC.md` | 1658 | `src/ragling/cli.py` |
| `e5f5e69` | replace is_git bool tuple with IndexSource NamedTuple | Core | `src/ragling/SPEC.md` | 1658 | `src/ragling/cli.py` |
| `6c55a4b` | simplify factory by unifying construction into _build_indexer | Indexers | `src/ragling/indexers/SPEC.md` | 2396 | `src/ragling/indexers/factory.py` |

### Replacement notes

- `334992b` (code parser registry) was the original Parsers candidate but is **invalid**: it modifies `src/ragling/server.py` (Core) in addition to `src/ragling/parsers/code.py`, making it cross-cutting. Replaced with `8b244d1` (remove .md and .txt from code extension map), which touches only `src/ragling/parsers/code.py`.
- `1c1a8d6` was expected to be Search-only but touches only `src/ragling/mcp_server.py` (Core). It remains a valid single-subsystem commit; classification corrected to Core.
- `339d14d` was listed as the Search candidate but touches only `src/ragling/mcp_server.py` (Core). It remains valid as a Core commit.

---

## Table 2 — Phase 2 commits (H2, cross-cutting + control)

| SHA | Message (short) | Type | Subsystems touched | Warm-tier SPEC.mds | Total warm-tier tokens |
|---|---|---|---|---|---|
| `b8665d3` | extract serve orchestration into ServerOrchestrator | control | Core | `src/ragling/SPEC.md` | 1658 |
| `0cdc98a` | centralize indexer dispatch in factory.py, remove _rag_index_direct | cross-cutting | Core, Indexers | `src/ragling/SPEC.md`, `src/ragling/indexers/SPEC.md` | 4054 |
| `bca25f7` | parse_markdown INV-5 gap + document SPEC invariants | cross-cutting | Document, Parsers | `src/ragling/document/SPEC.md`, `src/ragling/parsers/SPEC.md` | 2737 |
| `6f3c56b` | SPEC.md indexing + project onboarding (init command, auto-discovery) | cross-cutting | Core, Indexers | `src/ragling/SPEC.md`, `src/ragling/indexers/SPEC.md` | 4054 |
| `cbd2ac3` | spec parser cleanup and Core subsystem refactor | cross-cutting | Core, Auth, Document, Indexers, Parsers, Search, Watchers | `src/ragling/SPEC.md`, `src/ragling/auth/SPEC.md`, `src/ragling/document/SPEC.md`, `src/ragling/indexers/SPEC.md`, `src/ragling/parsers/SPEC.md`, `src/ragling/search/SPEC.md`, `src/ragling/watchers/SPEC.md` | 8511 |

### Phase 2 subsystem detail

- **`b8665d3` (control):** `src/ragling/SPEC.md`, `src/ragling/cli.py`, `src/ragling/server.py` — all three files are in `src/ragling/` root (Core). Confirmed single-subsystem.
- **`0cdc98a`:** `src/ragling/cli.py`, `src/ragling/indexing_queue.py`, `src/ragling/mcp_server.py` (Core) + `src/ragling/indexers/factory.py` (Indexers). Expected Core + Indexers confirmed.
- **`bca25f7`:** `src/ragling/parsers/markdown.py` (Parsers) + `src/ragling/document/SPEC.md` (Document SPEC only, no Document .py files). Expected Document + Parsers confirmed; note only Parsers has actual .py changes.
- **`6f3c56b`:** `src/ragling/cli.py`, `src/ragling/config.py` (Core) + `src/ragling/indexers/project.py` (Indexers). Also modifies `CLAUDE.md` and `docs/` (no subsystem SPEC.md implied). Expected Core + Indexers + CLI; Core and Indexers confirmed (CLI is part of Core in this codebase).
- **`cbd2ac3`:** Mega-refactor moving modules into subpackages. Touches all seven subsystem directories. Also the foundational commit that created `auth/`, `document/`, `search/`, and `watchers/` as packages with their own SPEC.md files.
