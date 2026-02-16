# Ragling: Docling-Powered Local RAG Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Fork local-rag, swap parsing/chunking for Docling, add a shared content-addressed document store so multiple per-group MCP instances share expensive conversions while keeping separate vector indexes.

**Architecture:** Shared `doc_store.sqlite` holds Docling-converted documents keyed by SHA-256 file hash. Each MCP group gets its own `index.db` with embeddings and FTS. Docling replaces PyMuPDF, python-docx, and hand-rolled parsers for PDF/DOCX/HTML/EPUB/plaintext. Legacy parsers remain for markdown (Obsidian-flavored), code (tree-sitter), email, RSS, and Calibre.

**Tech Stack:** Python 3.12+, SQLite + sqlite-vec + FTS5, Docling + docling-core, Ollama + bge-m3, Click, FastMCP.

**Design Spec:** `~/ragling/plans/declarative-discovering-phoenix.md`

---

## Task 1: Rename Package from `local_rag` to `ragling`

Rename the Python package so all imports use `ragling.*`. Work inside `local-rag/` (the git repo).

**Files:**
- Rename: `src/local_rag/` -> `src/ragling/`
- Modify: `pyproject.toml` (project name, entry point, package path)
- Modify: all `*.py` files (imports)
- Modify: all `tests/*.py` files (imports)

**Step 1: Create a feature branch**

```bash
cd ~/ragling/local-rag
git checkout -b feat/ragling-docling
```

**Step 2: Rename the source package directory**

```bash
cd ~/ragling/local-rag
mv src/local_rag src/ragling
```

**Step 3: Update all internal imports**

Find-and-replace `local_rag` -> `ragling` across all `.py` files in `src/` and `tests/`.

Every file in `src/ragling/` that imports `from local_rag.` or `import local_rag` must change to `from ragling.` / `import ragling`. Same for all test files.

Key files to update (grep for `local_rag`):
- `src/ragling/config.py` — no internal imports, but other files import from it
- `src/ragling/db.py` — `from local_rag.config import Config` -> `from ragling.config import Config`
- `src/ragling/embeddings.py` — `from local_rag.config import Config`
- `src/ragling/search.py` — imports from config, embeddings
- `src/ragling/chunker.py` — no imports to change
- `src/ragling/cli.py` — imports from config, indexers, search, embeddings
- `src/ragling/mcp_server.py` — imports from config, db, search, embeddings, indexers
- `src/ragling/parsers/*.py` — some import from each other or chunker
- `src/ragling/indexers/*.py` — import from config, db, embeddings, chunker, parsers
- `tests/test_chunker.py` — `from local_rag.chunker import ...`
- `tests/test_parsers.py` — `from local_rag.parsers.markdown import ...`
- `tests/test_search.py` — imports from config, search, db, embeddings

**Step 4: Update pyproject.toml**

```toml
[project]
name = "ragling"
version = "0.1.0"
description = "Docling-powered local RAG with shared document cache and per-group indexes"

[project.scripts]
ragling = "ragling.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

Also add `mypy` to dev dependencies:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov",
    "ruff",
    "mypy>=1.0",
]
```

**Step 5: Verify all existing tests pass**

