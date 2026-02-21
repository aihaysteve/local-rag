"""Append-only query logging for ACE telemetry."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def log_query(
    log_path: Path,
    query: str,
    filters: dict[str, Any],
    top_k: int,
    results: list[dict[str, Any]],
    duration_ms: float,
) -> None:
    """Append a query log entry as a single JSONL line.

    Flushes and fsyncs after each write so ``tail -f`` consumers
    see entries immediately.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "filters": {k: v for k, v in filters.items() if v is not None},
        "top_k": top_k,
        "results": [
            {
                "rank": i,
                "title": r.get("title", ""),
                "source_path": r.get("source_path", ""),
                "source_type": r.get("source_type", ""),
                "collection": r.get("collection", ""),
                "rrf_score": r.get("score", 0),
            }
            for i, r in enumerate(results)
        ],
        "duration_ms": round(duration_ms, 1),
    }

    try:
        fd = os.open(str(log_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            line = json.dumps(entry, separators=(",", ":")) + "\n"
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        logger.warning("Failed to write query log to %s", log_path, exc_info=True)
