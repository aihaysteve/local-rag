# CLI Reference

## Indexing

```
ragling index obsidian [--vault PATH] [--force]      Index Obsidian vault(s)
ragling index email [--force]                        Index eM Client emails
ragling index calibre [--library PATH] [--force]     Index Calibre ebook libraries
ragling index rss [--force]                          Index NetNewsWire RSS articles
ragling index group [NAME] [--history] [--force]     Index code group(s)
ragling index project NAME PATH... [--force]         Index docs into a project
ragling index all [--force]                          Index all configured sources
```

See [Indexing Sources](indexing.md) for detailed examples.

## Searching

```
ragling search QUERY [options]                       Hybrid search across collections
  --collection NAME                                  Search specific collection
  --type TYPE                                        Filter by source type
  --author TEXT                                      Filter by book author
  --after DATE                                       Results after this date
  --before DATE                                      Results before this date
  --top N                                            Number of results (default: 10)
```

## Collections

```
ragling collections list                             List all collections
ragling collections info NAME                        Detailed collection info
ragling collections delete NAME                      Delete a collection
```

## Server

```
ragling serve [--sse] [--port PORT] [--no-stdio]     Start MCP server
ragling mcp-config [--port PORT]                     Output MCP client config JSON
ragling status                                       Show database stats
```

## Global Options

```
--verbose / -v          Verbose output
--group / -g NAME       Select group
--config / -c PATH      Config file path
```
