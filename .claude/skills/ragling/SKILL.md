---
name: ragling
description: Use when searching personal knowledge, querying indexed documents, emails, code, or ebooks, or when ragling MCP tools are available and you need patterns for effective search
---

# Ragling — MCP Tool Reference

## Overview

Ragling is a local RAG system providing hybrid vector + full-text search across personal knowledge. Six MCP tools are available. **Everything runs locally — no cloud APIs, no data leaves the machine.**

## Search Workflow

1. **Discover** — call `rag_list_collections` to see what's indexed
2. **Search broad** — call `rag_search` with just a query, no filters
3. **Narrow** — add `collection`, `source_type`, `sender`, `author`, or date filters if results are noisy
4. **Present** — include `source_uri` as markdown links so users can open originals

Never skip step 1 on first use. Never jump to filtered search without trying broad first.

## Score Interpretation

Scores are **relative within a single query**. A score of 0.032 vs 0.028 means the first ranks higher in this query. Do not compare scores across different queries — they are not on a comparable scale.

## Indexing Status

When `rag_search` returns `indexing: {"active": true, "remaining": N}`, results are from an incomplete index. Tell the user results may be incomplete and suggest trying again shortly.

## Tools Quick Reference

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `rag_search` | Hybrid search with RRF | `query`, `collection`, `source_type`, `sender`, `author`, `date_from`, `date_to`, `top_k` |
| `rag_list_collections` | Discover available collections | (none) |
| `rag_collection_info` | Details on one collection | `collection` |
| `rag_index` | Trigger indexing | `collection`, `path` (required for projects) |
| `rag_convert` | Convert document to markdown | `file_path` |
| `rag_doc_store_info` | List cached conversions | (none) |

For full parameter documentation, see @mcp-tools.md.

## Collection Filtering

The `collection` parameter accepts a **name** or a **type**:

- Name: `"obsidian"`, `"email"`, `"my-org"` — searches that specific collection
- Type: `"system"`, `"code"`, `"project"` — searches all collections of that type
- Omit: searches everything

Use `"code"` to search all code groups at once.

## Source URIs

| Source | URI Scheme | Opens in |
|--------|-----------|----------|
| Obsidian vault files | `obsidian://` | Obsidian app |
| Code files | `vscode://` | VS Code at correct line |
| Calibre books, project docs | `file://` | Default macOS app |
| RSS articles | `https://` | Browser |
| Email, git commits | `null` | Not openable |

Always include source URIs as markdown links in responses.

## Common Patterns

```python
# Broad search — start here
rag_search(query="kubernetes deployment strategy")

# Filter by collection type
rag_search(query="auth middleware", collection="code")

# Combine email filters
rag_search(query="invoice", sender="john", date_from="2026-01-01")

# Specific collection + source type
rag_search(query="tax return", collection="obsidian", source_type="pdf")

# Book by author
rag_search(query="machine learning", author="Bishop")

# Commit history
rag_search(query="refactored auth", collection="my-org", source_type="commit")

# Full document read (not search)
rag_convert(file_path="/path/to/document.pdf")
```

## Best Practices

- **Start broad, then narrow.** Search without filters first. Add filters only if results are noisy.
- **Natural language for meaning.** "how to handle errors in Go" beats "error handling Go".
- **Keywords for exact matches.** Function names, error messages, specific phrases.
- **Check collections first.** Call `rag_list_collections` before assuming what exists.
- **Use `rag_convert` for full reads.** When you need the complete text of a specific file, use `rag_convert` instead of `rag_search`.
- **Link sources.** Always include `source_uri` as a markdown link in your response.
