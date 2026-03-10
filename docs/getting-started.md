# Getting Started

Install ragling, index your first source, search it, and connect to Claude.

## Prerequisites

- macOS
- [Homebrew](https://brew.sh)

```bash
brew install ollama uv
ollama pull bge-m3
```

Ollama runs as a background service after installation. Verify with: `curl http://localhost:11434`.

## Install ragling

```bash
git clone git@github.com:aihaysteve/local-rag.git ~/ragling
cd ~/ragling
```

No further setup needed. On first use, `uv run` creates the virtual environment and installs dependencies (takes a minute or two).

## Index Your First Source

Pick whichever source you have available:

```bash
# Obsidian vault
uv run ragling index obsidian --vault ~/Documents/MyVault

# Calibre ebook library
uv run ragling index calibre --library ~/CalibreLibrary

# eM Client emails
uv run ragling index email

# NetNewsWire RSS feeds
uv run ragling index rss

# Git repositories (define groups in config first)
uv run ragling index group my-org

# Any folder of documents
uv run ragling index project "My Docs" ~/Documents/project/
```

See [Indexing Sources](indexing.md) for full details on each source type.

## Search

```bash
uv run ragling search "kubernetes deployment strategy"
uv run ragling search "invoice" --collection email
uv run ragling search "machine learning" --author "Bishop"
```

ragling combines semantic search (meaning) with keyword search (exact terms) and merges the results. See [How Search Works](hybrid-search-and-rrf.md) for details.

## Connect to Claude

Give Claude access to your indexed knowledge via MCP (Model Context Protocol).

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

Once connected, Claude can search your indexed knowledge with the `rag_search` tool.

**Claude Code tip:** Copy the ragling skill into your project for better search patterns:

```bash
cp -r /path/to/ragling/.claude/skills/ragling your-project/.claude/skills/
```

## Add Ragling to a Project

Add ragling search to an existing project:

```bash
cd your-project
uv run --directory /path/to/ragling ragling init
```

This creates `ragling.json` and `.mcp.json` in your project directory. See [Project Setup](project-setup.md) for details.

## Next Steps

- [Configuration](configuration.md) — set up permanent paths for your sources
- [Automatic Indexing](automatic-indexing.md) — keep your index current with launchd
- [CLI Reference](cli.md) — all available commands
- [Multi-Agent Setup](multi-agent.md) — share one server across multiple AI agents
