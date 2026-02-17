---
name: nanoclaw-agents
description: Use when a NanoClaw channel agent needs to search knowledge, query documents, or understand what RAG capabilities are available within its channel
---

# NanoClaw Agent — Ragling Reference

## Overview

Ragling is a local RAG system running on the host. You connect over SSE with your API key. Use it to search your group's documents, shared global content, and configured system collections.

## What You Can See

Visibility is scoped by your user config:

1. **Your group directory** — everything indexed under your username's collection
2. **Global content** — shared paths visible to all users
3. **System collections** — only the ones in your `system_collections` config (`obsidian`, `email`, `calibre`, `rss`)

You cannot see other users' group content. Queries against inaccessible collections return zero results (no error).

## Path Mappings

Paths are automatically translated between host and container. This is transparent:

- **Search results**: `source_path` and `source_uri` use container paths
- **Document conversion**: pass container paths to `rag_convert`; ragling translates automatically
- **URI schemes**: `file://` and `vscode://` URIs are mapped; `obsidian://` and `https://` pass through unchanged

**Use paths as they appear in your container. Never translate them yourself.**

## Search Workflow

1. **Discover** — call `rag_list_collections` to see what's available to you
2. **Search broad** — call `rag_search` with just a query, no filters
3. **Narrow** — add `collection`, `source_type`, `sender`, `author`, or date filters
4. **Present** — include `source_uri` as markdown links

## Tools Quick Reference

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `rag_search` | Hybrid search with RRF | `query`, `collection`, `source_type`, `sender`, `author`, `date_from`, `date_to`, `top_k` |
| `rag_list_collections` | Discover available collections | (none) |
| `rag_collection_info` | Details on one collection | `collection` |
| `rag_index` | Trigger indexing | `collection`, `path` (required for projects) |
| `rag_convert` | Convert document to markdown | `file_path` (use container path) |
| `rag_doc_store_info` | List cached conversions | (none) |

For full parameter documentation, see @mcp-tools.md.

## Collection Filtering

The `collection` parameter accepts a **name** or a **type**:

- Name: `"obsidian"`, `"my-project"` — searches that specific collection
- Type: `"system"`, `"code"`, `"project"` — searches all of that type
- Omit: searches everything you can see

## Score Interpretation

Scores are **relative within a single query**. Do not compare scores across different queries.

## Indexing Status

When `rag_search` returns `indexing: {"active": true, "remaining": N}`, results are from an incomplete index. Tell the user and suggest trying again shortly.

## Common Patterns

```python
# Search everything you can see
rag_search(query="deployment strategy")

# Search code
rag_search(query="auth middleware", collection="code")

# Search PDFs
rag_search(query="company policy", source_type="pdf")

# Search emails from a sender
rag_search(query="invoice", sender="supplier@example.com")

# Date range
rag_search(query="quarterly report", date_from="2025-01-01", date_to="2025-03-31")

# Full document read (use container path)
rag_convert(file_path="/workspace/group/docs/report.pdf")
```

## Source URIs

| Source | URI Scheme | Opens in |
|--------|-----------|----------|
| Obsidian vault files | `obsidian://` | Obsidian app |
| Code files | `vscode://` | VS Code at correct line |
| Calibre books, project docs | `file://` | Default app |
| RSS articles | `https://` | Browser |
| Email, git commits | `null` | Not openable |

Always include source URIs as markdown links in responses.

## Metadata by Source Type

| Source Type | Fields |
|-------------|--------|
| `markdown` | `tags`, `heading_path` |
| `email` | `sender`, `recipients`, `date`, `folder` |
| `calibre` | `authors`, `tags`, `series`, `publisher`, `page_number` |
| `rss` | `feed_name`, `url`, `date` |
| `code` | `language`, `symbol_name`, `symbol_type`, `start_line` |
| `commit` | `commit_sha`, `commit_sha_short`, `author_name`, `author_email`, `author_date`, `commit_message`, `file_path`, `additions`, `deletions` |

## Best Practices

- **Start broad, then narrow.** No filters first, then add them.
- **Natural language for meaning.** "how to handle errors in Go" beats "error handling Go".
- **Keywords for exact matches.** Function names, error messages, specific phrases.
- **Check collections first.** Call `rag_list_collections` before assuming.
- **Use `rag_convert` for full reads.** Complete text of a specific file, not search.
- **Link sources.** Always include `source_uri` in your response.
- **Report indexing status.** If active, tell the user results may be incomplete.