```bash
cd ~/ragling/local-rag
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

All tests should pass with the renamed package.

**Step 6: Commit**

```bash
git add -A
git commit -m "rename: local_rag -> ragling package"
```

---

## Task 2: Add Shared Document Store (`doc_store.py`)

Content-addressed SQLite store for caching Docling conversions. Multiple MCP instances share this DB via WAL mode.

**Files:**
- Create: `src/ragling/doc_store.py`
- Create: `tests/test_doc_store.py`

**Step 1: Write failing tests for DocStore**

Create `tests/test_doc_store.py`:

```python
"""Tests for ragling.doc_store module."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ragling.doc_store import DocStore


@pytest.fixture()
def store(tmp_path: Path) -> DocStore:
    """Create a DocStore backed by a temp directory."""
    return DocStore(tmp_path / "doc_store.sqlite")


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    """Create a sample text file for testing."""
    f = tmp_path / "sample.txt"
    f.write_text("Hello, world!")
    return f


class TestDocStoreInit:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.sqlite"
        DocStore(db_path)
        assert db_path.exists()

    def test_creates_tables(self, store: DocStore) -> None:
        tables = {
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "sources" in tables
        assert "converted_documents" in tables

    def test_enables_wal_mode(self, store: DocStore) -> None:
        mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


class TestGetOrConvert:
    def test_cache_miss_calls_converter(
        self, store: DocStore, sample_file: Path
    ) -> None:
        converter = MagicMock(return_value={"mock": "document"})
        result = store.get_or_convert(sample_file, converter)
        converter.assert_called_once_with(sample_file)
        assert result == {"mock": "document"}

    def test_cache_hit_skips_converter(
        self, store: DocStore, sample_file: Path
    ) -> None:
        converter = MagicMock(return_value={"mock": "document"})
        store.get_or_convert(sample_file, converter)
        converter.reset_mock()

        result = store.get_or_convert(sample_file, converter)
        converter.assert_not_called()
        assert result == {"mock": "document"}

    def test_file_change_triggers_reconversion(
        self, store: DocStore, sample_file: Path
    ) -> None:
        converter = MagicMock(side_effect=[{"v": 1}, {"v": 2}])
        store.get_or_convert(sample_file, converter)

        # Modify the file
        sample_file.write_text("Changed content!")
        result = store.get_or_convert(sample_file, converter)
        assert converter.call_count == 2
        assert result == {"v": 2}

    def test_stores_conversion_metadata(
        self, store: DocStore, sample_file: Path
    ) -> None:
        converter = MagicMock(return_value={"data": "test"})
        store.get_or_convert(sample_file, converter)

        sources = store.list_sources()
        assert len(sources) == 1
        assert sources[0]["source_path"] == str(sample_file)
        assert sources[0]["content_hash"] is not None


class TestGetDocument:
    def test_returns_none_for_unknown_path(self, store: DocStore) -> None:
        assert store.get_document("/nonexistent") is None

    def test_returns_cached_document(
        self, store: DocStore, sample_file: Path
    ) -> None:
        converter = MagicMock(return_value={"cached": True})
        store.get_or_convert(sample_file, converter)

        result = store.get_document(str(sample_file))
        assert result == {"cached": True}


class TestInvalidate:
    def test_removes_cached_conversion(
        self, store: DocStore, sample_file: Path
    ) -> None:
        converter = MagicMock(return_value={"data": "test"})
        store.get_or_convert(sample_file, converter)

        store.invalidate(str(sample_file))
        assert store.get_document(str(sample_file)) is None

    def test_invalidate_nonexistent_is_noop(self, store: DocStore) -> None:
        store.invalidate("/does/not/exist")  # should not raise


class TestListSources:
    def test_empty_store_returns_empty(self, store: DocStore) -> None:
        assert store.list_sources() == []

    def test_lists_all_sources(
        self, store: DocStore, tmp_path: Path
    ) -> None:
        converter = MagicMock(return_value={"data": "x"})
        for i in range(3):
            f = tmp_path / f"file{i}.txt"
            f.write_text(f"content {i}")
            store.get_or_convert(f, converter)

        sources = store.list_sources()
        assert len(sources) == 3
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_doc_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'ragling.doc_store'`

**Step 3: Implement `doc_store.py`**

Create `src/ragling/doc_store.py`:

```python
"""Shared document store for caching Docling conversions.

