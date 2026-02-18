"""Core benchmark runner — times conversion, chunking, and embedding stages."""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ragling.chunker import Chunk
from ragling.config import Config
from ragling.doc_store import DocStore
from ragling.docling_bridge import (
    epub_to_docling_doc,
    markdown_to_docling_doc,
    plaintext_to_docling_doc,
)
from ragling.docling_convert import DOCLING_FORMATS, chunk_with_hybrid, convert_and_chunk
from ragling.embeddings import get_embeddings
from ragling.indexers.project import _EXTENSION_MAP
from ragling.parsers.epub import parse_epub
from ragling.parsers.markdown import parse_markdown

from benchmark.fixtures import Fixture
from benchmark.matrix import Matrix

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Timing result for one (configuration, fixture) pair."""

    tag: str
    configuration: str
    fixture: str
    format_group: str
    file_size_kb: int
    conversion_ms: int
    chunking_ms: int
    embedding_ms: int
    total_ms: int
    chunks_produced: int


def time_conversion(
    path: Path,
    source_type: str,
    config: Config,
    doc_store: DocStore | None,
) -> tuple[int, list[Chunk]]:
    """Time the conversion + chunking stage for a file.

    Returns (elapsed_ms, chunks). Conversion and chunking are measured
    together because for Docling formats they're tightly coupled.

    Args:
        path: Path to the fixture file.
        source_type: Source type string (e.g. "pdf", "markdown").
        config: Ragling config with enrichment settings.
        doc_store: Doc store for Docling formats (can be None for bridge formats).

    Returns:
        Tuple of (elapsed_ms, list of Chunk objects).
    """
    start = time.monotonic()

    if source_type in DOCLING_FORMATS:
        if doc_store is None:
            logger.error("Docling format %s requires doc_store", source_type)
            return 0, []
        chunks = convert_and_chunk(
            path,
            doc_store,
            chunk_max_tokens=config.chunk_size_tokens,
            source_type=source_type,
            asr_model=config.asr.model,
            config=config,
        )
    elif source_type == "markdown":
        text = path.read_text(encoding="utf-8", errors="replace")
        doc = parse_markdown(text, path.name)
        docling_doc = markdown_to_docling_doc(doc.body_text, doc.title)
        chunks = chunk_with_hybrid(
            docling_doc,
            title=doc.title,
            source_path=str(path),
            chunk_max_tokens=config.chunk_size_tokens,
        )
    elif source_type == "epub":
        chapters = parse_epub(path)
        docling_doc = epub_to_docling_doc(chapters, path.name)
        chunks = chunk_with_hybrid(
            docling_doc,
            title=path.name,
            source_path=str(path),
            chunk_max_tokens=config.chunk_size_tokens,
        )
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        docling_doc = plaintext_to_docling_doc(text, path.name)
        chunks = chunk_with_hybrid(
            docling_doc,
            title=path.name,
            source_path=str(path),
            chunk_max_tokens=config.chunk_size_tokens,
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return elapsed_ms, chunks


def time_embedding(texts: list[str], config: Config) -> int:
    """Time the embedding stage.

    Args:
        texts: List of chunk texts to embed.
        config: Ragling config (embedding model, ollama host).

    Returns:
        Elapsed time in milliseconds.
    """
    start = time.monotonic()
    get_embeddings(texts, config)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return elapsed_ms


def warmup_models(config: Config) -> None:
    """Send throwaway requests to pre-load models into Ollama.

    Args:
        config: Ragling config with embedding model and ollama host.
    """
    logger.info("Warming up embedding model: %s", config.embedding_model)
    try:
        get_embeddings(["warmup"], config)
    except Exception as e:
        logger.warning("Warmup failed for %s: %s", config.embedding_model, e)


def run_benchmarks(
    matrix: Matrix,
    fixtures: list[Fixture],
    tag: str,
    ollama_host: str | None = None,
    on_result: Callable[[BenchmarkResult], None] | None = None,
) -> list[BenchmarkResult]:
    """Run the full benchmark suite.

    For each configuration, creates a fresh temp doc_store, warms up
    models, then times conversion + embedding for each fixture.

    Args:
        matrix: Parsed benchmark matrix.
        fixtures: List of discovered fixtures.
        tag: Hardware tag label.
        ollama_host: Optional Ollama host override.

    Returns:
        List of BenchmarkResult, one per (configuration, fixture) pair.
    """
    results: list[BenchmarkResult] = []

    for bench_config in matrix.configurations:
        config = bench_config.to_ragling_config(matrix.defaults, ollama_host)
        logger.info("=== Configuration: %s ===", bench_config.name)

        # Fresh temp doc store per configuration
        with tempfile.TemporaryDirectory() as tmp_dir:
            doc_store = DocStore(Path(tmp_dir) / "doc_store.sqlite")
            warmup_models(config)

            for fixture in fixtures:
                source_type = _EXTENSION_MAP.get(fixture.path.suffix.lower())
                if source_type is None:
                    logger.warning("Skipping unsupported fixture: %s", fixture.name)
                    continue

                logger.info("  %s ...", fixture.name)
                total_start = time.monotonic()

                try:
                    conversion_ms, chunks = time_conversion(
                        fixture.path, source_type, config, doc_store
                    )

                    texts = [c.text for c in chunks]
                    embedding_ms = time_embedding(texts, config) if texts else 0

                    total_ms = int((time.monotonic() - total_start) * 1000)

                    results.append(
                        BenchmarkResult(
                            tag=tag,
                            configuration=bench_config.name,
                            fixture=fixture.name,
                            format_group=fixture.format_group,
                            file_size_kb=fixture.file_size // 1024,
                            conversion_ms=conversion_ms,
                            chunking_ms=total_ms - conversion_ms - embedding_ms,
                            embedding_ms=embedding_ms,
                            total_ms=total_ms,
                            chunks_produced=len(chunks),
                        )
                    )
                    if on_result is not None:
                        on_result(results[-1])
                    logger.info(
                        "    %dms total (%d chunks)",
                        total_ms,
                        len(chunks),
                    )
                except Exception as e:
                    logger.error("    FAILED: %s", e)
                    total_ms = int((time.monotonic() - total_start) * 1000)
                    results.append(
                        BenchmarkResult(
                            tag=tag,
                            configuration=bench_config.name,
                            fixture=fixture.name,
                            format_group=fixture.format_group,
                            file_size_kb=fixture.file_size // 1024,
                            conversion_ms=0,
                            chunking_ms=0,
                            embedding_ms=0,
                            total_ms=total_ms,
                            chunks_produced=0,
                        )
                    )
                    if on_result is not None:
                        on_result(results[-1])

    return results
