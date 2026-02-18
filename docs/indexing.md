# Indexing Sources

ragling indexes personal knowledge from six source types. All index commands detect changes automatically and skip unchanged files. Use `--force` to re-index everything.

## Obsidian

Indexes all files in your vault — markdown, PDF, DOCX, PPTX, images, and more.

```bash
uv run ragling index obsidian                              # paths from config
uv run ragling index obsidian --vault ~/Documents/MyVault  # explicit path
```

## eM Client

Reads the eM Client SQLite database (read-only). Indexes subject, body, sender, recipients, date, and folder.

```bash
uv run ragling index email
```

## Calibre

Indexes ebook content (EPUB, PDF) and metadata (author, tags, series) from your Calibre library.

```bash
uv run ragling index calibre                               # paths from config
uv run ragling index calibre --library ~/CalibreLibrary    # explicit path
```

## NetNewsWire

Indexes RSS/Atom articles from NetNewsWire (read-only).

```bash
uv run ragling index rss
```

## Code Groups

Indexes git repositories grouped by org or topic. Uses tree-sitter for structural parsing of 11 languages. Optionally includes commit history.

```bash
uv run ragling index group my-org              # one group
uv run ragling index group                     # all groups from config
uv run ragling index group my-org --history    # code + commit history
```

Define code groups in your [config file](configuration.md):

```json
{
  "code_groups": {
    "my-org": ["~/Repository/my-org/repo1", "~/Repository/my-org/repo2"],
    "terraform": ["~/Repository/tf-infra", "~/Repository/tf-modules"]
  }
}
```

## Project Folders

Indexes any folder of documents into a named collection. Files are routed to the right parser by extension.

```bash
uv run ragling index project "Client X" ~/Documents/client-x-docs/
```

## Index Everything

```bash
uv run ragling index all
```

Runs all configured sources in sequence. Pair with [automatic indexing](automatic-indexing.md) to keep your index current.