Content-addressed SQLite store keyed by SHA-256 file hash.
Multiple MCP instances share this DB via WAL mode.
"""

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


class DocStore:
    """Content-addressed document store backed by SQLite.

    Caches Docling document conversions so multiple MCP group
    instances can share expensive conversions.
    """

    def __init__(self, db_path: Path) -> None:
        """Open or create the shared store with WAL mode.

        Args:
            db_path: Path to the SQLite database file.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                file_size INTEGER,
                file_modified_at TEXT,
                discovered_at TEXT DEFAULT (datetime('now')),
                UNIQUE(source_path)
            );

            CREATE TABLE IF NOT EXISTS converted_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                content_hash TEXT NOT NULL,
                docling_json TEXT NOT NULL,
                format TEXT NOT NULL,
                page_count INTEGER,
                conversion_time_ms INTEGER,
                converted_at TEXT DEFAULT (datetime('now')),
                UNIQUE(source_id, content_hash)
            );

            CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);
            CREATE INDEX IF NOT EXISTS idx_converted_source ON converted_documents(source_id);
        """)
        self._conn.commit()

    def get_or_convert(
        self, path: Path, converter: Callable[[Path], Any]
    ) -> Any:
        """Content-addressed lookup with fallback to conversion.

        Returns cached document if file hash matches. Otherwise calls
        converter, stores result, and returns it.

        Args:
            path: Path to the source file.
            converter: Callable that takes a Path and returns a
                JSON-serializable document object.

        Returns:
            The converted document (from cache or fresh conversion).
        """
        content_hash = _file_hash(path)
        source_path = str(path)
        stat = path.stat()

        # Check for existing source with matching hash
        row = self._conn.execute(
            "SELECT id FROM sources WHERE source_path = ? AND content_hash = ?",
            (source_path, content_hash),
        ).fetchone()

        if row:
            source_id = row["id"]
            cached = self._conn.execute(
                "SELECT docling_json FROM converted_documents "
                "WHERE source_id = ? AND content_hash = ?",
                (source_id, content_hash),
            ).fetchone()
            if cached:
                logger.debug("Cache hit for %s", path.name)
                return json.loads(cached["docling_json"])

        # Cache miss — convert
        logger.info("Converting %s (cache miss)", path.name)
        start = time.monotonic()
        document = converter(path)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Upsert source row
        self._conn.execute(
            "INSERT INTO sources (source_path, content_hash, file_size, file_modified_at) "
            "VALUES (?, ?, ?, datetime(?, 'unixepoch')) "
            "ON CONFLICT(source_path) DO UPDATE SET "
            "content_hash = excluded.content_hash, "
            "file_size = excluded.file_size, "
            "file_modified_at = excluded.file_modified_at",
            (source_path, content_hash, stat.st_size, int(stat.st_mtime)),
        )

        source_id = self._conn.execute(
            "SELECT id FROM sources WHERE source_path = ?", (source_path,)
        ).fetchone()["id"]

        # Delete old conversion for this source (file changed)
        self._conn.execute(
            "DELETE FROM converted_documents WHERE source_id = ? AND content_hash != ?",
            (source_id, content_hash),
        )

        # Store new conversion
        doc_json = json.dumps(document)
        fmt = path.suffix.lstrip(".").lower() or "unknown"
        self._conn.execute(
            "INSERT OR REPLACE INTO converted_documents "
            "(source_id, content_hash, docling_json, format, conversion_time_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, content_hash, doc_json, fmt, elapsed_ms),
        )
        self._conn.commit()

        return document

    def get_document(self, source_path: str) -> Any | None:
        """Retrieve cached conversion by source path.

        Args:
            source_path: The original file path.

        Returns:
            The cached document, or None if not found.
        """
        row = self._conn.execute(
            "SELECT cd.docling_json FROM converted_documents cd "
            "JOIN sources s ON cd.source_id = s.id "
            "WHERE s.source_path = ? AND s.content_hash = cd.content_hash",
            (source_path,),
        ).fetchone()

        if row:
            return json.loads(row["docling_json"])
        return None

    def invalidate(self, source_path: str) -> None:
        """Remove cached conversion for a source path.

        Args:
            source_path: The original file path to invalidate.
        """
        row = self._conn.execute(
            "SELECT id FROM sources WHERE source_path = ?", (source_path,)
        ).fetchone()
        if row:
            self._conn.execute(
                "DELETE FROM converted_documents WHERE source_id = ?",
                (row["id"],),
            )
            self._conn.execute(
                "DELETE FROM sources WHERE id = ?", (row["id"],)
            )
            self._conn.commit()

    def list_sources(self) -> list[dict[str, Any]]:
        """List all known sources with conversion status.

        Returns:
            List of dicts with source_path, content_hash, file_size,
            discovered_at, and has_conversion keys.
        """
        rows = self._conn.execute(
            "SELECT s.source_path, s.content_hash, s.file_size, "
            "s.discovered_at, "
            "(SELECT COUNT(*) FROM converted_documents cd "
            " WHERE cd.source_id = s.id) as conversion_count "
            "FROM sources s ORDER BY s.discovered_at"
        ).fetchall()

        return [
            {
                "source_path": row["source_path"],
                "content_hash": row["content_hash"],
                "file_size": row["file_size"],
                "discovered_at": row["discovered_at"],
                "has_conversion": row["conversion_count"] > 0,
            }
            for row in rows
        ]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_doc_store.py -v
```

Expected: all pass.

**Step 5: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 6: Commit**

```bash
git add src/ragling/doc_store.py tests/test_doc_store.py
git commit -m "feat: add shared document store (content-addressed SQLite cache)"
```

---

## Task 3: Add Docling Conversion Wrapper (`docling_convert.py`)

Wraps Docling's DocumentConverter and HybridChunker. Since Docling is a heavy ML dependency, tests mock the Docling API and test our integration logic.

**Files:**
- Modify: `pyproject.toml` (add docling dependencies)
- Create: `src/ragling/docling_convert.py`
- Create: `tests/test_docling_convert.py`

**Step 1: Add docling dependencies to pyproject.toml**

Add to `[project] dependencies`:
```
"docling>=2.66.0",
"docling-core>=2.56.0",
```

Then sync:
```bash
cd ~/ragling/local-rag
uv sync
```

**Step 2: Write failing tests**

Create `tests/test_docling_convert.py`:

```python
"""Tests for ragling.docling_convert module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ragling.chunker import Chunk
from ragling.doc_store import DocStore


@pytest.fixture()
def store(tmp_path: Path) -> DocStore:
    return DocStore(tmp_path / "doc_store.sqlite")


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    f = tmp_path / "test.pdf"
    f.write_bytes(b"%PDF-1.4 fake content")
    return f


