"""Click CLI entry point for ragling."""

import logging
import signal
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ragling.config import Config, load_config

console = Console()


def _handle_sigint(_sig: int, _frame: object) -> None:
    """Handle Ctrl+C gracefully."""
    click.echo("\nInterrupted. Shutting down...", err=True)
    sys.exit(130)


signal.signal(signal.SIGINT, _handle_sigint)

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    """Configure logging level."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence noisy HTTP request logging from httpx/httpcore
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _get_db(config: Config, group: str = "default"):
    """Get initialized database connection.

    Args:
        config: Application configuration.
        group: Group name for per-group indexes. Sets config.group_name
            so the correct database path is used.
    """
    from ragling.db import get_connection, init_db

    config.group_name = group
    conn = get_connection(config)
    init_db(conn, config)
    return conn


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.option(
    "--group", "-g", default="default", show_default=True, help="Group name for per-group indexes."
)
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to config file.",
)
@click.pass_context
def main(ctx: click.Context, verbose: bool, group: str, config_path: Path | None) -> None:
    """ragling: Docling-powered local RAG with shared document cache."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["group"] = group
    ctx.obj["config_path"] = config_path


# ── Index commands ──────────────────────────────────────────────────────


@main.group()
def index() -> None:
    """Index sources into the RAG database."""


def _print_index_result(label: str, result) -> None:
    """Print a colored index result summary."""
    parts = [
        f"[bold]{label}[/bold] indexing complete:",
        f"  [green]{result.indexed} indexed[/green],",
        f"  [dim]{result.skipped} skipped[/dim],",
    ]
    error_style = "red" if result.errors > 0 else "dim"
    parts.append(f"  [{error_style}]{result.errors} errors[/{error_style}]")
    parts.append(f"  [dim](out of {result.total_found} found)[/dim]")
    console.print(" ".join(parts))


def _check_collection_enabled(config, name: str) -> None:
    """Exit with a message if the collection is disabled in config."""
    if not config.is_collection_enabled(name):
        click.echo(
            f"Collection '{name}' is disabled in config (disabled_collections). "
            "Remove it from disabled_collections to re-enable.",
            err=True,
        )
        sys.exit(1)


@index.command("obsidian")
@click.option(
    "--vault",
    "-v",
    "vaults",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Vault path(s). If omitted, uses config.",
)
@click.option("--force", is_flag=True, help="Force re-index all files.")
@click.pass_context
def index_obsidian(ctx: click.Context, vaults: tuple[Path, ...], force: bool) -> None:
    """Index Obsidian vault(s)."""
    from ragling.doc_store import DocStore
    from ragling.indexers.obsidian import ObsidianIndexer

    config = load_config(ctx.obj.get("config_path"))
    _check_collection_enabled(config, "obsidian")
    vault_paths = list(vaults) if vaults else config.obsidian_vaults

    if not vault_paths:
        click.echo(
            "Error: No vault paths provided. Use --vault or set obsidian_vaults in config.",
            err=True,
        )
        sys.exit(1)

    group = ctx.obj["group"]
    conn = _get_db(config, group)
    doc_store = DocStore(config.shared_db_path)
    try:
        indexer = ObsidianIndexer(vault_paths, config.obsidian_exclude_folders, doc_store=doc_store)
        result = indexer.index(conn, config, force=force)
        _print_index_result("Obsidian", result)
    finally:
        doc_store.close()
        conn.close()


@index.command("email")
@click.option("--force", is_flag=True, help="Force re-index all emails.")
@click.pass_context
def index_email(ctx: click.Context, force: bool) -> None:
    """Index eM Client emails."""
    from ragling.indexers.email_indexer import EmailIndexer

    config = load_config(ctx.obj.get("config_path"))
    _check_collection_enabled(config, "email")
    group = ctx.obj["group"]
    conn = _get_db(config, group)
    try:
        indexer = EmailIndexer(str(config.emclient_db_path))
        result = indexer.index(conn, config, force=force)
        _print_index_result("Email", result)
    finally:
        conn.close()


