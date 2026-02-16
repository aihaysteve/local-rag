"""MCP server exposing ragling search and index tools."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP

from ragling.auth import UserContext
from ragling.config import Config, load_config
from ragling.db import get_connection, init_db

if TYPE_CHECKING:
    from ragling.indexing_status import IndexingStatus

logger = logging.getLogger(__name__)


def _build_source_uri(
    source_path: str,
    source_type: str,
    metadata: dict,
    collection: str,
    obsidian_vaults: list | None = None,
) -> str | None:
    """Build a clickable URI for a search result's original source.

    Returns an obsidian://, vscode://, file://, https://, or None depending on the source:
    - Obsidian vault files: obsidian://open URI (opens directly in Obsidian app)
    - Code files: vscode://file URI (opens in VS Code at the correct line)
    - Other file-based sources (calibre, project): file:// URI
    - RSS articles: https:// URL from metadata
    - Email and git commits: None (no meaningful URI available)

    Args:
        source_path: The source_path from the sources table.
        source_type: The source_type from the sources table.
        metadata: Parsed metadata dict from the documents table.
        collection: The collection name the result belongs to.
        obsidian_vaults: List of configured Obsidian vault paths (needed
            to construct obsidian:// URIs).

    Returns:
        A URI string or None if no meaningful link can be constructed.
    """
    # RSS articles have a web URL in metadata
    if source_type == "rss":
        return metadata.get("url") or None

    # Email messages and git commits have no openable URI
    if source_type in ("email", "commit"):
        return None

    # Virtual paths (calibre description-only, git commit refs) are not openable
    if source_path.startswith(("calibre://", "git://")):
        return None

    # Obsidian vault files — use obsidian:// URI to open in the app
    if collection == "obsidian" and obsidian_vaults:
        obsidian_uri = _build_obsidian_uri(source_path, obsidian_vaults)
        if obsidian_uri:
            return obsidian_uri

    # Code files — use vscode:// URI to open in VS Code at the correct line
    if source_type == "code":
        start_line = metadata.get("start_line", 1)
        return f"vscode://file{quote(source_path, safe='/')}:{start_line}"

    # Everything else is a real file path — return as file:// URI
    return f"file://{quote(source_path, safe='/')}"


def _build_obsidian_uri(source_path: str, vault_paths: list) -> str | None:
    """Build an obsidian://open URI for a file inside an Obsidian vault.

    Matches the source_path against known vault paths to extract the vault
    name and the file path relative to the vault root.

    The URI format is: obsidian://open?vault=VAULT_NAME&file=RELATIVE/PATH

    Args:
        source_path: Absolute file path of the indexed document.
        vault_paths: List of configured Obsidian vault root paths.

    Returns:
        An obsidian:// URI string, or None if the path doesn't match any vault.
    """
    from pathlib import Path

    for vault_path in vault_paths:
        vault_str = str(Path(vault_path).expanduser().resolve())
        if source_path.startswith(vault_str + "/"):
            vault_name = Path(vault_str).name
            relative_path = source_path[len(vault_str) + 1 :]
            return (
                f"obsidian://open?vault={quote(vault_name, safe='')}"
                f"&file={quote(relative_path, safe='/')}"
            )
    return None


def _apply_user_context_to_results(
    results: list[dict[str, Any]], user_ctx: UserContext
) -> list[dict[str, Any]]:
    """Apply path mappings to search results for a user.

    Creates copies of each result dict with source_path and source_uri
    mapped through the user's path mappings.

    Args:
        results: List of search result dicts with source_path and source_uri keys.
        user_ctx: User context containing path mappings.

    Returns:
        New list of result dicts with mapped paths.
    """
    from ragling.path_mapping import apply_forward, apply_forward_uri

    mapped = []
    for r in results:
        r = dict(r)  # copy to avoid mutating the original
        r["source_path"] = apply_forward(r["source_path"], user_ctx.path_mappings)
        r["source_uri"] = apply_forward_uri(r.get("source_uri"), user_ctx.path_mappings)
        mapped.append(r)
    return mapped


def _build_search_response(
    results: list[dict[str, Any]],
    indexing_status: IndexingStatus | None = None,
) -> dict[str, Any]:
    """Build search response with optional indexing status.

    Args:
        results: List of search result dicts.
        indexing_status: Optional indexing status tracker.

    Returns:
        Response dict with 'results' and 'indexing' keys.
    """
    return {
        "results": results,
        "indexing": indexing_status.to_dict() if indexing_status else None,
    }


def _convert_document(file_path: str, path_mappings: dict[str, str]) -> str:
    """Convert a document to markdown text.

    Applies reverse path mapping if needed, then reads or converts the file.

    Args:
        file_path: Path to the file (may be a container path).
        path_mappings: Host->container mappings (reversed for lookup).

    Returns:
        Markdown text content, or error message.
    """
    from pathlib import Path as P

    from ragling.path_mapping import apply_reverse

    host_path = apply_reverse(file_path, path_mappings)
    resolved = P(host_path).expanduser().resolve()

    if not resolved.exists():
        return f"Error: File not found: {file_path}"

    # For markdown, just read directly
    if resolved.suffix.lower() == ".md":
        return resolved.read_text(encoding="utf-8", errors="replace")

    # For other formats, try Docling conversion via doc_store cache
    try:
        from ragling.doc_store import DocStore
        from ragling.docling_convert import convert_and_chunk

        config = load_config()
        doc_store = DocStore(config.shared_db_path)
        try:
            chunks = convert_and_chunk(resolved, doc_store)
            return "\n\n".join(c.text for c in chunks)
        finally:
            doc_store.close()
    except Exception as e:
        return f"Error converting {file_path}: {e}"


def _get_user_context(config: Config | None) -> UserContext | None:
    """Derive UserContext from the current request's access token.

    Uses the contextvar set by FastMCP's AuthContextMiddleware.
    Returns None when unauthenticated (stdio) or when the user is unknown.

    Args:
        config: Application config with users.

    Returns:
        UserContext if authenticated and user exists in config, None otherwise.
    """
    if config is None or not config.users:
        return None
    try:
        access_token = get_access_token()
    except Exception:
        return None
    if access_token is None:
        return None
    username = access_token.client_id
    user_config = config.users.get(username)
    if user_config is None:
        return None
    return UserContext(
        username=username,
        system_collections=user_config.system_collections,
        path_mappings=user_config.path_mappings,
    )


def create_server(
    group_name: str = "default",
    config: Config | None = None,
    indexing_status: IndexingStatus | None = None,
) -> FastMCP:
    """Create and configure the MCP server with all tools registered.

    Args:
        group_name: Group name for per-group indexes. Passed through to
            config so the correct database path is used.
        config: Optional pre-loaded Config. If None, tools will call
            load_config() on each invocation (backwards compatible).
        indexing_status: Optional IndexingStatus tracker for reporting
            indexing progress in search responses.
    """
    # Capture config for use inside tool closures. When provided, tools
    # use this instead of calling load_config() each time.
    server_config = config

    mcp_kwargs: dict[str, Any] = {
        "instructions": "Local RAG system for searching personal knowledge.",
    }

    # Set up auth when users are configured (enables SSE Bearer token validation)
    if server_config and server_config.users:
        from pydantic import AnyHttpUrl

        from mcp.server.auth.settings import AuthSettings

        from ragling.token_verifier import RaglingTokenVerifier

        mcp_kwargs["token_verifier"] = RaglingTokenVerifier(server_config)
        mcp_kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl(
                "http://localhost"
            ),  # Required placeholder; not used for simple bearer auth
            resource_server_url=None,
            required_scopes=[],
        )

    mcp = FastMCP("ragling", **mcp_kwargs)

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

        ## Collection filtering

        The `collection` parameter accepts either a collection name or a collection type:
        - Name (e.g., "obsidian", "email", "rustyquill", "terraform") — searches that specific collection.
        - Type ("system", "project", "code") — searches all collections of that type.
          Use "code" to search across all code groups at once.

        ## Source URIs

        Each result includes a `source_uri` field with a clickable link to the original source
        when available. Use these to let the user open or navigate to the original document.

        - **Obsidian vault files** (markdown, PDFs, etc. inside a vault):
          Returns an `obsidian://open?vault=...&file=...` URI that opens the note directly
          in the Obsidian app. Example: `obsidian://open?vault=MyVault&file=notes/report.md`.
        - **Code files** (from code groups):
          Returns a `vscode://file/...` URI that opens the file in VS Code at the correct line.
          Example: `vscode://file/Users/you/repos/project/src/main.py:42`.
        - **Other file-based sources** (calibre books, project docs):
          Returns a `file://` URI, e.g. `file:///Users/you/CalibreLibrary/book.epub`.
          These open the file in the default macOS application (Preview for PDFs, editor for code, etc.).
        - **RSS articles**: Returns the original article `https://` URL from metadata.
          Opens the article in the default browser.
        - **Email and git commits**: Returns `null` — no meaningful URI is available for these.
        - **Calibre description-only entries**: Returns `null` — no actual file exists.

        When presenting results to the user, include the `source_uri` as a markdown link so
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
                'txt', 'email', 'code', 'commit', 'rss'.
            date_from: Only results after this date (YYYY-MM-DD).
            date_to: Only results before this date (YYYY-MM-DD).
            sender: Filter by email sender (case-insensitive substring match).
            author: Filter by book author (case-insensitive substring match).
        """
        from ragling.embeddings import OllamaConnectionError
        from ragling.search import perform_search

        # Derive user context (present for SSE, None for stdio)
        user_ctx = _get_user_context(server_config)

        # Compute visible collections
        visible: list[str] | None = None
        if user_ctx:
            global_coll = "global" if server_config and server_config.global_paths else None
            visible = user_ctx.visible_collections(global_collection=global_coll)

        try:
            results = perform_search(
                query=query,
                collection=collection,
                top_k=top_k,
                source_type=source_type,
                date_from=date_from,
                date_to=date_to,
                sender=sender,
                author=author,
                group_name=group_name,
                config=server_config,
                visible_collections=visible,
            )
        except OllamaConnectionError as e:
            return _build_search_response([{"error": str(e)}], indexing_status)

        cfg = server_config or load_config()
        obsidian_vaults = cfg.obsidian_vaults

        result_dicts = [
            {
                "title": r.title,
                "content": r.content,
                "collection": r.collection,
                "source_type": r.source_type,
                "source_path": r.source_path,
                "source_uri": _build_source_uri(
                    r.source_path,
                    r.source_type,
                    r.metadata,
                    r.collection,
                    obsidian_vaults,
                ),
                "score": round(r.score, 4),
                "metadata": r.metadata,
            }
            for r in results
        ]

        # Apply path mappings for SSE users
        if user_ctx:
            result_dicts = _apply_user_context_to_results(result_dicts, user_ctx)

        return _build_search_response(result_dicts, indexing_status)

    @mcp.tool()
    def rag_list_collections() -> list[dict[str, Any]]:
        """List all available collections with source file counts, chunk counts, and metadata.

        Collections of type 'code' represent code groups that may contain multiple git repos.
        """
        config = server_config or load_config()
        config.group_name = group_name
        conn = get_connection(config)
        init_db(conn, config)

        try:
            rows = conn.execute("""
                SELECT c.name, c.collection_type, c.description, c.created_at,
                       (SELECT COUNT(*) FROM sources s WHERE s.collection_id = c.id) as source_count,
                       (SELECT COUNT(*) FROM documents d WHERE d.collection_id = c.id) as chunk_count,
                       (SELECT MAX(s.last_indexed_at) FROM sources s WHERE s.collection_id = c.id) as last_indexed
                FROM collections c
                ORDER BY c.name
            """).fetchall()

            return [
                {
                    "name": row["name"],
                    "type": row["collection_type"],
                    "description": row["description"],
                    "source_count": row["source_count"],
                    "chunk_count": row["chunk_count"],
                    "last_indexed": row["last_indexed"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    @mcp.tool()
    def rag_index(collection: str, path: str | None = None) -> dict[str, Any]:
        """Trigger indexing for a collection.

        For system collections ('obsidian', 'email', 'calibre', 'rss'), uses configured paths.
        For code groups (matching a key in config code_groups), indexes all repos in that group.
        For project collections, a path argument is required.

        Args:
            collection: Collection name ('obsidian', 'email', 'calibre', 'rss', a code group
                name, or a project name).
            path: Path to index (required for project collections, or to add a single repo
                to a code group).
        """
        from pathlib import Path as P

        from ragling.doc_store import DocStore
        from ragling.indexers.base import BaseIndexer
        from ragling.indexers.calibre_indexer import CalibreIndexer
        from ragling.indexers.email_indexer import EmailIndexer
        from ragling.indexers.git_indexer import GitRepoIndexer
        from ragling.indexers.obsidian import ObsidianIndexer
        from ragling.indexers.project import ProjectIndexer
        from ragling.indexers.rss_indexer import RSSIndexer

        config = server_config or load_config()
        config.group_name = group_name
        conn = get_connection(config)
        init_db(conn, config)
        doc_store = DocStore(config.shared_db_path)

        try:
            if not config.is_collection_enabled(collection):
                return {"error": f"Collection '{collection}' is disabled in config."}

            indexer: BaseIndexer
            if collection == "obsidian":
                indexer = ObsidianIndexer(
                    config.obsidian_vaults, config.obsidian_exclude_folders, doc_store=doc_store
                )
                result = indexer.index(conn, config)
            elif collection == "email":
                indexer = EmailIndexer(str(config.emclient_db_path))
                result = indexer.index(conn, config)
            elif collection == "calibre":
                indexer = CalibreIndexer(config.calibre_libraries, doc_store=doc_store)
                result = indexer.index(conn, config)
            elif collection == "rss":
                indexer = RSSIndexer(str(config.netnewswire_db_path))
                result = indexer.index(conn, config)
            elif collection in config.code_groups:
                # Code group — index all repos in this group (with commit history)
                total_indexed = 0
                total_skipped = 0
                total_errors = 0
                total_found = 0
                for repo_path in config.code_groups[collection]:
                    idx = GitRepoIndexer(repo_path, collection_name=collection)
                    r = idx.index(conn, config, index_history=True)
                    total_indexed += r.indexed
                    total_skipped += r.skipped
                    total_errors += r.errors
                    total_found += r.total_found
                return {
                    "collection": collection,
                    "indexed": total_indexed,
                    "skipped": total_skipped,
                    "errors": total_errors,
                    "total_found": total_found,
                }
            elif path:
                indexer = ProjectIndexer(collection, [P(path)], doc_store=doc_store)
                result = indexer.index(conn, config)
            else:
                return {
                    "error": f"Unknown collection '{collection}'. Provide a path for project indexing."
                }

            return {
                "collection": collection,
                "indexed": result.indexed,
                "skipped": result.skipped,
                "errors": result.errors,
                "total_found": result.total_found,
            }
        finally:
            doc_store.close()
            conn.close()

    @mcp.tool()
    def rag_doc_store_info() -> list[dict[str, Any]]:
        """List all documents in the shared document cache.

        Shows all source files that have been converted by Docling,
        regardless of which group indexed them. Useful for checking
        what's cached and avoiding redundant conversions.

        Returns a list of dicts, each with:
        - source_path: Original file path
        - content_hash: SHA-256 hash of file contents
        - file_size: File size in bytes
        - file_modified_at: When the file was last modified
        - discovered_at: When the file was first seen
        """
        from ragling.doc_store import DocStore

        config = server_config or load_config()
        config.group_name = group_name
        store = DocStore(config.shared_db_path)
        try:
            return store.list_sources()
        finally:
            store.close()

    @mcp.tool()
    def rag_collection_info(collection: str) -> dict[str, Any]:
        """Get detailed information about a specific collection.

        Args:
            collection: The collection name.
        """
        config = server_config or load_config()
        config.group_name = group_name
        conn = get_connection(config)
        init_db(conn, config)

        try:
            row = conn.execute("SELECT * FROM collections WHERE name = ?", (collection,)).fetchone()

            if not row:
                return {"error": f"Collection '{collection}' not found."}

            coll_id = row["id"]

            doc_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM documents WHERE collection_id = ?",
                (coll_id,),
            ).fetchone()["cnt"]

            source_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM sources WHERE collection_id = ?",
                (coll_id,),
            ).fetchone()["cnt"]

            type_breakdown = conn.execute(
                "SELECT source_type, COUNT(*) as cnt FROM sources WHERE collection_id = ? GROUP BY source_type",
                (coll_id,),
            ).fetchall()

            last_indexed = conn.execute(
                "SELECT MAX(last_indexed_at) as ts FROM sources WHERE collection_id = ?",
                (coll_id,),
            ).fetchone()["ts"]

            sample_titles = conn.execute(
                "SELECT DISTINCT title FROM documents WHERE collection_id = ? LIMIT 10",
                (coll_id,),
            ).fetchall()

            return {
                "name": collection,
                "type": row["collection_type"],
                "description": row["description"],
                "created_at": row["created_at"],
                "source_count": source_count,
                "chunk_count": doc_count,
                "last_indexed": last_indexed,
                "source_types": {tb["source_type"]: tb["cnt"] for tb in type_breakdown},
                "sample_titles": [st["title"] for st in sample_titles],
            }
        finally:
            conn.close()

    @mcp.tool()
    def rag_convert(file_path: str) -> str:
        """Convert a document (PDF, DOCX, etc.) to markdown text.

        Supports PDF, DOCX, PPTX, XLSX, HTML, EPUB, images, and plain text.
        Results are cached — converting the same file twice is instant.

        Args:
            file_path: Path to the document file.
        """
        user_ctx = _get_user_context(server_config)
        mappings = user_ctx.path_mappings if user_ctx else {}
        return _convert_document(file_path, path_mappings=mappings)

    return mcp