class TestConvertAndChunk:
    def test_returns_list_of_chunks(
        self, store: DocStore, sample_file: Path
    ) -> None:
        """convert_and_chunk returns a list of Chunk dataclass instances."""
        from ragling.docling_convert import convert_and_chunk

        with patch("ragling.docling_convert.get_converter") as mock_conv:
            # Mock the Docling conversion pipeline
            mock_doc = MagicMock()
            mock_result = MagicMock()
            mock_result.document = mock_doc
            mock_conv.return_value.convert.return_value = mock_result

            # Mock HybridChunker
            mock_chunk = MagicMock()
            mock_chunk.text = "chunk text"
            mock_chunk.meta.headings = ["Section 1"]

            with patch("ragling.docling_convert.HybridChunker") as mock_chunker_cls:
                mock_chunker = MagicMock()
                mock_chunker.chunk.return_value = [mock_chunk]
                mock_chunker.contextualize.return_value = "Section 1\nchunk text"
                mock_chunker_cls.return_value = mock_chunker

                chunks = convert_and_chunk(sample_file, store)

        assert len(chunks) == 1
        assert isinstance(chunks[0], Chunk)
        assert chunks[0].text == "Section 1\nchunk text"
        assert chunks[0].title == "test.pdf"
        assert chunks[0].chunk_index == 0

    def test_uses_doc_store_cache(
        self, store: DocStore, sample_file: Path
    ) -> None:
        """Second call for same file should hit doc_store cache."""
        from ragling.docling_convert import convert_and_chunk

        with patch("ragling.docling_convert.get_converter") as mock_conv:
            mock_doc = MagicMock()
            mock_result = MagicMock()
            mock_result.document = mock_doc

            # Make the mock JSON-serializable for doc_store caching
            mock_doc_data = {"type": "mock_doc", "texts": ["hello"]}
            mock_conv.return_value.convert.return_value = mock_result

            with patch("ragling.docling_convert.HybridChunker") as mock_chunker_cls:
                mock_chunk = MagicMock()
                mock_chunk.text = "text"
                mock_chunk.meta.headings = []
                mock_chunker = MagicMock()
                mock_chunker.chunk.return_value = [mock_chunk]
                mock_chunker.contextualize.return_value = "text"
                mock_chunker_cls.return_value = mock_chunker

                convert_and_chunk(sample_file, store)
                convert_and_chunk(sample_file, store)

        # Converter should only be called once (second call hits cache)
        assert mock_conv.return_value.convert.call_count == 1

    def test_chunk_metadata_includes_source_path(
        self, store: DocStore, sample_file: Path
    ) -> None:
        from ragling.docling_convert import convert_and_chunk

        with patch("ragling.docling_convert.get_converter") as mock_conv:
            mock_doc = MagicMock()
            mock_result = MagicMock()
            mock_result.document = mock_doc
            mock_conv.return_value.convert.return_value = mock_result

            with patch("ragling.docling_convert.HybridChunker") as mock_chunker_cls:
                mock_chunk = MagicMock()
                mock_chunk.text = "text"
                mock_chunk.meta.headings = ["H1"]
                mock_chunker = MagicMock()
                mock_chunker.chunk.return_value = [mock_chunk]
                mock_chunker.contextualize.return_value = "H1\ntext"
                mock_chunker_cls.return_value = mock_chunker

                chunks = convert_and_chunk(sample_file, store)

        assert chunks[0].metadata["source_path"] == str(sample_file)
        assert chunks[0].metadata["headings"] == ["H1"]


class TestDoclingFormats:
    """Test the DOCLING_FORMATS set and format detection."""

    def test_docling_formats_set_exists(self) -> None:
        from ragling.docling_convert import DOCLING_FORMATS

        assert "pdf" in DOCLING_FORMATS
        assert "docx" in DOCLING_FORMATS
        assert "html" in DOCLING_FORMATS
        assert "epub" in DOCLING_FORMATS
        assert "plaintext" in DOCLING_FORMATS

    def test_markdown_not_in_docling_formats(self) -> None:
        from ragling.docling_convert import DOCLING_FORMATS

        assert "markdown" not in DOCLING_FORMATS

    def test_code_not_in_docling_formats(self) -> None:
        from ragling.docling_convert import DOCLING_FORMATS

        assert "code" not in DOCLING_FORMATS
```

**Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_docling_convert.py -v
```

Expected: `ModuleNotFoundError: No module named 'ragling.docling_convert'`

**Step 4: Implement `docling_convert.py`**

Create `src/ragling/docling_convert.py`:

```python
"""Docling document conversion and chunking wrapper.

Wraps Docling's DocumentConverter for format conversion and
HybridChunker for structure-aware chunking. Integrates with
DocStore for content-addressed caching.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker

from ragling.chunker import Chunk
from ragling.doc_store import DocStore

logger = logging.getLogger(__name__)

# Formats that Docling handles (vs. legacy parsers)
DOCLING_FORMATS: frozenset[str] = frozenset({
    "pdf", "docx", "pptx", "xlsx", "html", "epub",
    "plaintext", "latex", "image", "csv", "asciidoc",
})


@lru_cache
def get_converter() -> DocumentConverter:
    """Get or create the Docling DocumentConverter singleton."""
    return DocumentConverter()


def _convert_with_docling(path: Path) -> Any:
    """Convert a file using Docling and return serializable dict.

    Args:
        path: Path to the document file.

    Returns:
        A JSON-serializable representation of the DoclingDocument.
    """
    result = get_converter().convert(str(path))
    doc = result.document
    # Serialize to dict for JSON storage in DocStore
    return doc.model_dump()


def convert_and_chunk(
    path: Path,
    doc_store: DocStore,
    chunk_max_tokens: int = 256,
    embedding_model_id: str = "BAAI/bge-m3",
) -> list[Chunk]:
    """Convert a document via Docling (cached in doc_store), chunk with HybridChunker.

    Args:
        path: Path to the source document.
        doc_store: Shared document store for caching conversions.
        chunk_max_tokens: Maximum tokens per chunk.
        embedding_model_id: HuggingFace model ID for tokenizer alignment.

    Returns:
        List of Chunk dataclass instances ready for embedding.
    """
    # 1. Get or convert (content-addressed via doc_store)
    doc_data = doc_store.get_or_convert(path, _convert_with_docling)

    # 2. Reconstruct DoclingDocument from cached data
    from docling_core.types.doc import DoclingDocument

    doc = DoclingDocument.model_validate(doc_data)

    # 3. Chunk with HybridChunker
    chunker = HybridChunker(
        tokenizer=embedding_model_id,
        max_tokens=chunk_max_tokens,
    )
    doc_chunks = list(chunker.chunk(doc))

    # 4. Map to ragling Chunk format
    chunks: list[Chunk] = []
    for i, dc in enumerate(doc_chunks):
        chunks.append(
            Chunk(
                text=chunker.contextualize(dc),
                title=path.name,
                metadata={
                    "headings": dc.meta.headings if dc.meta else [],
                    "source_path": str(path),
                },
                chunk_index=i,
            )
        )

    return chunks
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_docling_convert.py -v
```

Note: The mocked tests should pass. If Docling import causes issues at import time, we may need to adjust the mocking strategy (e.g., mock at module level or use `importlib`). Fix any import-time issues.

**Step 6: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 7: Commit**

```bash
git add src/ragling/docling_convert.py tests/test_docling_convert.py pyproject.toml uv.lock
git commit -m "feat: add Docling conversion wrapper with HybridChunker"
```

---

## Task 4: Add Group-Aware Config (`config.py`)

Add `shared_db_path`, `group_name`, and `group_db_dir` fields to Config.

**Files:**
- Modify: `src/ragling/config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing tests**

Create `tests/test_config.py`:

```python
"""Tests for ragling.config module."""

import json
from pathlib import Path

import pytest

from ragling.config import Config, load_config


class TestConfigDefaults:
    def test_default_shared_db_path(self) -> None:
        config = Config()
        assert config.shared_db_path == Path("~/.ragling/doc_store.sqlite").expanduser()

    def test_default_group_name(self) -> None:
        config = Config()
        assert config.group_name == "default"

    def test_default_group_db_dir(self) -> None:
        config = Config()
        assert config.group_db_dir == Path("~/.ragling/groups/").expanduser()

    def test_group_index_db_path(self) -> None:
        config = Config(group_name="personal")
        expected = config.group_db_dir / "personal" / "index.db"
        assert config.group_index_db_path == expected


class TestConfigFromJson:
    def test_loads_group_fields_from_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "shared_db_path": str(tmp_path / "shared.sqlite"),
            "group_name": "work",
            "group_db_dir": str(tmp_path / "groups"),
        }))

        config = load_config(config_file)
        assert config.shared_db_path == tmp_path / "shared.sqlite"
        assert config.group_name == "work"
        assert config.group_db_dir == tmp_path / "groups"

    def test_missing_group_fields_use_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"embedding_model": "bge-m3"}))

        config = load_config(config_file)
        assert config.group_name == "default"
        assert "ragling" in str(config.shared_db_path)
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `AttributeError: ... has no attribute 'shared_db_path'`

**Step 3: Implement config changes**

Modify `src/ragling/config.py`:

Add fields to Config dataclass:
```python
shared_db_path: Path = field(
    default_factory=lambda: Path.home() / ".ragling" / "doc_store.sqlite"
)
group_name: str = "default"
group_db_dir: Path = field(
    default_factory=lambda: Path.home() / ".ragling" / "groups"
)

@property
def group_index_db_path(self) -> Path:
    """Path to this group's per-group index database."""
    return self.group_db_dir / self.group_name / "index.db"
```

