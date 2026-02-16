# RAGLING.md

Ragling is a local RAG system for searching personal knowledge. It indexes documents, code, emails, ebooks, and RSS feeds into a hybrid vector + full-text search engine. Everything runs locally -- no cloud APIs, no data leaves the machine.

Use ragling when you need to find information across the user's personal knowledge base: notes, emails, codebases, books, or project documents.

---

## MCP Tools

### rag_search

Hybrid vector + full-text search with Reciprocal Rank Fusion. This is the primary tool.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | required | Natural language question or keywords |
| `collection` | str \| null | null | Collection name or type filter (see below) |
| `top_k` | int | 10 | Number of results to return |
| `source_type` | str \| null | null | Filter: `markdown`, `pdf`, `docx`, `epub`, `html`, `txt`, `email`, `code`, `commit`, `rss` |
| `date_from` | str \| null | null | Only results after this date (YYYY-MM-DD) |
| `date_to` | str \| null | null | Only results before this date (YYYY-MM-DD) |
| `sender` | str \| null | null | Email sender filter (case-insensitive substring) |
| `author` | str \| null | null | Book author filter (case-insensitive substring) |

**Returns:** Dict with two keys:
- `results`: List of result dicts, each with: `title`, `content`, `collection`, `source_type`, `source_path`, `source_uri`, `score`, `metadata`.
- `indexing`: `{"active": true, "remaining": N}` while startup indexing is in progress, or `null` when idle. Use this to inform the user that results may be incomplete.

**Collection filtering:** The `collection` parameter accepts either:
- A collection **name** (e.g., `"obsidian"`, `"email"`, `"my-terraform"`) -- searches that specific collection.
- A collection **type** (`"system"`, `"project"`, `"code"`) -- searches all collections of that type.
- Omit to search everything.

### rag_convert

Convert a document file to markdown text. Useful for reading PDFs, DOCX, PPTX, etc. inline.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `file_path` | str | Path to the document file |

**Returns:** Markdown text content of the document.

**Supported formats:** PDF, DOCX, PPTX, XLSX, HTML, EPUB, images (PNG, JPG, TIFF), LaTeX, CSV, Markdown, plain text.

Results are cached in the shared document store -- converting the same file twice is instant.

### rag_list_collections

List all available collections with counts and metadata. Takes no parameters.

**Returns:** List of dicts, each with: `name`, `type`, `description`, `source_count`, `chunk_count`, `last_indexed`, `created_at`.

Use this to discover what collections exist before searching.

### rag_collection_info

Get detailed information about a specific collection.

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

List all documents in the shared Docling conversion cache. Takes no parameters.

**Returns:** List of dicts, each with: `source_path`, `content_hash`, `file_size`, `file_modified_at`, `discovered_at`.

Useful for checking what has been converted and cached.

---

## Collection Types

| Type | Collections | Source Types | Key Metadata |
|------|-------------|--------------|--------------|
| **system** | `obsidian`, `email`, `calibre`, `rss` | markdown, pdf, docx, epub, html, txt, email, rss | tags, sender, authors, feed_name |
| **code** | Named groups (e.g., `my-org`, `terraform`) | code, commit | language, symbol_name, commit_sha, author_name |
| **project** | User-created names | Varies by content | Depends on file types |

---

## Search Examples

```python
# Search everything
rag_search(query="kubernetes deployment strategy")

# Search a specific collection
rag_search(query="authentication middleware", collection="my-org")

# Search all code groups at once
rag_search(query="database connection pool", collection="code")

# Search all system collections
rag_search(query="meeting notes", collection="system")

# Filter by source type
rag_search(query="tax return", collection="obsidian", source_type="pdf")

# Search emails from a specific sender
rag_search(query="invoice", sender="john@example.com")

# Search emails within a date range
rag_search(query="project update", sender="boss", date_from="2025-01-01")

# Search books by author
rag_search(query="machine learning", author="Bishop")

# Search commit history
rag_search(query="refactored auth", collection="my-org", source_type="commit")

# Search RSS articles
rag_search(query="AI regulation", collection="rss", date_from="2025-06-01")

# Get more results
rag_search(query="error handling patterns", collection="code", top_k=20)
```

---

## Interpreting Results

### Scores

Results are ranked by RRF score (higher is better). Scores are relative within a single query -- do not compare scores across different queries.

### Source URIs

Each result includes a `source_uri` for linking back to the original:

| Source | URI Scheme | Example |
|--------|-----------|---------|
| Obsidian vault files | `obsidian://` | `obsidian://open?vault=MyVault&file=notes/report.md` |
| Code files | `vscode://` | `vscode://file/path/to/src/main.py:42` |
| Calibre books, project docs | `file://` | `file:///Users/you/CalibreLibrary/book.epub` |
| RSS articles | `https://` | Original article URL |
| Email, git commits | `null` | No openable URI |

When presenting results, include `source_uri` as a markdown link so the user can open the original document.

### Metadata

The `metadata` dict varies by source type. Not all fields are present in every result; missing fields are null.

- **markdown**: `tags`, `heading_path`
- **email**: `sender`, `recipients`, `date`, `folder`
- **calibre**: `authors`, `tags`, `series`, `publisher`, `page_number`
- **rss**: `feed_name`, `url`, `date`
- **code**: `language`, `symbol_name`, `symbol_type`, `start_line`
- **commit**: `commit_sha`, `commit_sha_short`, `author_name`, `author_email`, `author_date`, `commit_message`, `file_path`, `additions`, `deletions`

---

## SSE Authentication

When ragling is served over SSE (HTTP), requests require a Bearer token matching a configured user's API key. Include it as:

```
Authorization: Bearer <api_key>
```

Each user's API key is configured in `config.json` under `users.<username>.api_key`. The token determines which collections the user can see -- users only see their own collection and global collections.

When served over stdio (e.g., Claude Desktop), no authentication is needed.

---

## Best Practices

- **Start broad, then narrow.** Search without filters first. Add `collection`, `source_type`, or date filters if results are too noisy.
- **Use natural language for semantic queries.** The vector search understands meaning: "how to handle errors in Go" works better than "error handling Go".
- **Use keywords for exact matches.** The full-text search finds exact phrases: searching for a specific function name or error message works well.
- **Combine filters.** Use `sender` + `date_from` for targeted email search. Use `collection` + `source_type="commit"` for git history.
- **Check collection existence first.** Call `rag_list_collections` if unsure what collections are available.
- **Use `rag_convert` for one-off document reading.** When you need the full text of a specific file (not search), use `rag_convert` instead of `rag_search`.
- **Link to sources.** Include `source_uri` as a markdown link in your response so users can open the original document.
- **Check indexing status.** If `rag_search` returns `"indexing": {"active": true, ...}`, mention to the user that indexing is in progress and results may be incomplete. Suggest trying again shortly if results seem sparse.
