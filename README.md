# ragling

A fully local, privacy-preserving RAG (Retrieval Augmented Generation) system for macOS. Indexes personal knowledge from multiple sources with hybrid vector + full-text search. Nothing leaves your machine.

Forked from [sebastianhutter/local-rag](https://github.com/sebastianhutter/local-rag). Built with [Claude](https://claude.ai). Powered by [Docling](https://github.com/DS4SD/docling) (IBM). Inspired by [devrag](https://github.com/strickvl/devrag).

## What It Does

ragling indexes content from your local apps and files, then lets you search across all of it — either from the command line or directly from Claude Desktop / Claude Code via MCP.

**Supported sources:**

| Source | What's Indexed |
|--------|---------------|
| **Obsidian** | All files in your vault (.md, .pdf, .docx, .html, .epub, .txt, .pptx, .xlsx, images) |
| **eM Client** | Emails (subject, body, sender, recipients, date, folder) |
| **Calibre** | Ebook content and metadata (EPUB, PDF) |
| **NetNewsWire** | RSS/Atom articles |
| **Code groups** | Git repos grouped by org/topic — tree-sitter structural parsing (11 languages) + commit history |
| **Project folders** | Any folder of documents, dispatched to the right parser by file type |

## What Changed From local-rag

- **Docling replaces PyMuPDF, python-docx, and epub/html/plaintext parsers.** One library handles PDF, DOCX, PPTX, XLSX, HTML, images, LaTeX, CSV, and AsciiDoc with ML-powered layout analysis.
- **5 PDF enrichments.** Picture descriptions (SmolVLM), code block extraction (codeformulav2), formula extraction to LaTeX (codeformulav2), accurate table detection (TableFormerMode.ACCURATE), and caption preservation.
- **Bridge functions** convert markdown, epub, email, RSS, and plaintext into DoclingDocument for unified HybridChunker chunking.
- **Shared document store.** Content-addressed cache (`doc_store.sqlite`) so multiple groups share expensive Docling conversions without re-processing.
- **Per-group vector indexes.** Each MCP instance gets its own embeddings in `~/.ragling/groups/{name}/index.db`, while sharing the document cache.
- **SSE transport** for multi-user and multi-agent setups, with API key auth, collection scoping, and path mappings.
- **Startup sync and file watching.** The `serve` command auto-indexes configured paths on startup and watches for file changes.
- **Chunk size reduced to 256 tokens** (from 500) for better retrieval precision with HybridChunker's tokenizer-aligned splitting.
- **Python 3.12+** (relaxed from 3.13+).
- **PyMuPDF (AGPL) removed** — all dependencies are now permissively licensed.

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

Create `~/.ragling/config.json` to set paths for your sources. See [config.example.json](config.example.json) for all available options.

To disable indexing for a collection without deleting its existing data, add it to `disabled_collections`:

```json
{
  "disabled_collections": ["email", "rss"]
}
```

Works with any collection name: system collections (`obsidian`, `email`, `calibre`, `rss`) or user-created ones (code group names, project names).

If you skip this step, you can pass paths directly on the command line.

### 2. Index Your Content

```bash
# Index Obsidian vault (from config or explicit path)
uv run ragling index obsidian
uv run ragling index obsidian --vault ~/Documents/MyVault

# Index eM Client emails
uv run ragling index email

# Index Calibre ebook libraries
uv run ragling index calibre
uv run ragling index calibre --library ~/CalibreLibrary

# Index NetNewsWire RSS articles
uv run ragling index rss

# Index code groups
uv run ragling index group my-org
uv run ragling index group                    # all groups from config
uv run ragling index group my-org --history   # code + commit history

# Index a folder of documents into a named project
uv run ragling index project "Client X" ~/Documents/client-x-docs/

# Index all configured sources at once
uv run ragling index all
```

All index commands support `--force` to re-index everything regardless of change detection.

### 3. Search

```bash
uv run ragling search "kubernetes deployment strategy"
uv run ragling search "invoice from supplier" --collection email
uv run ragling search "API specification" --collection "Client X"
uv run ragling search "budget report" --type pdf --after 2025-01-01
```

### 4. Use with Claude

Start the MCP server and connect it to Claude Desktop or Claude Code:

```bash
uv run ragling serve
```

**Claude Code** — add to your project's `.mcp.json`:
```json
{
  "mcpServers": {
    "ragling": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/ragling", "ragling", "serve"]
    }
  }
}
```

**Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "ragling": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/ragling", "ragling", "serve"]
    }
  }
}
```

Once connected, Claude can search your indexed knowledge using the `rag_search` tool.

## Multi-User / Agent Integration

ragling supports SSE transport for scenarios where multiple users or AI agents need to share a single server instance.

### Starting with SSE

```bash
# SSE only (no stdio)
ragling serve --sse --no-stdio --port 10001