Update `load_config()` to read the new fields:
```python
shared_db_path=_expand_path(
    data.get("shared_db_path", str(Path.home() / ".ragling" / "doc_store.sqlite"))
),
group_name=data.get("group_name", "default"),
group_db_dir=_expand_path(
    data.get("group_db_dir", str(Path.home() / ".ragling" / "groups"))
),
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

**Step 5: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 6: Commit**

```bash
git add src/ragling/config.py tests/test_config.py
git commit -m "feat: add group-aware config fields (shared_db_path, group_name, group_db_dir)"
```

---

## Task 5: Make `db.py` Accept Explicit Path

Currently `get_connection()` takes a Config and uses `config.db_path`. We need it to work with both the legacy single-DB path and the new per-group path.

**Files:**
- Modify: `src/ragling/db.py`
- Add tests to: `tests/test_config.py` (or create `tests/test_db.py`)

**Step 1: Write failing tests**

Add to `tests/test_config.py` or create `tests/test_db.py`:

```python
"""Tests for ragling.db module."""

import sqlite3
from pathlib import Path

import pytest

from ragling.config import Config


class TestGetConnection:
    def test_uses_group_index_db_path_when_group_set(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            group_name="test-group",
            group_db_dir=tmp_path / "groups",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            expected_path = tmp_path / "groups" / "test-group" / "index.db"
            assert expected_path.exists()
        finally:
            conn.close()

    def test_falls_back_to_db_path_for_default_group(self, tmp_path: Path) -> None:
        from ragling.db import get_connection

        config = Config(
            db_path=tmp_path / "legacy.db",
            group_name="default",
            embedding_dimensions=4,
        )
        conn = get_connection(config)
        try:
            assert (tmp_path / "legacy.db").exists()
        finally:
            conn.close()
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_db.py -v
```

**Step 3: Modify `db.py`**

Update `get_connection()` to use `config.group_index_db_path` when group is not "default":

```python
def get_connection(config: Config) -> sqlite3.Connection:
    """Open a SQLite connection with sqlite-vec loaded and pragmas set."""
    if config.group_name != "default":
        db_path = config.group_index_db_path
    else:
        db_path = config.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    return conn
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_db.py -v
```

**Step 5: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 6: Commit**

```bash
git add src/ragling/db.py tests/test_db.py
git commit -m "feat: db.get_connection uses per-group index path when group is set"
```

---

## Task 6: Update `_parse_and_chunk()` Dispatch in `indexers/project.py`

Route Docling-handled formats through `convert_and_chunk()`, keep legacy dispatch for markdown/code.

**Files:**
- Modify: `src/ragling/indexers/project.py`
- Create: `tests/test_project_indexer.py`

**Step 1: Write failing tests**

Create `tests/test_project_indexer.py`:

```python
"""Tests for ragling.indexers.project module — format routing."""

import pytest

from ragling.indexers.project import _EXTENSION_MAP, DOCLING_FORMATS


class TestExtensionMap:
    def test_pdf_maps_to_pdf(self) -> None:
        assert _EXTENSION_MAP[".pdf"] == "pdf"

    def test_docx_maps_to_docx(self) -> None:
        assert _EXTENSION_MAP[".docx"] == "docx"

    def test_pptx_maps_to_pptx(self) -> None:
        assert _EXTENSION_MAP[".pptx"] == "pptx"

    def test_xlsx_maps_to_xlsx(self) -> None:
        assert _EXTENSION_MAP[".xlsx"] == "xlsx"

    def test_tex_maps_to_latex(self) -> None:
        assert _EXTENSION_MAP[".tex"] == "latex"

    def test_png_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".png"] == "image"

    def test_jpg_maps_to_image(self) -> None:
        assert _EXTENSION_MAP[".jpg"] == "image"

    def test_md_maps_to_markdown(self) -> None:
        assert _EXTENSION_MAP[".md"] == "markdown"

    def test_adoc_maps_to_asciidoc(self) -> None:
        assert _EXTENSION_MAP[".adoc"] == "asciidoc"


class TestDoclingFormats:
    def test_pdf_is_docling_format(self) -> None:
        assert "pdf" in DOCLING_FORMATS

    def test_markdown_is_not_docling_format(self) -> None:
        assert "markdown" not in DOCLING_FORMATS

    def test_all_docling_extensions_have_mapping(self) -> None:
        """Every format in DOCLING_FORMATS should have at least one extension mapping to it."""
        mapped_formats = set(_EXTENSION_MAP.values())
        for fmt in DOCLING_FORMATS:
            assert fmt in mapped_formats, f"DOCLING_FORMATS has '{fmt}' but no extension maps to it"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_project_indexer.py -v