@index.command("calibre")
@click.option(
    "--library",
    "-l",
    "libraries",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Library path(s). If omitted, uses config.",
)
@click.option("--force", is_flag=True, help="Force re-index all books.")
@click.pass_context
def index_calibre(ctx: click.Context, libraries: tuple[Path, ...], force: bool) -> None:
    """Index Calibre ebook library/libraries."""
    from ragling.doc_store import DocStore
    from ragling.indexers.calibre_indexer import CalibreIndexer

    config = load_config(ctx.obj.get("config_path"))
    _check_collection_enabled(config, "calibre")
    library_paths = list(libraries) if libraries else config.calibre_libraries

    if not library_paths:
        click.echo(
            "Error: No library paths provided. Use --library or set calibre_libraries in config.",
            err=True,
        )
        sys.exit(1)

    group = ctx.obj["group"]
    conn = _get_db(config, group)
    doc_store = DocStore(config.shared_db_path)
    try:
        indexer = CalibreIndexer(library_paths, doc_store=doc_store)
        result = indexer.index(conn, config, force=force)
        _print_index_result("Calibre", result)
    finally:
        doc_store.close()
        conn.close()


@index.command("rss")
@click.option("--force", is_flag=True, help="Force re-index all articles.")
@click.pass_context
def index_rss(ctx: click.Context, force: bool) -> None:
    """Index NetNewsWire RSS articles."""
    from ragling.indexers.rss_indexer import RSSIndexer

    config = load_config(ctx.obj.get("config_path"))
    _check_collection_enabled(config, "rss")
    group = ctx.obj["group"]
    conn = _get_db(config, group)
    try:
        indexer = RSSIndexer(str(config.netnewswire_db_path))
        result = indexer.index(conn, config, force=force)
        _print_index_result("RSS", result)
    finally:
        conn.close()


@index.command("project")
@click.argument("name")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--force", is_flag=True, help="Force re-index all files.")
@click.pass_context
def index_project(ctx: click.Context, name: str, paths: tuple[Path, ...], force: bool) -> None:
    """Index documents into a named project collection."""
    from ragling.doc_store import DocStore
    from ragling.indexers.project import ProjectIndexer

    config = load_config(ctx.obj.get("config_path"))
    _check_collection_enabled(config, name)
    group = ctx.obj["group"]
    conn = _get_db(config, group)
    doc_store = DocStore(config.shared_db_path)
    try:
        indexer = ProjectIndexer(name, list(paths), doc_store=doc_store)
        result = indexer.index(conn, config, force=force)
        _print_index_result(name, result)
    finally:
        doc_store.close()
        conn.close()


@index.command("group")
@click.argument("name", required=False)
@click.option("--force", is_flag=True, help="Force re-index all files.")
@click.option("--history", is_flag=True, help="Also index commit history (last N months).")
@click.pass_context
def index_group(ctx: click.Context, name: str | None, force: bool, history: bool) -> None:
    """Index code group(s) from config.

    If NAME is given, indexes only that group's repos. If omitted, indexes
    all groups defined in code_groups config.
    """
    from ragling.indexers.git_indexer import GitRepoIndexer

    config = load_config(ctx.obj.get("config_path"))

    if name:
        if name not in config.code_groups:
            click.echo(f"Error: Group '{name}' not found in code_groups config.", err=True)
            sys.exit(1)
        groups = {name: config.code_groups[name]}
    elif config.code_groups:
        groups = config.code_groups
    else:
        click.echo("Error: No code_groups configured in ~/.ragling/config.json.", err=True)
        sys.exit(1)

    cli_group = ctx.obj["group"]
    conn = _get_db(config, cli_group)
    try:
        for code_group_name, repo_paths in groups.items():
            _check_collection_enabled(config, code_group_name)
            for repo_path in repo_paths:
                click.echo(f"  {code_group_name}: {repo_path}")
                indexer = GitRepoIndexer(repo_path, collection_name=code_group_name)
                result = indexer.index(conn, config, force=force, index_history=history)
                _print_index_result(f"{code_group_name}/{repo_path.name}", result)
    finally:
        conn.close()


