# ragling

Search your notes, emails, ebooks, RSS feeds, and code repos with one query. Shared document cache with separate indexes per group — index once, search from multiple AI agents. Powers the RAG backend for [NanoClaw](https://github.com/aihaysteve/nanoclaw). Everything runs locally; nothing leaves your machine.

Forked from [sebastianhutter/local-rag](https://github.com/sebastianhutter/local-rag). Built with [Claude](https://claude.ai). Powered by [Docling](https://github.com/DS4SD/docling) (IBM). Inspired by [devrag](https://github.com/strickvl/devrag).

## Capabilities

- **11 document formats** — PDF, DOCX, PPTX, XLSX, HTML, LaTeX, CSV, AsciiDoc, EPUB, images, plaintext
- **Audio transcription** — MP3, M4A, WAV, OGG, OPUS, and more via Whisper (local, optional)
- **PDF intelligence** — ML-powered table extraction, image descriptions (SmolVLM), code block and formula recognition
- **17 programming languages** — tree-sitter structural parsing extracts functions, classes, and symbols
- **Git commit history** — indexes commit messages and per-file diffs for code archaeology
- **Image descriptions** — standalone images described by a local vision model (PNG, JPG, TIFF, BMP, WebP)

## Supported Sources

| Source | What's Indexed |
|--------|---------------|
| **Obsidian** | All files in your vault (.md, .pdf, .docx, .html, .epub, .txt, .pptx, .xlsx, images) |
| **eM Client** | Emails (subject, body, sender, recipients, date, folder) |
| **Calibre** | Ebook content and metadata (EPUB, PDF) |
| **NetNewsWire** | RSS/Atom articles |
| **Code groups** | Git repos grouped by org/topic — tree-sitter structural parsing (17 languages) + commit history |
| **Project folders** | Any folder of documents, dispatched to the right parser by file type |

## Quick Start

```bash
# Install prerequisites
brew install ollama uv
ollama pull bge-m3

# Clone and index
git clone git@github.com:aihaysteve/local-rag.git ~/ragling
cd ~/ragling
uv run ragling index obsidian --vault ~/Documents/MyVault

# Search
uv run ragling search "kubernetes deployment strategy"
```

The first run takes a minute or two while `uv` installs dependencies. No configuration file needed — pass paths on the command line.

## Connect to Claude

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

## Documentation

- **[Getting Started](docs/getting-started.md)** — full onboarding walkthrough
- **[Indexing Sources](docs/indexing.md)** — all source types with examples
- **[Configuration](docs/configuration.md)** — config file reference
- **[CLI Reference](docs/cli.md)** — all commands at a glance
- **[Automatic Indexing](docs/automatic-indexing.md)** — keep your index current with launchd
- **[Multi-Agent Setup](docs/multi-agent.md)** — SSE transport for multiple AI agents
- **[Architecture](docs/architecture.md)** — system design, schema, data flow
- **[How Search Works](docs/hybrid-search-and-rrf.md)** — hybrid vector + keyword search with RRF
- **[Ollama & Embeddings](docs/ollama-and-embeddings.md)** — embedding model setup

## License & Credits

This project is licensed under the [MIT License](LICENSE).

**Credits:**
- Forked from [sebastianhutter/local-rag](https://github.com/sebastianhutter/local-rag)
- [Docling](https://github.com/DS4SD/docling) by IBM — ML-powered document conversion
- [devrag](https://github.com/strickvl/devrag) — inspiration for multi-group MCP architecture
- Built with [Claude](https://claude.ai) by Anthropic