```

Expected: `ImportError` because `DOCLING_FORMATS` doesn't exist yet in `project.py`.

**Step 3: Update `indexers/project.py`**

Add the new extension mappings and DOCLING_FORMATS set. Update `_parse_and_chunk()` to accept an optional `doc_store` parameter and route Docling formats through `convert_and_chunk()`.

Key changes:

```python
from ragling.doc_store import DocStore
from ragling.docling_convert import DOCLING_FORMATS, convert_and_chunk

# Updated extension map
_EXTENSION_MAP: dict[str, str] = {
    # Docling-handled formats
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".epub": "epub",
    ".txt": "plaintext",
    ".tex": "latex",
    ".latex": "latex",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".csv": "csv",
    ".adoc": "asciidoc",
    # Legacy-handled formats
    ".md": "markdown",
    ".json": "plaintext",
    ".yaml": "plaintext",
    ".yml": "plaintext",
}

# Re-export for use by obsidian indexer and elsewhere
# (DOCLING_FORMATS is defined in docling_convert.py)


def _parse_and_chunk(
    path: Path, source_type: str, config: Config,
    doc_store: DocStore | None = None,
) -> list[Chunk]:
    """Parse a file and return chunks based on its type."""
    if source_type in DOCLING_FORMATS and doc_store is not None:
        return convert_and_chunk(path, doc_store)

    # Legacy paths (markdown, code, etc.) — unchanged
    # ... existing code ...
```

Update `ProjectIndexer.__init__` and `_index_file` to accept and pass `doc_store`.

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_project_indexer.py -v
```

**Step 5: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 6: Commit**

```bash
git add src/ragling/indexers/project.py tests/test_project_indexer.py
git commit -m "feat: route Docling-handled formats through convert_and_chunk in project indexer"
```

---

## Task 7: Route Obsidian Attachments Through Docling

**Files:**
- Modify: `src/ragling/indexers/obsidian.py`

**Step 1: Write a test for Docling routing in obsidian indexer**

Add to `tests/test_project_indexer.py` or create a small test:

```python
class TestObsidianDoclingRouting:
    def test_obsidian_imports_docling_formats(self) -> None:
        """ObsidianIndexer uses the shared extension map and DOCLING_FORMATS."""
        from ragling.indexers.obsidian import _index_file
        from ragling.indexers.project import DOCLING_FORMATS, _EXTENSION_MAP

        # PDF should route through Docling
        assert _EXTENSION_MAP[".pdf"] == "pdf"
        assert "pdf" in DOCLING_FORMATS
```

**Step 2: Modify `indexers/obsidian.py`**

Update `_index_file()` to accept a `doc_store` parameter and pass it through to `_parse_and_chunk()`.

Update `ObsidianIndexer.index()` to accept a `doc_store` parameter.

The key change is threading `doc_store` through so PDF/DOCX/HTML attachments in vaults go through Docling.

```python
def _index_file(
    conn: sqlite3.Connection,
    config: Config,
    collection_id: int,
    file_path: Path,
    force: bool,
    doc_store: DocStore | None = None,
) -> str:
    ...
    chunks = _parse_and_chunk(file_path, source_type, config, doc_store=doc_store)
    ...
```

**Step 3: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 4: Commit**

```bash
git add src/ragling/indexers/obsidian.py
git commit -m "feat: route Obsidian vault attachments through Docling"
```

---

## Task 8: Add `--group` Flag to CLI

**Files:**
- Modify: `src/ragling/cli.py`

**Step 1: Write failing test**

Add to existing test structure or create `tests/test_cli.py`:

```python
"""Tests for ragling CLI group flag."""

from click.testing import CliRunner

from ragling.cli import main


class TestGroupFlag:
    def test_serve_accepts_group_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--group", "test", "--help"])
        # --help should work without errors
        assert result.exit_code == 0

    def test_index_project_accepts_group_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["index", "project", "--help"])
        assert result.exit_code == 0
```

**Step 2: Modify `cli.py`**