@index.command("all")
@click.option("--force", is_flag=True, help="Force re-index all sources.")
@click.pass_context
def index_all(ctx: click.Context, force: bool) -> None:
    """Index all configured sources at once.

    Indexes obsidian, email, calibre, rss, and code groups based on what
    is configured in ~/.ragling/config.json. Skips any source that
    has no paths configured.
    """
    from ragling.doc_store import DocStore
    from ragling.indexers.base import BaseIndexer
    from ragling.indexers.calibre_indexer import CalibreIndexer
    from ragling.indexers.email_indexer import EmailIndexer
    from ragling.indexers.git_indexer import GitRepoIndexer
    from ragling.indexers.obsidian import ObsidianIndexer
    from ragling.indexers.rss_indexer import RSSIndexer

    config = load_config(ctx.obj.get("config_path"))
    group = ctx.obj["group"]
    conn = _get_db(config, group)
    doc_store = DocStore(config.shared_db_path)

    sources: list[tuple[str, BaseIndexer]] = []

    if config.is_collection_enabled("obsidian") and config.obsidian_vaults:
        sources.append(
            (
                "obsidian",
                ObsidianIndexer(
                    config.obsidian_vaults, config.obsidian_exclude_folders, doc_store=doc_store
                ),
            )
        )

    if (
        config.is_collection_enabled("email")
        and config.emclient_db_path
        and config.emclient_db_path.exists()
    ):
        sources.append(("email", EmailIndexer(str(config.emclient_db_path))))

    if config.is_collection_enabled("calibre") and config.calibre_libraries:
        sources.append(("calibre", CalibreIndexer(config.calibre_libraries, doc_store=doc_store)))

    if (
        config.is_collection_enabled("rss")
        and config.netnewswire_db_path
        and config.netnewswire_db_path.exists()
    ):
        sources.append(("rss", RSSIndexer(str(config.netnewswire_db_path))))

    git_indexers: list[str] = []
    for group_name, repo_paths in config.code_groups.items():
        if config.is_collection_enabled(group_name):
            for repo_path in repo_paths:
                label = f"{group_name}/{repo_path.name}"
                sources.append((label, GitRepoIndexer(repo_path, collection_name=group_name)))
                git_indexers.append(label)

    if not sources:
        click.echo("No sources configured. Set paths in ~/.ragling/config.json.", err=True)
        sys.exit(1)

    click.echo(f"Indexing {len(sources)} source(s)...\n")

    summary_rows: list[tuple[str, int, int, int, int, str | None]] = []

    try:
        for label, indexer in sources:
            click.echo(f"  {label}...")
            try:
                if label in git_indexers:
                    assert isinstance(indexer, GitRepoIndexer)
                    result = indexer.index(conn, config, force=force, index_history=True)
                else:
                    result = indexer.index(conn, config, force=force)
                summary_rows.append(
                    (label, result.indexed, result.skipped, result.errors, result.total_found, None)
                )
            except Exception as e:
                summary_rows.append((label, 0, 0, 0, 0, str(e)))
    finally:
        doc_store.close()
        conn.close()

    table = Table(title="Indexing Summary")
    table.add_column("Collection", style="bold")
    table.add_column("Indexed", justify="right", style="green")
    table.add_column("Skipped", justify="right", style="dim")
    table.add_column("Errors", justify="right")
    table.add_column("Total", justify="right")

    for label, indexed, skipped, errors, total, error_msg in summary_rows:
        error_style = "red" if errors > 0 else "dim"
        if error_msg:
            table.add_row(label, "-", "-", "[red]failed[/red]", "-")
        else:
            table.add_row(
                label,
                str(indexed),
                str(skipped),
                Text(str(errors), style=error_style),
                str(total),
            )

    console.print(table)


# ── Search command ──────────────────────────────────────────────────────


@main.command()
@click.argument("query")
@click.option("--collection", "-c", help="Search within a specific collection.")
@click.option("--type", "source_type", help="Filter by source type (e.g., pdf, markdown, email).")
@click.option("--from", "sender", help="Filter by email sender.")
@click.option("--author", help="Filter by book author (case-insensitive substring match).")
@click.option("--after", help="Only results after this date (YYYY-MM-DD).")
@click.option("--before", help="Only results before this date (YYYY-MM-DD).")
@click.option("--top", default=10, show_default=True, help="Number of results to return.")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    collection: str | None,
    source_type: str | None,
    sender: str | None,
    author: str | None,
    after: str | None,
    before: str | None,
    top: int,
) -> None:
    """Search across indexed collections."""
    from ragling.embeddings import OllamaConnectionError
    from ragling.search import perform_search

    group = ctx.obj["group"]
    config = load_config(ctx.obj.get("config_path"))

    try:
        results = perform_search(
            query=query,
            collection=collection,
            top_k=top,
            source_type=source_type,
            date_from=after,
            date_to=before,
            sender=sender,
            author=author,
            group_name=group,
            config=config,
        )
    except OllamaConnectionError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not results:
        click.echo("No results found.")
        return

    for i, r in enumerate(results, 1):
        # Color-code score
        score = r.score
        if score >= 0.7:
            score_text = Text(f"{score:.4f}", style="green")
        elif score >= 0.4:
            score_text = Text(f"{score:.4f}", style="yellow")
        else:
            score_text = Text(f"{score:.4f}", style="red")

        console.print()
        console.rule(f"[bold]\\[{i}] {r.title}[/bold]", style="dim")

        meta_table = Table(show_header=False, box=None, padding=(0, 2))
        meta_table.add_column("Key", style="bold")
        meta_table.add_column("Value")
        meta_table.add_row("Collection", r.collection)
        meta_table.add_row("Type", r.source_type)
        meta_table.add_row("Score", score_text)
        meta_table.add_row("Source", r.source_path)

        if r.metadata:
            meta_items = {k: v for k, v in r.metadata.items() if k != "heading_path"}
            if meta_items:
                meta_str = ", ".join(f"{k}={v}" for k, v in meta_items.items())
                meta_table.add_row("Meta", meta_str)

        console.print(meta_table)

        # Show snippet (first 300 chars)
        snippet = r.content[:300].replace("\n", " ")
        if len(r.content) > 300:
            snippet += "..."
        console.print(f"  [dim]{snippet}[/dim]")

    console.print()
    console.print(f"[bold]{len(results)}[/bold] result(s) found.")


