# Add Ragling to Your Project

Set up ragling to index and search your project's documents, code, and data.

## Prerequisites

- [Ollama](https://ollama.com) running with the `bge-m3` embedding model
- [uv](https://docs.astral.sh/uv/) for Python package management
- ragling cloned locally (e.g., `~/ragling`)

```bash
brew install ollama uv
ollama pull bge-m3
git clone https://github.com/aihaysteve/local-rag.git ~/ragling
```

## Quick Setup

From your project directory:

```bash
uv run --directory ~/ragling ragling init
```

This creates two files:

**`ragling.json`** — tells ragling to watch your project directory:
```json
{
  "watch": {
    "my-project": "."
  }
}
```

**`.mcp.json`** — connects Claude to ragling:
```json
{
  "mcpServers": {
    "ragling": {
      "command": "uv",
      "args": [
        "run", "--directory", "/Users/you/ragling",
        "ragling", "--config", "/Users/you/my-project/ragling.json", "serve"
      ]
    }
  }
}
```

The command also checks whether Ollama is running and `bge-m3` is available.

Both files contain machine-specific absolute paths, so add them to `.gitignore`:

```
ragling.json
.mcp.json
```

### Options

| Flag | Description |
|------|-------------|
| `--name NAME` | Override the project name (defaults to directory name) |
| `--ragling-dir PATH` | Override the ragling installation path (auto-detected) |

## Manual Setup

If you prefer to create the files by hand:

1. Create `ragling.json` in your project root:
   ```json
   {
     "watch": {
       "my-project": "."
     }
   }
   ```

2. Create or update `.mcp.json` in your project root:
   ```json
   {
     "mcpServers": {
       "ragling": {
         "command": "uv",
         "args": [
           "run", "--directory", "/path/to/ragling",
           "ragling", "--config", "/path/to/my-project/ragling.json", "serve"
         ]
       }
     }
   }
   ```

Replace `/path/to/ragling` with your ragling clone location and `/path/to/my-project` with the absolute path to your project.

## What Happens Next

When the MCP server starts (e.g., when Claude Code opens your project):

1. ragling reads `ragling.json` and discovers your watched directory
2. It scans the directory and auto-detects content types:
   - `.git/` present → indexes code (tree-sitter, 17 languages) + commit history + documents
   - `.obsidian/` present → indexes as an Obsidian vault (frontmatter, wikilinks, tags)
   - Otherwise → indexes all supported document types
3. Files are indexed incrementally — only new or changed files are processed
4. A file watcher keeps the index current as you work

Search is available immediately, even while initial indexing is in progress.

## Supported File Types

Within watched directories, ragling indexes:

| Category | Extensions |
|----------|-----------|
| Documents | `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.txt`, `.epub` |
| Code | `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.c`, `.cpp`, `.rb`, `.swift`, and more (17 languages) |
| Data | `.csv`, `.json`, `.yaml` |
| Images in PDFs | Described via SmolVLM for searchable text |

## CLI Usage

With `ragling.json` in your project, you can also use the CLI directly:

```bash
cd my-project
uv run --directory ~/ragling ragling search "authentication flow"
uv run --directory ~/ragling ragling collections list
```

ragling auto-discovers `ragling.json` in the current directory, so no `--config` flag is needed for CLI commands.
