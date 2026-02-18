# Configuration

ragling works without a config file — pass paths on the command line. Create a config file when you want to set permanent defaults.

## Config File Location

```
~/.ragling/config.json
```

Copy the example to get started:

```bash
mkdir -p ~/.ragling
cp config.example.json ~/.ragling/config.json
```

Edit the file to match your setup. See [config.example.json](../config.example.json) for all options.

## Settings Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `obsidian_vaults` | `[]` | Paths to Obsidian vaults |
| `obsidian_exclude_folders` | `[]` | Folders to skip within vaults |
| `emclient_db_path` | auto-detected | Path to eM Client data directory |
| `calibre_libraries` | `[]` | Paths to Calibre libraries |
| `netnewswire_db_path` | auto-detected | Path to NetNewsWire data directory |
| `code_groups` | `{}` | Map of group name → list of git repo paths |
| `disabled_collections` | `[]` | Collections to skip during indexing |
| `git_history_in_months` | `6` | How far back to index commit history |
| `embedding_model` | `"bge-m3"` | Ollama embedding model |
| `embedding_dimensions` | `1024` | Vector dimensions (must match model) |
| `chunk_size_tokens` | `256` | Maximum tokens per chunk |
| `db_path` | `"~/.ragling/rag.db"` | Database path |
| `shared_db_path` | `"~/.ragling/doc_store.sqlite"` | Shared document conversion cache |

## Search Tuning

```json
{
  "search_defaults": {
    "top_k": 10,
    "rrf_k": 60,
    "vector_weight": 0.7,
    "fts_weight": 0.3
  }
}
```

See [Hybrid Search and RRF](hybrid-search-and-rrf.md) for details on these parameters.

## Disabling Collections

Skip a collection during indexing without deleting its data:

```json
{
  "disabled_collections": ["email", "rss"]
}
```