# ── Collections commands ────────────────────────────────────────────────


@main.group()
def collections() -> None:
    """Manage collections."""


@collections.command("list")
@click.pass_context
def collections_list(ctx: click.Context) -> None:
    """List all collections with document counts."""
    config = load_config(ctx.obj.get("config_path"))
    group = ctx.obj["group"]
    conn = _get_db(config, group)
    try:
        rows = conn.execute("""
            SELECT c.name, c.collection_type, c.created_at,
                   (SELECT COUNT(*) FROM sources s WHERE s.collection_id = c.id) as source_count,
                   (SELECT COUNT(*) FROM documents d WHERE d.collection_id = c.id) as chunk_count
            FROM collections c
            ORDER BY c.name
        """).fetchall()

        if not rows:
            click.echo("No collections found.")
            return

        table = Table(title="Collections")
        table.add_column("Name", style="bold")
        table.add_column("Type", style="dim")
        table.add_column("Sources", justify="right")
        table.add_column("Chunks", justify="right")
        table.add_column("Created", style="dim")

        for row in rows:
            table.add_row(
                row["name"],
                row["collection_type"],
                str(row["source_count"]),
                str(row["chunk_count"]),
                row["created_at"],
            )

        console.print(table)
    finally:
        conn.close()


@collections.command("info")
@click.argument("name")
@click.pass_context
def collections_info(ctx: click.Context, name: str) -> None:
    """Show detailed info about a collection."""
    config = load_config(ctx.obj.get("config_path"))
    group = ctx.obj["group"]
    conn = _get_db(config, group)
    try:
        row = conn.execute("SELECT * FROM collections WHERE name = ?", (name,)).fetchone()
        if not row:
            click.echo(f"Error: Collection '{name}' not found.", err=True)
            sys.exit(1)

        coll_id = row["id"]

        doc_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM documents WHERE collection_id = ?", (coll_id,)
        ).fetchone()["cnt"]

        source_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM sources WHERE collection_id = ?", (coll_id,)
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
            "SELECT DISTINCT title FROM documents WHERE collection_id = ? LIMIT 5",
            (coll_id,),
        ).fetchall()

        info = Table(show_header=False, box=None, padding=(0, 2))
        info.add_column("Key", style="bold")
        info.add_column("Value")
        info.add_row("Collection", name)
        info.add_row("Type", row["collection_type"])
        info.add_row("Created", row["created_at"])
        info.add_row("Description", row["description"] or "(none)")
        info.add_row("Sources", str(source_count))
        info.add_row("Chunks", str(doc_count))
        info.add_row("Last indexed", last_indexed or "never")
        console.print(info)

        if type_breakdown:
            console.print()
            types_table = Table(title="Source Types")
            types_table.add_column("Type")
            types_table.add_column("Count", justify="right")
            for tb in type_breakdown:
                types_table.add_row(tb["source_type"], str(tb["cnt"]))
            console.print(types_table)

        if sample_titles:
            console.print()
            console.print("[bold]Sample titles[/bold]")
            for st in sample_titles:
                console.print(f"  - {st['title']}")
    finally:
        conn.close()