Add `--group` option to the main group (so it's available to all subcommands):

```python
@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.option("--group", "-g", default="default", show_default=True,
              help="Group name for per-group indexes.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, group: str) -> None:
    """ragling: Docling-powered local RAG with shared document cache."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["group"] = group
```

Update `serve` command:

```python
@main.command()
@click.option("--port", type=int, default=None,
              help="Port for HTTP/SSE transport. If omitted, uses stdio.")
@click.pass_context
def serve(ctx: click.Context, port: int | None) -> None:
    """Start the MCP server."""
    from ragling.mcp_server import create_server

    group = ctx.obj["group"]
    server = create_server(group_name=group)

    if port:
        click.echo(f"Starting MCP server on port {port} (group: {group})...")
        server.run(transport="sse", port=port)
    else:
        server.run(transport="stdio")
```

Update `_get_db()` to use group from context:

```python
def _get_db(config):
    """Get initialized database connection."""
    from ragling.db import get_connection, init_db
    conn = get_connection(config)
    init_db(conn, config)
    return conn
```

Thread group name through all index commands by reading from context and setting `config.group_name` before calling `_get_db()`.

**Step 3: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 4: Commit**

```bash
git add src/ragling/cli.py tests/test_cli.py
git commit -m "feat: add --group flag to CLI for per-group indexes"
```

---

## Task 9: Update MCP Server with Group Config and Doc Store Info Tool

**Files:**
- Modify: `src/ragling/mcp_server.py`

**Step 1: Write failing test**

```python
class TestMcpServer:
    def test_create_server_accepts_group_name(self) -> None:
        from ragling.mcp_server import create_server
        server = create_server(group_name="test")
        assert server is not None
```

**Step 2: Modify `mcp_server.py`**

Update `create_server()` to accept `group_name` parameter. Pass it to config loading so the right per-group DB is used.

Add `rag_doc_store_info` tool:

```python
@mcp.tool()
def rag_doc_store_info() -> list[dict[str, Any]]:
    """List all documents in the shared document cache.

    Shows all source files that have been converted by Docling,
    regardless of which group indexed them. Useful for checking
    what's cached and avoiding redundant conversions.
    """
    from ragling.doc_store import DocStore

    config = load_config()
    store = DocStore(config.shared_db_path)
    try:
        return store.list_sources()
    finally:
        store.close()
```

**Step 3: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 4: Commit**

```bash
git add src/ragling/mcp_server.py
git commit -m "feat: add rag_doc_store_info tool and group-aware MCP server"
```

---

## Task 10: Update `pyproject.toml` — Swap Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Remove replaced dependencies**

Remove from `dependencies`:
- `pymupdf>=1.24.0`
- `python-docx>=1.1.0`

These are replaced by Docling (already added in Task 3).

**Step 2: Sync and verify**

```bash
uv sync
uv run pytest
```

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: remove pymupdf and python-docx (replaced by Docling)"
```

---

## Task 11: Delete Replaced Parsers

**Files:**
- Delete: `src/ragling/parsers/pdf.py`
- Delete: `src/ragling/parsers/docx.py`
- Delete: `src/ragling/parsers/epub.py`
- Delete: `src/ragling/parsers/html.py`
- Delete: `src/ragling/parsers/plaintext.py`

**Step 1: Verify no remaining imports**

```bash
cd ~/ragling/local-rag
grep -rn "from ragling.parsers.pdf" src/ tests/
grep -rn "from ragling.parsers.docx" src/ tests/
grep -rn "from ragling.parsers.epub" src/ tests/
grep -rn "from ragling.parsers.html" src/ tests/
grep -rn "from ragling.parsers.plaintext" src/ tests/
```

Remove any remaining imports of these modules from `indexers/project.py` (the legacy import lines at the top that are no longer used since those formats now route through Docling).

**Step 2: Delete the files**

```bash
rm src/ragling/parsers/pdf.py
rm src/ragling/parsers/docx.py
rm src/ragling/parsers/epub.py
rm src/ragling/parsers/html.py
rm src/ragling/parsers/plaintext.py
```

**Step 3: Update `parsers/__init__.py`**

Remove any re-exports of deleted modules.

**Step 4: Run full verification**

```bash
uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .
```

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: delete parsers replaced by Docling (pdf, docx, epub, html, plaintext)"
```

---

## Task 12: Final Verification and Integration Test

**Step 1: Run full test suite**

```bash
cd ~/ragling/local-rag
uv run pytest -v
```

**Step 2: Run type checker**

```bash
uv run mypy src/
```

**Step 3: Run linter and formatter**

```bash
uv run ruff check .
uv run ruff format --check .
```

**Step 4: Verify CLI entry point works**

```bash
uv run ragling --help
uv run ragling index --help
uv run ragling serve --help
```

**Step 5: Check git log is clean**

```bash
git log --oneline feat/ragling-docling
```

---

## Implementation Notes

- **Pause after each task** for user review before continuing to the next.
- **TDD strictly**: write failing test, make it pass, then refactor.
- **All four checks must pass** before any task is considered complete: `uv run pytest && uv run mypy src/ && uv run ruff check . && uv run ruff format --check .`
- **Docling tests are mocked** since Docling requires ML model downloads. Integration tests with real Docling conversion happen in Task 12 / manual testing.
- **The `doc_store` parameter is optional** throughout the indexer chain (defaulting to `None`). When `None`, Docling formats fall through to legacy parsers (backwards compatibility during migration). When provided, they route through Docling.
