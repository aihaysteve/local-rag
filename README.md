# ragling

A fully local, privacy-preserving RAG system for macOS. Indexes personal knowledge from multiple sources with hybrid vector + full-text search. Nothing leaves your machine.

Forked from [sebastianhutter/local-rag](https://github.com/sebastianhutter/local-rag). Built with [Claude](https://claude.ai). Powered by [Docling](https://github.com/DS4SD/docling) (IBM). Inspired by [devrag](https://github.com/strickvl/devrag).

## Supported Sources

| Source | What's Indexed |
|--------|---------------|
| **Obsidian** | All files in your vault (.md, .pdf, .docx, .html, .epub, .txt, .pptx, .xlsx, images) |
| **eM Client** | Emails (subject, body, sender, recipients, date, folder) |
| **Calibre** | Ebook content and metadata (EPUB, PDF) |
| **NetNewsWire** | RSS/Atom articles |
| **Code groups** | Git repos grouped by org/topic — tree-sitter structural parsing (11 languages) + commit history |
| **Project folders** | Any folder of documents, dispatched to the right parser by file type |

## Prerequisites

- macOS
- [Homebrew](https://brew.sh)

```bash
brew install ollama uv
ollama pull bge-m3
```

Ollama runs as a background service on macOS after installation. Verify with `curl http://localhost:11434`.

## Quick Start

No configuration needed — defaults work out of the box, and `uv run` handles the virtual environment automatically.

```bash
# Clone the repo
git clone git@github.com:aihaysteve/local-rag.git ~/ragling
cd ~/ragling

# Index something (pick any source you have)
uv run ragling index obsidian --vault ~/Documents/MyVault

# Search
uv run ragling search "kubernetes deployment strategy"

# Connect to Claude Code (see below)
```

The first run takes a minute or two while uv creates the venv and installs dependencies. Subsequent runs start quickly.

## Indexing Sources

All index commands support `--force` to re-index everything regardless of change detection.

### Obsidian

Indexes all files in your vault — markdown, PDF, DOCX, PPTX, images, and more. Docling handles rich formats with ML-powered layout analysis.

```bash
uv run ragling index obsidian                          # from config
uv run ragling index obsidian --vault ~/Documents/MyVault  # explicit path
```

### eM Client

Reads the eM Client SQLite database in read-only mode. Indexes email subject, body, sender, recipients, date, and folder.

```bash
uv run ragling index email
```

### Calibre

Indexes ebook content (EPUB, PDF) and metadata (author, tags, series) from your Calibre library. Reads `metadata.db` in read-only mode.

```bash
uv run ragling index calibre                               # from config
uv run ragling index calibre --library ~/CalibreLibrary    # explicit path
```

### NetNewsWire

Indexes RSS/Atom articles from NetNewsWire's SQLite database in read-only mode.

```bash
uv run ragling index rss
```

### Code Groups

Indexes git repositories grouped by org or topic. Uses tree-sitter for structural parsing of 11 languages. Optionally includes commit history (messages and per-file diffs).

```bash
uv run ragling index group my-org              # one group
uv run ragling index group                     # all groups from config
uv run ragling index group my-org --history    # code + commit history
```

Code groups are defined in `config.json`:
```json
{
  "code_groups": {
    "my-org": ["~/Repository/my-org/repo1", "~/Repository/my-org/repo2"],
    "terraform": ["~/Repository/tf-infra", "~/Repository/tf-modules"]
  }
}
```

### Project Folders

Indexes any folder of documents into a named collection. Files are dispatched to the right parser by extension.

```bash
uv run ragling index project "Client X" ~/Documents/client-x-docs/
```

### All at Once

```bash
uv run ragling index all
```

## Connect to Claude

Start the MCP server and connect it to Claude Desktop or Claude Code.

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

Once connected, Claude can search your indexed knowledge using the `rag_search` tool. For Claude Code users, copy the ragling skill to your project for better search patterns:

```bash
cp -r /path/to/ragling/.claude/skills/ragling your-project/.claude/skills/
```

## Configuration

Create `~/.ragling/config.json` to set paths for your sources. See [config.example.json](config.example.json) for all options.

If you skip this, you can pass paths directly on the command line (as shown in the Quick Start and Indexing sections above).

```json
{
  "db_path": "~/.ragling/rag.db",
  "shared_db_path": "~/.ragling/doc_store.sqlite",
  "embedding_model": "bge-m3",
  "embedding_dimensions": 1024,
  "chunk_size_tokens": 256,
  "obsidian_vaults": ["~/Documents/MyVault"],
  "obsidian_exclude_folders": ["_Inbox", "_Templates"],
  "emclient_db_path": "~/Library/Application Support/eM Client",
  "calibre_libraries": ["~/CalibreLibrary"],
  "netnewswire_db_path": "~/Library/Containers/com.ranchero.NetNewsWire-Evergreen/Data/Library/Application Support/NetNewsWire/Accounts",
  "code_groups": {
    "my-org": ["~/Repository/my-org/repo1", "~/Repository/my-org/repo2"]
  },
  "disabled_collections": [],
  "git_history_in_months": 6,
  "search_defaults": {
    "top_k": 10,
    "rrf_k": 60,
    "vector_weight": 0.7,
    "fts_weight": 0.3
  }
}
```

To disable a collection without deleting its data, add it to `disabled_collections`:

```json
{
  "disabled_collections": ["email", "rss"]
}
```

## Automatic Indexing with launchd

Keep your index up to date automatically. Unlike cron, launchd catches up on missed runs after your Mac wakes from sleep.

**1. Create the plist file** (run from the ragling repo directory):

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

    <key>StartInterval</key>
    <integer>7200</integer>

    <key>StandardOutPath</key>
    <string>$HOME/.ragling/index.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.ragling/index.log</string>

    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF
```

**2. Load the agent:**

```bash
launchctl load ~/Library/LaunchAgents/com.ragling.index.plist
```

**3. Verify:**

```bash
launchctl list | grep ragling
tail -f ~/.ragling/index.log
```

**Managing:**

```bash
# Stop and unload
launchctl unload ~/Library/LaunchAgents/com.ragling.index.plist

# Reload after editing the plist
launchctl unload ~/Library/LaunchAgents/com.ragling.index.plist
launchctl load ~/Library/LaunchAgents/com.ragling.index.plist
```

## How It Works

ragling uses a hybrid search approach combining semantic vector search with keyword full-text search:

1. **Indexing**: Documents are parsed by Docling (PDF, DOCX, PPTX, XLSX, HTML, images, LaTeX, CSV, AsciiDoc) or by dedicated parsers (markdown, code, email, RSS, Calibre). Parsed content is split into chunks (~256 tokens) using Docling's HybridChunker and embedded locally using Ollama (bge-m3 model). Converted documents are cached in a shared document store (`doc_store.sqlite`) so multiple groups never re-convert the same file. Chunks, embeddings, and metadata are stored in per-group SQLite databases.

2. **Search**: Your query is embedded and compared against stored vectors (semantic match) AND searched via FTS5 (keyword match). Results are merged using Reciprocal Rank Fusion (RRF).

Everything runs locally — embeddings are generated on your machine by Ollama, and the databases are SQLite files on disk.

### About Docling

[Docling](https://github.com/DS4SD/docling) is IBM's MIT-licensed document conversion library. It uses ML models to understand document layout, reading order, tables, code blocks, formulas, and image content. ragling uses Docling for all rich document formats and its HybridChunker for tokenizer-aligned chunking.

## Advanced: Multi-Agent Setup

ragling supports SSE transport for scenarios where multiple users or AI agents share a single server.

### Starting with SSE

SSE always uses HTTPS with auto-generated self-signed certificates (stored in `~/.ragling/tls/`). TLS is mandatory because SSE uses Bearer token authentication — tokens must not be transmitted in plaintext.

```bash
ragling serve --sse --no-stdio --port 10001
ragling serve --sse --port 10001 --config /path/to/config.json
```

Generate MCP client config JSON (includes CA cert path):
```bash
ragling mcp-config --port 10001
```

### Per-user configuration

Each user gets an API key, collection visibility, and path mappings:

```json
{
  "home": "~/agents/groups",
  "global_paths": ["~/agents/global"],
  "users": {
    "agent-1": {
      "api_key": "rag_your_generated_key",
      "system_collections": ["obsidian"],
      "path_mappings": {
        "~/agents/groups/agent-1/": "/workspace/group/",
        "~/agents/global/": "/workspace/global/"
      }
    }
  }
}
```

Generate API keys: `python3 -c "import secrets; print(f'rag_{secrets.token_hex(16)}')"``

### Collection scoping

Users only see collections listed in their `system_collections` array plus their own group and global content. Queries against inaccessible collections return zero results.

### Path mappings

Path mappings rewrite `source_path` and `source_uri` in search results so file paths make sense to the client. Keys are server-side prefixes (with `~/` expanded); values are client-side replacements.

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
  --type TYPE                                        Filter by source type
  --author TEXT                                      Filter by book author
  --after DATE                                       Only results after this date
  --before DATE                                      Only results before this date
  --top N                                            Number of results (default: 10)

ragling collections list                             List all collections
ragling collections info NAME                        Detailed collection info
ragling collections delete NAME                      Delete a collection

ragling status                                       Show database stats
ragling serve [--sse] [--port PORT] [--no-stdio]     Start MCP server
ragling mcp-config [--port PORT]                     Output MCP client config JSON
```

Global options: `--verbose/-v`, `--group/-g NAME`, `--config/-c PATH`

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12+ |
| Database | SQLite + sqlite-vec + FTS5 |
| Embeddings | Ollama + bge-m3 (1024d) |
| Document conversion | Docling (PDF, DOCX, PPTX, XLSX, HTML, images, LaTeX, CSV, AsciiDoc) |
| Bridge functions | Markdown, EPUB, plaintext, email, RSS to DoclingDocument |
| Code parsing | tree-sitter (11 languages) |
| Chunking | Docling HybridChunker (tokenizer-aligned, 256 tokens) |
| CLI | click + rich |
| MCP server | mcp Python SDK (FastMCP) |
| File watching | watchdog |

## Documentation

- [Architecture overview](docs/architecture.md) — system design, data flow, database schema
- [Hybrid search and RRF](docs/hybrid-search-and-rrf.md) — how vector + keyword search are combined
- [Ollama and embeddings](docs/ollama-and-embeddings.md) — Ollama setup, embedding models
- [eM Client schema](docs/emclient-schema.md) — eM Client database structure

## License & Credits

This project is licensed under the [MIT License](LICENSE).

**Credits:**
- Forked from [sebastianhutter/local-rag](https://github.com/sebastianhutter/local-rag)
- [Docling](https://github.com/DS4SD/docling) by IBM — ML-powered document conversion
- [devrag](https://github.com/strickvl/devrag) — inspiration for multi-group MCP architecture
- Built with [Claude](https://claude.ai) by Anthropic
