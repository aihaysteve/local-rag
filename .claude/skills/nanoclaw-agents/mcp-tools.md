# MCP Tools — Full Reference

## rag_search

Hybrid vector + full-text search with Reciprocal Rank Fusion.

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

**Returns:** `{ results: [...], indexing: { active: bool, remaining: int } | null }`

Each result: `title`, `content`, `collection`, `source_type`, `source_path`, `source_uri`, `score`, `metadata`.

### Collection Types

| Type | Collections | Source Types | Key Metadata |
|------|-------------|--------------|--------------|
| **system** | `obsidian`, `email`, `calibre`, `rss` | markdown, pdf, docx, epub, html, txt, email, rss | tags, sender, authors, feed_name |
| **code** | Named groups (e.g., `my-org`) | code, commit | language, symbol_name, commit_sha |
| **project** | User-created names | Varies | Depends on file types |

### Metadata by Source Type

- **markdown**: `tags`, `heading_path`
- **email**: `sender`, `recipients`, `date`, `folder`
- **calibre**: `authors`, `tags`, `series`, `publisher`, `page_number`
- **rss**: `feed_name`, `url`, `date`
- **code**: `language`, `symbol_name`, `symbol_type`, `start_line`
- **commit**: `commit_sha`, `commit_sha_short`, `author_name`, `author_email`, `author_date`, `commit_message`, `file_path`, `additions`, `deletions`

## rag_convert

Convert a document file to markdown text. Cached — same file twice is instant.

| Parameter | Type | Description |
|-----------|------|-------------|
| `file_path` | str | Path to the document file |

**Supported:** PDF, DOCX, PPTX, XLSX, HTML, EPUB, images, LaTeX, CSV, Markdown, plain text.

## rag_list_collections

List all available collections. No parameters.

**Returns:** List of `{ name, type, description, source_count, chunk_count, last_indexed, created_at }`.

## rag_collection_info

Detailed information about a specific collection.

| Parameter | Type | Description |
|-----------|------|-------------|
| `collection` | str | Collection name |

**Returns:** `{ name, type, description, created_at, source_count, chunk_count, last_indexed, source_types, sample_titles }`.

## rag_index

Trigger indexing for a collection.

| Parameter | Type | Description |
|-----------|------|-------------|
| `collection` | str | Collection name |
| `path` | str \| null | Required for project collections |

- System collections (`obsidian`, `email`, `calibre`, `rss`): use configured paths.
- Code groups: indexes all repos in the group.
- Projects: `path` is required.

**Returns:** `{ collection, indexed, skipped, errors, total_found }`.

## rag_doc_store_info

List all documents in the shared conversion cache. No parameters.

**Returns:** List of `{ source_path, content_hash, file_size, file_modified_at, discovered_at }`.
