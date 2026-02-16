# NANOCLAW-agents.md -- Ragling Agent Reference

Ragling is a local RAG system running on the host machine. You connect to it
over SSE using your API key. Use it to search across your group's documents,
shared global content, and any system collections your user is configured to access.

---

## Available MCP Tools

### rag_search

Primary search tool. Hybrid vector + full-text search with Reciprocal Rank Fusion.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | required | Natural language question or keywords |
| `collection` | str \| null | null | Collection name or type filter |
| `top_k` | int | 10 | Number of results to return |
| `source_type` | str \| null | null | Filter: `markdown`, `pdf`, `docx`, `epub`, `html`, `txt`, `email`, `code`, `commit`, `rss` |
| `date_from` | str \| null | null | Only results after this date (YYYY-MM-DD) |
| `date_to` | str \| null | null | Only results before this date (YYYY-MM-DD) |
| `sender` | str \| null | null | Email sender filter (case-insensitive substring) |
| `author` | str \| null | null | Book author filter (case-insensitive substring) |

**Returns:** Dict with two keys:
- `results`: List of result dicts, each with: `title`, `content`, `collection`, `source_type`, `source_path`, `source_uri`, `score`, `metadata`.
- `indexing`: `{"active": true, "remaining": N}` while startup indexing is in progress, or `null` when idle.

**Collection filtering:**
- Name (e.g., `"obsidian"`, `"my-project"`) -- searches that specific collection.
- Type (`"system"`, `"project"`, `"code"`) -- searches all collections of that type.
- Omit -- searches everything you can see.

### rag_convert

Convert a document to markdown text. Use your container paths -- path mapping is automatic.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `file_path` | str | Path to the document (use your container path) |

**Returns:** Markdown text content of the document.

Cached. Same file twice = instant.

**Supported formats:** PDF, DOCX, PPTX, XLSX, HTML, EPUB, images (PNG, JPG, TIFF), LaTeX, CSV, Markdown, plain text.

### rag_list_collections

List all collections you can see. No parameters.

**Returns:** List of dicts, each with: `name`, `type`, `description`, `source_count`, `chunk_count`, `last_indexed`, `created_at`.

### rag_collection_info

Detailed info about a specific collection.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `collection` | str | Collection name |

**Returns:** Dict with: `name`, `type`, `description`, `created_at`, `source_count`, `chunk_count`, `last_indexed`, `source_types` (breakdown by type), `sample_titles`.

### rag_index

Trigger indexing for a collection.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `collection` | str | Collection name |
| `path` | str \| null | Required for project collections; optional for adding a repo to a code group |

**Returns:** Dict with: `collection`, `indexed`, `skipped`, `errors`, `total_found`. Returns `{"error": "..."}` for unknown or disabled collections.

- System collections (`obsidian`, `email`, `calibre`, `rss`): use configured paths, no `path` needed.
- Code groups: indexes all repos in the group.
- Projects: `path` is required.

### rag_doc_store_info

List the shared document conversion cache. No parameters.

**Returns:** List of dicts, each with: `source_path`, `content_hash`, `file_size`, `file_modified_at`, `discovered_at`.

---

## What You Can See

Visibility is scoped by your user config:

1. **Your group directory** -- everything indexed under your username's collection.
2. **Global content** -- shared paths visible to all users (if configured).
3. **System collections** -- `obsidian`, `email`, `calibre`, `rss` -- only the ones listed in your `system_collections` config.

You cannot see other users' group content. Queries against collections you lack access to return zero results (no error).

---

## Path Mappings

Paths in results use container paths, not host paths. This is transparent:

- **Search results:** Host paths are mapped to container paths in `source_path` and `source_uri` before you see them.
- **Document conversion:** You pass container paths to `rag_convert`; ragling translates them to host paths automatically.
- **URI schemes:** `file://` and `vscode://` URIs are mapped. `obsidian://` and `https://` URIs pass through unchanged.

Use paths as they appear in your container. Never try to translate them yourself.

---

## Indexing Status

When startup sync is running, search responses include:

```json
{"indexing": {"active": true, "remaining": 42}}
```

Tell the user indexing is in progress and results may be incomplete. Suggest trying again shortly if results seem sparse.

When idle, `indexing` is `null`.

---

## Search Patterns

```python
# Search everything
rag_search(query="deployment strategy")

# Search code
rag_search(query="auth middleware", collection="code")

# Search PDFs
rag_search(query="company policy", source_type="pdf")

# Search Obsidian
rag_search(query="meeting notes", collection="obsidian")

# Search emails from a sender
rag_search(query="invoice", sender="supplier@example.com")

# Date range
rag_search(query="quarterly report", date_from="2025-01-01", date_to="2025-03-31")

# Commit history
rag_search(query="refactored auth", source_type="commit")

# More results
rag_search(query="error handling", top_k=20)
```

---

## Best Practices

- **Start broad, then narrow.** Search without filters first. Add `collection`, `source_type`, or date filters if results are too noisy.
- **Natural language for semantic queries.** The vector search understands meaning: "how to handle errors in Go" works better than "error handling Go".
- **Keywords for exact matches.** The full-text search finds exact phrases: searching for a specific function name or error message works well.
- **Check collections first.** Call `rag_list_collections` if you are unsure what is available.
- **Use `rag_convert` for full documents.** When you need the entire text of a specific file (not search), use `rag_convert` instead of `rag_search`.
- **Link to sources.** Include `source_uri` as a markdown link in your response so the user can open the original document.
- **Check indexing status.** If `indexing` is active in search responses, mention to the user that results may be incomplete.

---

## Source URIs

Each search result includes a `source_uri` for linking back to the original:

| Source | URI Scheme | Example |
|--------|-----------|---------|
| Obsidian vault files | `obsidian://` | `obsidian://open?vault=MyVault&file=notes/report.md` |
| Code files | `vscode://` | `vscode://file/path/to/src/main.py:42` |
| Calibre books, project docs | `file://` | `file:///data/CalibreLibrary/book.epub` |
| RSS articles | `https://` | Original article URL |
| Email, git commits | `null` | No openable URI |

Present these as markdown links when showing results to the user.

---

## Metadata by Source Type

The `metadata` dict in each result varies by source type. Not all fields are present in every result.

| Source Type | Metadata Fields |
|-------------|----------------|
| `markdown` | `tags`, `heading_path` |
| `email` | `sender`, `recipients`, `date`, `folder` |
| `calibre` | `authors`, `tags`, `series`, `publisher`, `page_number` |
| `rss` | `feed_name`, `url`, `date` |
| `code` | `language`, `symbol_name`, `symbol_type`, `start_line` |
| `commit` | `commit_sha`, `commit_sha_short`, `author_name`, `author_email`, `author_date`, `commit_message`, `file_path`, `additions`, `deletions` |
