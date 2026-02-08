# local-rag

A fully local, privacy-preserving RAG (Retrieval Augmented Generation) system for macOS. Indexes personal knowledge from multiple sources into a single SQLite database with hybrid vector + full-text search. Nothing leaves your machine.

## What It Does

local-rag indexes content from your local apps and files, then lets you search across all of it — either from the command line or directly from Claude Desktop / Claude Code via MCP.

**Supported sources:**

| Source | What's Indexed |
|--------|---------------|
| **Obsidian** | All files in your vault (.md, .pdf, .docx, .html, .epub, .txt) |
| **eM Client** | Emails (subject, body, sender, recipients, date) |
| **Calibre** | Ebook content and metadata (EPUB, PDF) |
| **NetNewsWire** | RSS/Atom articles |
| **Git repos** | Code files with structural parsing (Python, Go, TypeScript, Rust, Java, C, and more) |
| **Project folders** | Any folder of documents, dispatched to the right parser by file type |

## Prerequisites

- macOS
- [Homebrew](https://brew.sh)

```bash
brew install ollama uv
ollama pull bge-m3
```

Ollama runs as a background service on macOS after installation. Verify with `curl http://localhost:11434`.

## Getting Started

No installation step needed — `uv run` handles the virtual environment automatically.

### 1. Configure (optional)

Create `~/.local-rag/config.json` to set paths for your sources. See [config.example.json](config.example.json) for all available options.

To disable indexing for a collection without deleting its existing data, add it to `disabled_collections`:

```json
{
  "disabled_collections": ["email", "rss"]
}
```

Works with any collection name: system collections (`obsidian`, `email`, `calibre`, `rss`) or user-created ones (repo names, project names).

If you skip this step, you can pass paths directly on the command line.

### 2. Index Your Content

```bash
# Index Obsidian vault (from config or explicit path)
uv run local-rag index obsidian
uv run local-rag index obsidian --vault ~/Documents/MyVault

# Index eM Client emails
uv run local-rag index email

# Index Calibre ebook libraries
uv run local-rag index calibre
uv run local-rag index calibre --library ~/CalibreLibrary

# Index NetNewsWire RSS articles
uv run local-rag index rss

# Index a git repository
uv run local-rag index repo ~/Repository/my-project
uv run local-rag index repo  # indexes all repos from config

# Index a folder of documents into a named project
uv run local-rag index project "Client X" ~/Documents/client-x-docs/

# Index all configured sources at once
uv run local-rag index all
```

All index commands support `--force` to re-index everything regardless of change detection.

### 3. Search

```bash
uv run local-rag search "kubernetes deployment strategy"
uv run local-rag search "invoice from supplier" --collection email
uv run local-rag search "API specification" --collection "Client X"
uv run local-rag search "budget report" --type pdf --after 2025-01-01
```

### 4. Use with Claude

Start the MCP server and connect it to Claude Desktop or Claude Code:

```bash
uv run local-rag serve
```

**Claude Code** — add to your project's `.mcp.json`:
```json
{
  "mcpServers": {
    "local-rag": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/local-rag", "local-rag", "serve"]
    }
  }
}
```

**Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "local-rag": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/local-rag", "local-rag", "serve"]
    }
  }
}
```

Once connected, Claude can search your indexed knowledge using the `rag_search` tool.

## CLI Reference

```
local-rag index obsidian [--vault PATH] [--force]    Index Obsidian vault(s)
local-rag index email [--force]                      Index eM Client emails
local-rag index calibre [--library PATH] [--force]   Index Calibre ebook libraries
local-rag index rss [--force]                        Index NetNewsWire RSS articles
local-rag index repo [PATH] [--name NAME] [--force]  Index a git repository
local-rag index project NAME PATH... [--force]       Index docs into a project
local-rag index all [--force]                         Index all configured sources

local-rag search QUERY [options]                     Hybrid search across collections
  --collection NAME                                  Search within a specific collection
  --type TYPE                                        Filter by source type (pdf, markdown, email, ...)
  --author TEXT                                      Filter by book author
  --after DATE                                       Only results after this date (YYYY-MM-DD)
  --before DATE                                      Only results before this date (YYYY-MM-DD)
  --top N                                            Number of results (default: 10)

local-rag collections list                           List all collections
local-rag collections info NAME                      Detailed collection info
local-rag collections delete NAME                    Delete a collection and all its data

local-rag status                                     Show database stats
local-rag serve [--port PORT]                        Start MCP server (stdio or HTTP/SSE)
```

## How It Works

local-rag uses a hybrid search approach combining semantic vector search with keyword full-text search:

1. **Indexing**: Documents are parsed, split into chunks (~500 tokens), and embedded locally using Ollama (bge-m3 model). Chunks, embeddings, and metadata are stored in SQLite.
2. **Search**: Your query is embedded and compared against stored vectors (semantic match) AND searched via FTS5 (keyword match). Results are merged using Reciprocal Rank Fusion.

Everything runs locally — embeddings are generated on your machine by Ollama, and the database is a single SQLite file.

## Documentation

- [Architecture overview](docs/architecture.md) — system design, data flow, database schema, supported file types
- [Ollama and embeddings](docs/ollama-and-embeddings.md) — what Ollama does, how embeddings work, model configuration
- [Hybrid search and RRF](docs/hybrid-search-and-rrf.md) — how vector + keyword search are combined
- [eM Client schema](docs/emclient-schema.md) — eM Client database structure and how emails are extracted

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.13+ |
| Database | SQLite + sqlite-vec + FTS5 |
| Embeddings | Ollama + bge-m3 (1024d) |
| PDF parsing | pymupdf |
| DOCX parsing | python-docx |
| EPUB parsing | zipfile + BeautifulSoup |
| Code parsing | tree-sitter |
| CLI | click |
| MCP server | mcp Python SDK (FastMCP) |
