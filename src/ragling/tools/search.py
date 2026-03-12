"""MCP tool: rag_search — hybrid vector + full-text search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_search tool."""

    @mcp.tool()
    def rag_search(
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        source_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sender: str | None = None,
        author: str | None = None,
        subsystem: str | None = None,
        section_type: str | None = None,
        rerank: bool = True,
        min_score: float | None = None,
    ) -> dict[str, Any]:
        """Search personal knowledge using hybrid vector + full-text search with Reciprocal Rank Fusion.

        Searches across all indexed collections by default. Combines semantic similarity
        (understands meaning) with keyword matching (finds exact phrases) for best results.

        ## Collections and their metadata

        **obsidian** (system) — Obsidian vault notes and attachments.
          Source types: markdown, pdf, docx, epub, html, txt.
          Metadata: tags, heading_path.
          Useful filters: source_type, date_from/date_to.

        **email** (system) — eM Client emails.
          Source types: email.
          Metadata: sender, recipients, date, folder.
          Useful filters: sender, date_from/date_to.

        **calibre** (system) — Calibre ebook library.
          Source types: pdf, epub.
          Metadata: authors, tags, series, publisher, page_number.
          Useful filters: author, date_from/date_to.

        **rss** (system) — NetNewsWire RSS articles.
          Source types: rss.
          Metadata: feed_name, url, date.
          Useful filters: date_from/date_to.

        **Code groups** (code) — Groups of git repos indexed together by topic or org.
          Each group is a collection containing code from one or more repos.
          Source types: code, commit.
          Code metadata: language, symbol_name, symbol_type, start_line.
          Commit metadata: commit_sha, commit_sha_short, author_name, author_email,
            author_date, commit_message, file_path, additions, deletions.
          Useful filters: collection=<group-name>, source_type=commit, or collection=code for all.

        **Project folders** (project) — User-created document collections.
          Source types: vary by content (markdown, pdf, docx, etc.).
          Useful filters: collection=<project-name>.

        **Watch directories** — Auto-detected collections from configured directories.
          Each directory is indexed as code or project based on its contents.
          Source types: depend on auto-detection (code or project types).
          Useful filters: collection=<watch-name>.

        **SPEC.md subsystems** — Structured subsystem specifications extracted from SPEC.md files
          found in code repositories and project directories.
          Source types: spec.
          Metadata: subsystem, repo.
          Useful filters: source_type=spec for SPEC.md subsystem specifications.

        ## Collection filtering

        The ``collection`` parameter accepts either a collection name or a collection type:
        - Name (e.g., "obsidian", "email", "my-project") — searches that specific collection.
        - Type ("system", "project", "code") — searches all collections of that type.
          Use "code" to search across all code groups at once.

        ## Source URIs

        Each result includes a ``source_uri`` field with a clickable link to the original source
        when available. Use these to let the user open or navigate to the original document.

        - **Obsidian vault files** (markdown, PDFs, etc. inside a vault):
          Returns an ``obsidian://open?vault=...&file=...`` URI that opens the note directly
          in the Obsidian app. Example: ``obsidian://open?vault=MyVault&file=notes/report.md``.
        - **Code files** (from code groups):
          Returns a ``vscode://file/...`` URI that opens the file in VS Code at the correct line.
          Example: ``vscode://file/Users/you/repos/project/src/main.py:42``.
        - **Other file-based sources** (calibre books, project docs):
          Returns a ``file://`` URI, e.g. ``file:///Users/you/CalibreLibrary/book.epub``.
          These open the file in the default macOS application (Preview for PDFs, editor for code, etc.).
        - **RSS articles**: Returns the original article ``https://`` URL from metadata.
          Opens the article in the default browser.
        - **Email and git commits**: Returns ``null`` — no meaningful URI is available for these.
        - **Calibre description-only entries**: Returns ``null`` — no actual file exists.

        When presenting results to the user, include the ``source_uri`` as a markdown link so
        the user can click to open the original. Example:
          [Open in Obsidian](obsidian://open?vault=MyVault&file=notes/report.md)
          [Open PDF](file:///Users/you/CalibreLibrary/Author/book.pdf)
          [Read article](https://example.com/article)

        ## Examples

        - Search everything: query="kubernetes deployment strategy"
        - Search emails from someone: query="invoice", sender="john@example.com"
        - Search a code group: query="authentication middleware", collection="rustyquill"
        - Search all code groups: query="database connection pool", collection="code"
        - Search cross-cutting group: query="module structure", collection="terraform"
        - Search books by author: query="machine learning", author="Bishop"
        - Search PDFs in Obsidian: query="tax return", collection="obsidian", source_type="pdf"
        - Search recent emails: query="project update", sender="boss", date_from="2025-01-01"
        - Search RSS articles: query="AI regulation", collection="rss", date_from="2025-06-01"
        - Search commit history: query="refactored auth", collection="rustyquill", source_type="commit"

        Args:
            query: The search query text. Can be a natural language question or keywords.
            collection: Filter by collection name (e.g., 'obsidian', 'email', 'my-project')
                or collection type ('system', 'project', 'code'). Omit to search everything.
            top_k: Number of results to return (default 10).
            source_type: Filter by source type: 'markdown', 'pdf', 'docx', 'epub', 'html',
                'txt', 'email', 'code', 'commit', 'rss', 'spec'.
            date_from: Only results after this date (YYYY-MM-DD).
            date_to: Only results before this date (YYYY-MM-DD).
            sender: Filter by email sender (case-insensitive substring match).
            author: Filter by book author (case-insensitive substring match).
            subsystem: Filter by SPEC.md subsystem name (case-insensitive exact match).
                Use with source_type="spec" to retrieve specs for a specific subsystem.
            section_type: Filter by SPEC.md section type (e.g., 'decision_framework',
                'invariants', 'public_interface'). Use with source_type="spec".
            rerank: Whether to apply cross-encoder rescoring (default True).
                Set to False to skip reranking and use raw RRF scores.
            min_score: Minimum score threshold for results. Only results with
                a score >= this value are returned. None means no threshold.

        Returns:
            Dict with ``results`` (list of matched chunks, each with title, content,
            collection, source_type, source_path, source_uri, score, and metadata),
            ``reranked`` (bool, whether cross-encoder rescoring was applied),
            and optional ``indexing_status`` when background indexing is active.
        """
        import time

        from ragling.config import load_config
        from ragling.embeddings import OllamaConnectionError
        from ragling.search.search import perform_search
        from ragling.tools.helpers import (
            _apply_user_context_to_results,
            _build_search_response,
            _get_user_context,
            _get_visible_collections,
            _result_to_dict,
        )

        visible = _get_visible_collections(ctx.server_config)
        user_ctx = _get_user_context(ctx.server_config)

        t0 = time.monotonic()
        try:
            results, reranked = perform_search(
                query=query,
                collection=collection,
                top_k=top_k,
                source_type=source_type,
                date_from=date_from,
                date_to=date_to,
                sender=sender,
                author=author,
                subsystem=subsystem,
                section_type=section_type,
                group_name=ctx.group_name,
                config=ctx.server_config,
                visible_collections=visible,
                rerank=rerank,
                min_score=min_score,
            )
        except OllamaConnectionError as e:
            return _build_search_response([{"error": str(e)}], ctx.indexing_status)

        obsidian_vaults = (ctx.server_config or load_config()).obsidian_vaults

        result_dicts = [_result_to_dict(r, obsidian_vaults) for r in results]

        # Log query for ACE telemetry
        cfg = ctx.get_config()
        if cfg.query_log_path:
            from ragling.query_logger import log_query

            duration_ms = (time.monotonic() - t0) * 1000
            log_query(
                log_path=cfg.query_log_path,
                query=query,
                filters={
                    "collection": collection,
                    "source_type": source_type,
                    "date_from": date_from,
                    "date_to": date_to,
                    "sender": sender,
                    "author": author,
                    "subsystem": subsystem,
                    "section_type": section_type,
                },
                top_k=top_k,
                results=result_dicts,
                duration_ms=duration_ms,
            )

        # Apply path mappings for SSE users
        if user_ctx:
            result_dicts = _apply_user_context_to_results(result_dicts, user_ctx)

        return _build_search_response(result_dicts, ctx.indexing_status, reranked=reranked)
