"""Processing pipeline for walk results.

Takes a WalkResult manifest and indexes each file into the database,
using existing parsers and the atomic upsert pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ragling.db import get_or_create_collection
from ragling.document.chunker import Chunk
from ragling.embeddings import get_embeddings
from ragling.indexers.base import (
    IndexResult,
    file_hash,
    prune_stale_sources,
    upsert_source_with_chunks,
)
from ragling.indexers.walker import FileRoute, WalkResult, assign_collection

if TYPE_CHECKING:
    import sqlite3

    from ragling.config import Config
    from ragling.doc_store import DocStore
    from ragling.indexing_status import IndexingStatus

logger = logging.getLogger(__name__)


def process_walk_result(
    walk_result: WalkResult,
    conn: sqlite3.Connection,
    config: Config,
    *,
    watch_name: str,
    watch_root: Path,
    force: bool = False,
    doc_store: DocStore | None = None,
    status: IndexingStatus | None = None,
) -> IndexResult:
    """Process a walk manifest: parse, embed, and persist each file."""
    result = IndexResult(total_found=len(walk_result.routes))
    total = len(walk_result.routes)

    # Cache collection IDs
    collection_ids: dict[str, int] = {}

    if status:
        status.set_file_total(watch_name, total)

    for i, route in enumerate(walk_result.routes):
        try:
            _process_file(
                route,
                conn,
                config,
                result,
                watch_name=watch_name,
                watch_root=watch_root,
                force=force,
                doc_store=doc_store,
                collection_ids=collection_ids,
            )
        except Exception:
            logger.exception("Error processing %s", route.path)
            result.errors += 1
            result.error_messages.append(str(route.path))
        finally:
            if status:
                status.file_processed(watch_name)

    # Prune stale sources for each collection we touched
    for coll_name, coll_id in collection_ids.items():
        try:
            result.pruned += prune_stale_sources(conn, coll_id)
        except Exception:
            logger.exception("Error pruning collection %s", coll_name)

    return result


def _process_file(
    route: FileRoute,
    conn: sqlite3.Connection,
    config: Config,
    result: IndexResult,
    *,
    watch_name: str,
    watch_root: Path,
    force: bool,
    doc_store: DocStore | None,
    collection_ids: dict[str, int],
) -> None:
    """Process a single file from the walk manifest."""
    path = route.path

    if not path.exists():
        result.errors += 1
        result.error_messages.append(f"File not found: {path}")
        return

    # Determine collection
    coll_name = assign_collection(route, watch_name=watch_name, watch_root=watch_root)
    if coll_name not in collection_ids:
        collection_ids[coll_name] = get_or_create_collection(conn, coll_name)
    coll_id = collection_ids[coll_name]

    # Change detection
    current_hash = file_hash(path)
    if not force:
        existing = conn.execute(
            "SELECT file_hash FROM sources WHERE collection_id = ? AND source_path = ?",
            (coll_id, str(path)),
        ).fetchone()
        if existing and existing["file_hash"] == current_hash:
            result.skipped += 1
            return

    # Parse the file
    chunks = _parse_route(route, config, doc_store, watch_root)
    if not chunks:
        result.skipped_empty += 1
        return

    # Embed and persist
    embeddings = get_embeddings([c.text for c in chunks], config)
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()

    upsert_source_with_chunks(
        conn,
        collection_id=coll_id,
        source_path=str(path),
        source_type=route.parser,
        chunks=chunks,
        embeddings=embeddings,
        file_hash=current_hash,
        file_modified_at=modified_at,
    )
    result.indexed += 1


def _parse_route(
    route: FileRoute,
    config: Config,
    doc_store: DocStore | None,
    watch_root: Path,
) -> list[Chunk]:
    """Parse a file based on its routing decision."""
    path = route.path

    if route.parser == "treesitter":
        return _parse_treesitter(route, config, watch_root)

    # For spec, markdown, docling, plaintext — use existing format_routing
    from ragling.indexers.format_routing import parse_and_chunk

    # Determine source_type for parse_and_chunk compatibility
    if route.parser == "spec":
        source_type = "spec"
    elif route.parser == "markdown":
        source_type = "markdown"
    elif route.parser == "docling":
        ext = path.suffix.lower()
        from ragling.indexers.walker import DOCLING_EXTENSIONS

        source_type = DOCLING_EXTENSIONS.get(ext, "pdf")
    elif route.parser == "plaintext":
        source_type = "plaintext"
    else:
        source_type = "plaintext"

    # Compute source_path for metadata context
    if route.git_root:
        source_path = str(path.relative_to(route.git_root))
    elif route.vault_root:
        source_path = str(path.relative_to(route.vault_root))
    else:
        source_path = str(path.relative_to(watch_root))

    return parse_and_chunk(path, source_type, config, doc_store, source_path)


def _parse_treesitter(
    route: FileRoute,
    config: Config,
    watch_root: Path,
) -> list[Chunk]:
    """Parse a code file with tree-sitter and convert to chunks."""
    from ragling.parsers.code import get_language, parse_code_file
    from ragling.parsers.spec import find_nearest_spec

    path = route.path
    language = get_language(path)
    if language is None:
        return []

    # Compute relative path for metadata
    if route.git_root:
        relative_path = str(path.relative_to(route.git_root))
    else:
        relative_path = str(path.relative_to(watch_root))

    code_doc = parse_code_file(path, language, relative_path)
    if code_doc is None or not code_doc.blocks:
        return []

    # Find nearest SPEC.md for annotation
    spec_context: str | None = None
    if route.git_root:
        spec_context = find_nearest_spec(path, route.git_root)

    chunks: list[Chunk] = []
    for i, block in enumerate(code_doc.blocks):
        prefix = f"[{relative_path}] [{block.language}:{block.symbol_type}] {block.symbol_name}"
        if spec_context:
            prefix += f" (spec: {spec_context})"

        chunks.append(
            Chunk(
                text=f"{prefix}\n\n{block.text}",
                title=f"{relative_path}:{block.symbol_name}",
                metadata={
                    "language": block.language,
                    "symbol_name": block.symbol_name,
                    "symbol_type": block.symbol_type,
                    "start_line": block.start_line,
                    "end_line": block.end_line,
                    "file_path": relative_path,
                    **({"spec_context": spec_context} if spec_context else {}),
                },
                chunk_index=i,
            )
        )

    return chunks
