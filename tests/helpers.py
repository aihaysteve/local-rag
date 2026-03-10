"""Shared test helpers for ragling tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ragling.config import Config
from ragling.db import get_connection, init_db

EMBED_DIM = 4


def make_test_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create an initialized test DB with small embedding dimensions."""
    config = make_test_config(tmp_path)
    conn = get_connection(config)
    init_db(conn, config)
    return conn


def make_test_config(tmp_path: Path, **overrides: Any) -> Config:
    """Create a Config suitable for testing.

    Accepts keyword overrides for any Config field.
    """
    defaults: dict[str, Any] = {
        "db_path": tmp_path / "test.db",
        "embedding_dimensions": EMBED_DIM,
    }
    defaults.update(overrides)
    return Config(**defaults)


def fake_embeddings(texts: list[str], config: Config) -> list[list[float]]:
    """Return fixed-dimension fake embeddings for each text."""
    return [[0.1, 0.2, 0.3, 0.4]] * len(texts)
