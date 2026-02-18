"""Core benchmark runner — times conversion, chunking, and embedding stages."""

from __future__ import annotations

from dataclasses import dataclass


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