# Both stdio and SSE simultaneously
ragling serve --sse --port 10001

# With a custom config file
ragling serve --sse --port 10001 --config /path/to/config.json
```

### Per-user configuration

Each user gets an API key, a set of system collections they can access, and path mappings that translate server-side paths into paths meaningful to their environment:

```json
{
  "users": {
    "alice": {
      "api_key": "sk-alice-secret",
      "system_collections": ["obsidian", "email", "calibre", "rss"],
      "path_mappings": {
        "~/Documents/": "/remote/documents/"
      }
    },
    "agent-1": {
      "api_key": "sk-agent-1-secret",
      "system_collections": ["obsidian"],
      "path_mappings": {}
    }
  }
}
```

### Collection scoping

Users only see collections listed in their `system_collections` array plus any code groups or projects they have access to. This keeps personal email out of shared agent contexts.

### Path mappings

Path mappings rewrite `source_uri` fields in search results so that file paths make sense to the client. For example, a remote agent can see `/remote/documents/report.pdf` instead of the server's local `~/Documents/report.pdf`.

## CLI Reference

```
ragling index obsidian [--vault PATH] [--force]      Index Obsidian vault(s)
ragling index email [--force]                        Index eM Client emails
ragling index calibre [--library PATH] [--force]     Index Calibre ebook libraries
ragling index rss [--force]                          Index NetNewsWire RSS articles
ragling index group [NAME] [--history] [--force]     Index code group(s)
ragling index project NAME PATH... [--force]         Index docs into a project
ragling index all [--force]                          Index all configured sources

ragling search QUERY [options]                       Hybrid search across collections
  --collection NAME                                  Search within a specific collection
  --type TYPE                                        Filter by source type (pdf, markdown, email, ...)
  --author TEXT                                      Filter by book author
  --after DATE                                       Only results after this date (YYYY-MM-DD)
  --before DATE                                      Only results before this date (YYYY-MM-DD)
  --top N                                            Number of results (default: 10)

ragling collections list                             List all collections
ragling collections info NAME                        Detailed collection info
ragling collections delete NAME                      Delete a collection and all its data

ragling status                                       Show database stats
ragling serve [--sse] [--port PORT] [--no-stdio]     Start MCP server
  --config PATH                                      Path to config file
  --group NAME                                       Group name for per-group indexes