@collections.command("delete")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def collections_delete(ctx: click.Context, name: str, yes: bool) -> None:
    """Delete a collection and all its data."""
    config = load_config(ctx.obj.get("config_path"))
    group = ctx.obj["group"]
    conn = _get_db(config, group)
    try:
        row = conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
        if not row:
            click.echo(f"Error: Collection '{name}' not found.", err=True)
            sys.exit(1)

        if not yes:
            doc_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM documents WHERE collection_id = ?",
                (row["id"],),
            ).fetchone()["cnt"]
            if not click.confirm(f"Delete collection '{name}' and all {doc_count} documents?"):
                click.echo("Cancelled.")
                return

        coll_id = row["id"]

        # Delete vec_documents entries for documents in this collection
        conn.execute(
            "DELETE FROM vec_documents WHERE document_id IN (SELECT id FROM documents WHERE collection_id = ?)",
            (coll_id,),
        )
        # CASCADE will handle sources and documents
        conn.execute("DELETE FROM collections WHERE id = ?", (coll_id,))
        conn.commit()

        click.echo(f"Collection '{name}' deleted.")
    finally:
        conn.close()


# ── Status command ──────────────────────────────────────────────────────


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show overall RAG status and statistics."""
    config = load_config(ctx.obj.get("config_path"))
    group = ctx.obj["group"]
    config.group_name = group

    # Check the right database path based on group
    if group != "default":
        db_path = config.group_index_db_path
    else:
        db_path = config.db_path

    if not db_path.exists():
        click.echo("Database not found. Run 'ragling index' to get started.")
        return

    conn = _get_db(config, group)
    try:
        coll_count = conn.execute("SELECT COUNT(*) as cnt FROM collections").fetchone()["cnt"]
        doc_count = conn.execute("SELECT COUNT(*) as cnt FROM documents").fetchone()["cnt"]
        source_count = conn.execute("SELECT COUNT(*) as cnt FROM sources").fetchone()["cnt"]

        db_size_mb = db_path.stat().st_size / (1024 * 1024)

        last_indexed = conn.execute("SELECT MAX(last_indexed_at) as ts FROM sources").fetchone()[
            "ts"
        ]

        table = Table(title="ragling status", show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        table.add_row("Database", str(db_path))
        table.add_row("Size", f"{db_size_mb:.1f} MB")
        table.add_row("Collections", str(coll_count))
        table.add_row("Sources", str(source_count))
        table.add_row("Chunks", str(doc_count))
        table.add_row("Last indexed", last_indexed or "never")
        table.add_row(
            "Embedding model", f"{config.embedding_model} ({config.embedding_dimensions}d)"
        )
        console.print(table)
    finally:
        conn.close()


# ── Serve command ───────────────────────────────────────────────────────


@main.command()
@click.option(
    "--port",
    type=int,
    default=10001,
    show_default=True,
    help="Port for SSE transport.",
)
@click.option("--sse", is_flag=True, help="Enable SSE transport.")
@click.option("--no-stdio", is_flag=True, help="Disable stdio transport (SSE only).")
@click.pass_context
def serve(ctx: click.Context, port: int, sse: bool, no_stdio: bool) -> None:
    """Start the MCP server."""
    from ragling.indexing_status import IndexingStatus
    from ragling.mcp_server import create_server

    if no_stdio and not sse:
        click.echo("Error: Cannot disable both stdio and SSE.", err=True)
        ctx.exit(1)
        return

    group = ctx.obj["group"]
    config = load_config(ctx.obj.get("config_path"))

    # Create shared indexing status
    indexing_status = IndexingStatus()

    # Start startup sync and file watcher if home/global paths configured
    if config.home or config.global_paths:
        import threading

        from ragling.sync import run_startup_sync
        from ragling.watcher import start_watcher

        sync_done = threading.Event()
        run_startup_sync(config, indexing_status, done_event=sync_done)

        def _on_files_changed(files: list[Path]) -> None:
            from ragling.sync import _index_file

            logger.info("File changes detected: %d files", len(files))
            for file_path in files:
                try:
                    _index_file(file_path, config)
                except Exception:
                    logger.exception("Error indexing changed file: %s", file_path)

        # Wait for initial sync before starting watcher
        sync_done.wait()

        start_watcher(config, _on_files_changed)

    server = create_server(
        group_name=group,
        config=config,
        indexing_status=indexing_status,
    )

    if sse and not no_stdio:
        import anyio

        click.echo(f"Starting MCP server (stdio + SSE on port {port}, group: {group})...")
        server.settings.port = port

        async def _run_both() -> None:
            async with anyio.create_task_group() as tg:
                tg.start_soon(server.run_sse_async)
                tg.start_soon(server.run_stdio_async)

        anyio.run(_run_both)
    elif sse:
        click.echo(f"Starting MCP server on port {port} (SSE only, group: {group})...")
        server.settings.port = port
        server.run(transport="sse")
    elif not no_stdio:
        server.run(transport="stdio")