```

Global options (apply to all commands):
```
--verbose, -v      Enable debug logging
--group, -g NAME   Group name for per-group indexes (default: "default")
--config, -c PATH  Path to config file
```

## How It Works

ragling uses a hybrid search approach combining semantic vector search with keyword full-text search:

1. **Indexing**: Documents are parsed by Docling (PDF, DOCX, PPTX, XLSX, HTML, images, LaTeX, CSV, AsciiDoc) or by dedicated parsers (markdown, code, email, RSS, Calibre). Parsed content is split into chunks (~256 tokens) using Docling's HybridChunker and embedded locally using Ollama (bge-m3 model). Converted documents are cached in a shared document store (`doc_store.sqlite`) so multiple groups never re-convert the same file. Chunks, embeddings, and metadata are stored in per-group SQLite databases.

2. **Search**: Your query is embedded and compared against stored vectors (semantic match) AND searched via FTS5 (keyword match). Results are merged using Reciprocal Rank Fusion (RRF).

Everything runs locally — embeddings are generated on your machine by Ollama, and the databases are SQLite files on disk.

## About Docling

[Docling](https://github.com/DS4SD/docling) is IBM's MIT-licensed document conversion library. It uses ML models to understand document layout, reading order, tables, code blocks, formulas, and image content — producing structured DoclingDocument output that preserves the logical hierarchy of a document. ragling uses Docling for all rich document formats and its HybridChunker for tokenizer-aligned chunking across all content types.

## Automatic Indexing with launchd

To keep your index up to date automatically, create a macOS launchd user agent. Unlike cron, launchd catches up on missed runs after your Mac wakes from sleep.

**1. Create the plist file:**

Run this from the ragling repository directory:

```bash
cat > ~/Library/LaunchAgents/com.ragling.index.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ragling.index</string>

    <key>ProgramArguments</key>
    <array>
        <string>$(which uv)</string>
        <string>run</string>
        <string>--directory</string>
        <string>$PWD</string>
        <string>ragling</string>
        <string>index</string>
        <string>all</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$(dirname $(which uv)):/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <!-- Run every 2 hours (7200 seconds) -->
    <key>StartInterval</key>
    <integer>7200</integer>

    <!-- Log output to ~/.ragling/index.log -->
    <key>StandardOutPath</key>
    <string>$HOME/.ragling/index.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.ragling/index.log</string>

    <!-- Run once immediately when loaded -->
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF
```

This resolves all paths automatically: `$(which uv)` finds your uv binary, `$PWD` uses the current directory (the ragling repo), and `$HOME` points to your home directory. Make sure to run the command from the ragling repository root.

**2. Load the agent:**

```bash
launchctl load ~/Library/LaunchAgents/com.ragling.index.plist
```

**3. Verify it's running:**

```bash
launchctl list | grep ragling
tail -f ~/.ragling/index.log
```

**Managing the agent:**

```bash
# Stop and unload
launchctl unload ~/Library/LaunchAgents/com.ragling.index.plist

# Reload after editing the plist
launchctl unload ~/Library/LaunchAgents/com.ragling.index.plist
launchctl load ~/Library/LaunchAgents/com.ragling.index.plist
```

**Plist fields explained:**

| Field | Purpose |
|-------|---------|
| `Label` | Unique identifier for the job |
| `ProgramArguments` | Command to run, split into argv array |
| `EnvironmentVariables` | Sets `PATH` so launchd can find `uv` and `ollama` (launchd jobs start with a minimal environment) |
| `StartInterval` | Run every N seconds (7200 = 2 hours) |
| `StandardOutPath/ErrorPath` | Where stdout/stderr are written |
| `RunAtLoad` | Run immediately when the agent is loaded (on login or after `launchctl load`) |

## Documentation

- [Architecture overview](docs/architecture.md) — system design, data flow, database schema, supported file types
- [Ollama and embeddings](docs/ollama-and-embeddings.md) — what Ollama does, how embeddings work, model configuration
- [Hybrid search and RRF](docs/hybrid-search-and-rrf.md) — how vector + keyword search are combined
- [eM Client schema](docs/emclient-schema.md) — eM Client database structure and how emails are extracted

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12+ |
| Database | SQLite + sqlite-vec + FTS5 |
| Embeddings | Ollama + bge-m3 (1024d) |
| Document conversion | Docling (PDF, DOCX, PPTX, XLSX, HTML, images, LaTeX, CSV, AsciiDoc) |
| Bridge functions | Markdown, EPUB, plaintext, email, RSS to DoclingDocument |
| Code parsing | tree-sitter (11 languages) |
| Dedicated parsers | eM Client email, NetNewsWire RSS, Calibre metadata |
| Chunking | Docling HybridChunker (tokenizer-aligned, 256 tokens) |
| CLI | click + rich |
| MCP server | mcp Python SDK (FastMCP) |
| File watching | watchdog |

## License & Credits

This project is licensed under the [MIT License](LICENSE).

**Credits:**
- Forked from [sebastianhutter/local-rag](https://github.com/sebastianhutter/local-rag) — the original local RAG system this project builds on
- [Docling](https://github.com/DS4SD/docling) by IBM — ML-powered document conversion engine
- [devrag](https://github.com/strickvl/devrag) — inspiration for multi-group MCP architecture
- Built with [Claude](https://claude.ai) by Anthropic
