"""Tests for ragling.indexers.calibre_indexer module.

Tests are split into two categories:
1. Unit tests for internal functions (_build_book_metadata, _metadata_changed,
   _refresh_metadata, _extract_and_chunk_book) that do NOT require calibredb CLI.
2. Integration tests for CalibreIndexer.index() with a real SQLite DB and
   mock Calibre library on disk.

Since calibredb CLI is not required for the actual indexer (it reads metadata.db
directly), we can test the full flow by constructing a fake Calibre library
directory structure with a metadata.db file.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from ragling.chunker import Chunk
from ragling.config import Config
from ragling.db import get_connection, get_or_create_collection, init_db
from ragling.indexers.base import upsert_source_with_chunks
from ragling.parsers.calibre import CalibreBook, get_book_file_path

# Sentinel for distinguishing "not provided" from explicit empty list/dict
_UNSET: Any = object()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create an initialized test DB with small embedding dimensions."""
    config = Config(
        db_path=tmp_path / "test.db",
        embedding_dimensions=4,
    )
    conn = get_connection(config)
    init_db(conn, config)
    return conn


def _make_config(tmp_path: Path) -> Config:
    """Create a Config suitable for testing."""
    return Config(
        db_path=tmp_path / "test.db",
        embedding_dimensions=4,
        chunk_size_tokens=256,
    )


def _make_book(
    book_id: int = 1,
    title: str = "Test Book",
    authors: Any = _UNSET,
    tags: Any = _UNSET,
    series: str | None = None,
    series_index: float | None = None,
    publisher: str | None = None,
    pubdate: str | None = None,
    rating: int | None = None,
    languages: Any = _UNSET,
    identifiers: Any = _UNSET,
    description: str | None = None,
    formats: Any = _UNSET,
    relative_path: str = "Author/Test Book (1)",
    last_modified: str = "2025-01-01T00:00:00",
) -> CalibreBook:
    """Create a CalibreBook with sensible defaults for testing.

    Uses a sentinel value so callers can explicitly pass empty lists/dicts
    and have them honored, rather than being replaced by defaults.
    """
    return CalibreBook(
        book_id=book_id,
        title=title,
        authors=["Test Author"] if authors is _UNSET else authors,
        tags=["fiction"] if tags is _UNSET else tags,
        series=series,
        series_index=series_index,
        publisher=publisher,
        pubdate=pubdate,
        rating=rating,
        languages=["eng"] if languages is _UNSET else languages,
        identifiers={} if identifiers is _UNSET else identifiers,
        description=description,
        formats={} if formats is _UNSET else formats,
        relative_path=relative_path,
        last_modified=last_modified,
    )


def _create_calibre_metadata_db(library_path: Path, books: list[dict]) -> None:
    """Create a minimal Calibre metadata.db with the given books.

    Each book dict should have keys: id, title, path, and optionally:
    pubdate, last_modified, authors, tags, series, series_index, publisher,
    rating, languages, identifiers, comments, formats.
    """
    db_path = library_path / "metadata.db"
    # Remove existing DB if present (for re-create scenarios)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            path TEXT NOT NULL,
            pubdate TEXT,
            last_modified TEXT,
            series_index REAL
        );
        CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE books_authors_link (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            author INTEGER NOT NULL
        );
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE books_tags_link (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            tag INTEGER NOT NULL
        );
        CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE books_series_link (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            series INTEGER NOT NULL
        );
        CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE books_publishers_link (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            publisher INTEGER NOT NULL
        );
        CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INTEGER NOT NULL);
        CREATE TABLE books_ratings_link (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            rating INTEGER NOT NULL
        );
        CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT NOT NULL);
        CREATE TABLE books_languages_link (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            lang_code INTEGER NOT NULL
        );
        CREATE TABLE identifiers (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            type TEXT NOT NULL,
            val TEXT NOT NULL
        );
        CREATE TABLE comments (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE TABLE data (
            id INTEGER PRIMARY KEY,
            book INTEGER NOT NULL,
            format TEXT NOT NULL,
            name TEXT NOT NULL
        );
    """
    )

    author_counter = 0
    tag_counter = 0
    series_counter = 0
    pub_counter = 0
    rating_counter = 0
    lang_counter = 0
    ident_counter = 0
    link_counter = 0
    fmt_counter = 0

    for book in books:
        conn.execute(
            "INSERT INTO books (id, title, path, pubdate, last_modified, series_index) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                book["id"],
                book["title"],
                book["path"],
                book.get("pubdate"),
                book.get("last_modified", "2025-01-01T00:00:00"),
                book.get("series_index"),
            ),
        )

        for author_name in book.get("authors", []):
            author_counter += 1
            conn.execute(
                "INSERT INTO authors (id, name) VALUES (?, ?)",
                (author_counter, author_name),
            )
            link_counter += 1
            conn.execute(
                "INSERT INTO books_authors_link (id, book, author) VALUES (?, ?, ?)",
                (link_counter, book["id"], author_counter),
            )

        for tag_name in book.get("tags", []):
            tag_counter += 1
            conn.execute(
                "INSERT INTO tags (id, name) VALUES (?, ?)",
                (tag_counter, tag_name),
            )
            link_counter += 1
            conn.execute(
                "INSERT INTO books_tags_link (id, book, tag) VALUES (?, ?, ?)",
                (link_counter, book["id"], tag_counter),
            )

        if "series" in book:
            series_counter += 1
            conn.execute(
                "INSERT INTO series (id, name) VALUES (?, ?)",
                (series_counter, book["series"]),
            )
            link_counter += 1
            conn.execute(
                "INSERT INTO books_series_link (id, book, series) VALUES (?, ?, ?)",
                (link_counter, book["id"], series_counter),
            )

        if "publisher" in book:
            pub_counter += 1
            conn.execute(
                "INSERT INTO publishers (id, name) VALUES (?, ?)",
                (pub_counter, book["publisher"]),
            )
            link_counter += 1
            conn.execute(
                "INSERT INTO books_publishers_link (id, book, publisher) VALUES (?, ?, ?)",
                (link_counter, book["id"], pub_counter),
            )

        if "rating" in book:
            rating_counter += 1
            conn.execute(
                "INSERT INTO ratings (id, rating) VALUES (?, ?)",
                (rating_counter, book["rating"]),
            )
            link_counter += 1
            conn.execute(
                "INSERT INTO books_ratings_link (id, book, rating) VALUES (?, ?, ?)",
                (link_counter, book["id"], rating_counter),
            )

        for lang in book.get("languages", []):
            lang_counter += 1
            conn.execute(
                "INSERT INTO languages (id, lang_code) VALUES (?, ?)",
                (lang_counter, lang),
            )
            link_counter += 1
            conn.execute(
                "INSERT INTO books_languages_link (id, book, lang_code) VALUES (?, ?, ?)",
                (link_counter, book["id"], lang_counter),
            )

        for id_type, id_val in book.get("identifiers", {}).items():
            ident_counter += 1
            conn.execute(
                "INSERT INTO identifiers (id, book, type, val) VALUES (?, ?, ?, ?)",
                (ident_counter, book["id"], id_type, id_val),
            )

        if "comments" in book:
            conn.execute(
                "INSERT INTO comments (id, book, text) VALUES (?, ?, ?)",
                (book["id"], book["id"], book["comments"]),
            )

        for fmt, name in book.get("formats", {}).items():
            fmt_counter += 1
            conn.execute(
                "INSERT INTO data (id, book, format, name) VALUES (?, ?, ?, ?)",
                (fmt_counter, book["id"], fmt, name),
            )

    conn.commit()
    conn.close()


def _create_epub_file(path: Path) -> None:
    """Create a minimal fake EPUB file at the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK\x03\x04fake epub content for testing")


def _create_pdf_file(path: Path) -> None:
    """Create a minimal fake PDF file at the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake pdf content for testing")


# ---------------------------------------------------------------------------
# Tests for _build_book_metadata
# ---------------------------------------------------------------------------


class TestBuildBookMetadata:
    """Tests for the _build_book_metadata helper function."""

    def test_includes_all_populated_fields(self) -> None:
        """Metadata dict includes all non-None/non-empty fields from the book."""
        from ragling.indexers.calibre_indexer import _build_book_metadata

        book = _make_book(
            authors=["Author A", "Author B"],
            tags=["sci-fi", "adventure"],
            series="My Series",
            series_index=2.0,
            publisher="Test Publisher",
            pubdate="2024-06-15",
            rating=8,
            languages=["eng", "fra"],
            identifiers={"isbn": "1234567890"},
        )
        meta = _build_book_metadata(book, Path("/lib"), "epub")

        assert meta["authors"] == ["Author A", "Author B"]
        assert meta["tags"] == ["sci-fi", "adventure"]
        assert meta["series"] == "My Series"
        assert meta["series_index"] == 2.0
        assert meta["publisher"] == "Test Publisher"
        assert meta["pubdate"] == "2024-06-15"
        assert meta["rating"] == 8
        assert meta["languages"] == ["eng", "fra"]
        assert meta["identifiers"] == {"isbn": "1234567890"}
        assert meta["calibre_id"] == 1
        assert meta["format"] == "epub"
        assert meta["library"] == "/lib"

    def test_skips_none_and_empty_fields(self) -> None:
        """Metadata dict omits fields that are None or empty."""
        from ragling.indexers.calibre_indexer import _build_book_metadata

        book = _make_book(
            authors=[],
            tags=[],
            series=None,
            series_index=None,
            publisher=None,
            pubdate=None,
            rating=None,
            languages=[],
            identifiers={},
        )
        meta = _build_book_metadata(book, Path("/lib"), None)

        assert "authors" not in meta
        assert "tags" not in meta
        assert "series" not in meta
        assert "series_index" not in meta
        assert "publisher" not in meta
        assert "pubdate" not in meta
        assert "rating" not in meta
        assert "languages" not in meta
        assert "identifiers" not in meta
        assert "format" not in meta
        # These are always present
        assert meta["calibre_id"] == 1
        assert meta["library"] == "/lib"

    def test_format_none_omits_format_key(self) -> None:
        """When fmt is None (description-only), 'format' key is absent."""
        from ragling.indexers.calibre_indexer import _build_book_metadata

        book = _make_book()
        meta = _build_book_metadata(book, Path("/lib"), None)

        assert "format" not in meta

    def test_rating_zero_is_included(self) -> None:
        """A rating of 0 should still be included (it's not None)."""
        from ragling.indexers.calibre_indexer import _build_book_metadata

        book = _make_book(rating=0)
        meta = _build_book_metadata(book, Path("/lib"), "pdf")

        assert meta["rating"] == 0


# ---------------------------------------------------------------------------
# Tests for _metadata_changed
# ---------------------------------------------------------------------------


class TestMetadataChanged:
    """Tests for the _metadata_changed helper that detects metadata drifts."""

    def test_returns_true_when_no_documents_exist(self, tmp_path: Path) -> None:
        """If no documents exist for the source, metadata is considered changed."""
        from ragling.indexers.calibre_indexer import _metadata_changed

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        # Insert a source with no documents
        conn.execute(
            "INSERT INTO sources (collection_id, source_type, source_path, file_hash) "
            "VALUES (?, 'epub', '/test.epub', 'hash123')",
            (cid,),
        )
        conn.commit()
        source_id = conn.execute("SELECT id FROM sources").fetchone()["id"]

        book = _make_book()
        assert _metadata_changed(conn, source_id, book) is True

    def test_returns_false_when_metadata_matches(self, tmp_path: Path) -> None:
        """Returns False when stored metadata matches the book's current metadata."""
        from ragling.indexers.calibre_indexer import _metadata_changed

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        book = _make_book(
            authors=["Author A"],
            tags=["fiction"],
            series=None,
            rating=None,
            publisher=None,
        )

        source_id = upsert_source_with_chunks(
            conn,
            collection_id=cid,
            source_path="/test.epub",
            source_type="epub",
            chunks=[
                Chunk(
                    text="content",
                    title="Test Book",
                    chunk_index=0,
                    metadata={"authors": ["Author A"], "tags": ["fiction"], "calibre_id": 1},
                )
            ],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
            file_hash="hash123",
        )

        assert _metadata_changed(conn, source_id, book) is False

    def test_returns_true_when_authors_changed(self, tmp_path: Path) -> None:
        """Returns True when authors differ from stored metadata."""
        from ragling.indexers.calibre_indexer import _metadata_changed

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        source_id = upsert_source_with_chunks(
            conn,
            collection_id=cid,
            source_path="/test.epub",
            source_type="epub",
            chunks=[
                Chunk(
                    text="content",
                    title="Test Book",
                    chunk_index=0,
                    metadata={"authors": ["Old Author"]},
                )
            ],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
            file_hash="hash123",
        )

        book = _make_book(authors=["New Author"])
        assert _metadata_changed(conn, source_id, book) is True

    def test_returns_true_when_tags_changed(self, tmp_path: Path) -> None:
        """Returns True when tags differ from stored metadata."""
        from ragling.indexers.calibre_indexer import _metadata_changed

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        source_id = upsert_source_with_chunks(
            conn,
            collection_id=cid,
            source_path="/test.epub",
            source_type="epub",
            chunks=[
                Chunk(
                    text="content",
                    title="Test Book",
                    chunk_index=0,
                    metadata={"authors": ["Author A"], "tags": ["old-tag"]},
                )
            ],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
            file_hash="hash123",
        )

        book = _make_book(authors=["Author A"], tags=["new-tag"])
        assert _metadata_changed(conn, source_id, book) is True

    def test_returns_true_when_series_changed(self, tmp_path: Path) -> None:
        """Returns True when series differs from stored metadata."""
        from ragling.indexers.calibre_indexer import _metadata_changed

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        source_id = upsert_source_with_chunks(
            conn,
            collection_id=cid,
            source_path="/test.epub",
            source_type="epub",
            chunks=[
                Chunk(
                    text="content",
                    title="Test Book",
                    chunk_index=0,
                    metadata={"authors": ["Author A"], "tags": ["fiction"]},
                )
            ],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
            file_hash="hash123",
        )

        book = _make_book(authors=["Author A"], tags=["fiction"], series="New Series")
        assert _metadata_changed(conn, source_id, book) is True

    def test_returns_true_when_rating_changed(self, tmp_path: Path) -> None:
        """Returns True when rating differs from stored metadata."""
        from ragling.indexers.calibre_indexer import _metadata_changed

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        source_id = upsert_source_with_chunks(
            conn,
            collection_id=cid,
            source_path="/test.epub",
            source_type="epub",
            chunks=[
                Chunk(
                    text="content",
                    title="Test Book",
                    chunk_index=0,
                    metadata={"authors": ["Author A"], "tags": ["fiction"], "rating": 5},
                )
            ],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
            file_hash="hash123",
        )

        book = _make_book(authors=["Author A"], tags=["fiction"], rating=8)
        assert _metadata_changed(conn, source_id, book) is True

    def test_returns_true_when_publisher_changed(self, tmp_path: Path) -> None:
        """Returns True when publisher differs from stored metadata."""
        from ragling.indexers.calibre_indexer import _metadata_changed

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        source_id = upsert_source_with_chunks(
            conn,
            collection_id=cid,
            source_path="/test.epub",
            source_type="epub",
            chunks=[
                Chunk(
                    text="content",
                    title="Test Book",
                    chunk_index=0,
                    metadata={"authors": ["Author A"], "tags": ["fiction"]},
                )
            ],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
            file_hash="hash123",
        )

        book = _make_book(authors=["Author A"], tags=["fiction"], publisher="New Pub")
        assert _metadata_changed(conn, source_id, book) is True


# ---------------------------------------------------------------------------
# Tests for _refresh_metadata
# ---------------------------------------------------------------------------


class TestRefreshMetadata:
    """Tests for _refresh_metadata which updates metadata in-place."""

    def test_updates_metadata_on_existing_documents(self, tmp_path: Path) -> None:
        """All document rows for a source get their metadata updated."""
        from ragling.indexers.calibre_indexer import _refresh_metadata

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        # Insert source with two chunks, each with some metadata
        source_id = upsert_source_with_chunks(
            conn,
            collection_id=cid,
            source_path="/test.epub",
            source_type="epub",
            chunks=[
                Chunk(
                    text="chapter 1",
                    title="Test Book",
                    chunk_index=0,
                    metadata={"authors": ["Old Author"], "chapter_number": 1},
                ),
                Chunk(
                    text="chapter 2",
                    title="Test Book",
                    chunk_index=1,
                    metadata={"authors": ["Old Author"], "chapter_number": 2},
                ),
            ],
            embeddings=[[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]],
            file_hash="hash123",
        )

        book = _make_book(authors=["New Author"], tags=["updated-tag"])
        _refresh_metadata(conn, source_id, book, Path("/lib"), "epub")

        # Check both documents got updated metadata
        rows = conn.execute(
            "SELECT metadata FROM documents WHERE source_id = ? ORDER BY chunk_index",
            (source_id,),
        ).fetchall()

        for row in rows:
            meta = json.loads(row["metadata"])
            assert meta["authors"] == ["New Author"]
            assert meta["tags"] == ["updated-tag"]
            assert meta["format"] == "epub"

    def test_preserves_chunk_specific_fields(self, tmp_path: Path) -> None:
        """Chunk-specific fields like chapter_number are preserved during refresh."""
        from ragling.indexers.calibre_indexer import _refresh_metadata

        conn = _make_conn(tmp_path)
        cid = get_or_create_collection(conn, "calibre", "system")

        source_id = upsert_source_with_chunks(
            conn,
            collection_id=cid,
            source_path="/test.epub",
            source_type="epub",
            chunks=[
                Chunk(
                    text="chapter 1",
                    title="Test Book",
                    chunk_index=0,
                    metadata={
                        "authors": ["Old Author"],
                        "chapter_number": 1,
                        "page_number": 42,
                        "chunk_type": "description",
                    },
                ),
            ],
            embeddings=[[0.1, 0.2, 0.3, 0.4]],
            file_hash="hash123",
        )

        book = _make_book(authors=["New Author"])
        _refresh_metadata(conn, source_id, book, Path("/lib"), "epub")

        row = conn.execute(
            "SELECT metadata FROM documents WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        meta = json.loads(row["metadata"])

        assert meta["authors"] == ["New Author"]
        assert meta["chapter_number"] == 1
        assert meta["page_number"] == 42
        assert meta["chunk_type"] == "description"


# ---------------------------------------------------------------------------
# Tests for get_book_file_path (from parsers.calibre)
# ---------------------------------------------------------------------------


class TestGetBookFilePath:
    """Tests for format detection and file path resolution."""

    def test_prefers_epub_over_pdf(self, tmp_path: Path) -> None:
        """When both EPUB and PDF exist, EPUB is preferred."""
        library = tmp_path / "library"
        book_dir = library / "Author" / "Book (1)"
        _create_epub_file(book_dir / "Book.epub")
        _create_pdf_file(book_dir / "Book.pdf")

        book = _make_book(
            formats={"EPUB": "Book", "PDF": "Book"},
            relative_path="Author/Book (1)",
        )

        result = get_book_file_path(library, book, ["EPUB", "PDF"])

        assert result is not None
        path, fmt = result
        assert fmt == "epub"
        assert path.name == "Book.epub"

    def test_falls_back_to_pdf_when_no_epub(self, tmp_path: Path) -> None:
        """When only PDF exists, it is returned."""
        library = tmp_path / "library"
        book_dir = library / "Author" / "Book (1)"
        _create_pdf_file(book_dir / "Book.pdf")

        book = _make_book(
            formats={"PDF": "Book"},
            relative_path="Author/Book (1)",
        )

        result = get_book_file_path(library, book, ["EPUB", "PDF"])

        assert result is not None
        path, fmt = result
        assert fmt == "pdf"
        assert path.name == "Book.pdf"

    def test_returns_none_when_no_supported_format(self, tmp_path: Path) -> None:
        """When no EPUB or PDF exists, returns None."""
        library = tmp_path / "library"
        library.mkdir(parents=True)

        book = _make_book(formats={"MOBI": "Book"}, relative_path="Author/Book (1)")

        result = get_book_file_path(library, book, ["EPUB", "PDF"])

        assert result is None

    def test_returns_none_when_format_listed_but_file_missing(self, tmp_path: Path) -> None:
        """When format is in metadata but file doesn't exist on disk, returns None."""
        library = tmp_path / "library"
        book_dir = library / "Author" / "Book (1)"
        book_dir.mkdir(parents=True)
        # No actual file created

        book = _make_book(
            formats={"EPUB": "Book"},
            relative_path="Author/Book (1)",
        )

        result = get_book_file_path(library, book, ["EPUB", "PDF"])

        assert result is None

    def test_default_preferred_formats(self, tmp_path: Path) -> None:
        """When no preferred_formats given, defaults to EPUB then PDF."""
        library = tmp_path / "library"
        book_dir = library / "Author" / "Book (1)"
        _create_epub_file(book_dir / "Book.epub")

        book = _make_book(
            formats={"EPUB": "Book"},
            relative_path="Author/Book (1)",
        )

        # Pass None to use default
        result = get_book_file_path(library, book, None)

        assert result is not None
        _, fmt = result
        assert fmt == "epub"


# ---------------------------------------------------------------------------
# Tests for parse_calibre_library with real metadata.db
# ---------------------------------------------------------------------------


class TestParseCalibreLibrary:
    """Tests for parsing a Calibre metadata.db into CalibreBook objects."""

    def test_parses_basic_book(self, tmp_path: Path) -> None:
        """Parses a library with one simple book."""
        from ragling.parsers.calibre import parse_calibre_library

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "My Book",
                    "path": "Author/My Book (1)",
                    "pubdate": "2024-01-15",
                    "last_modified": "2025-01-01T00:00:00",
                    "authors": ["Jane Doe"],
                    "tags": ["fiction", "thriller"],
                    "formats": {"EPUB": "My Book"},
                }
            ],
        )

        books = parse_calibre_library(library)

        assert len(books) == 1
        book = books[0]
        assert book.title == "My Book"
        assert book.authors == ["Jane Doe"]
        assert book.tags == ["fiction", "thriller"]
        assert book.formats == {"EPUB": "My Book"}
        assert book.relative_path == "Author/My Book (1)"

    def test_parses_multiple_books(self, tmp_path: Path) -> None:
        """Parses a library with multiple books."""
        from ragling.parsers.calibre import parse_calibre_library

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Book One",
                    "path": "Author/Book One (1)",
                    "authors": ["Author A"],
                },
                {
                    "id": 2,
                    "title": "Book Two",
                    "path": "Author/Book Two (2)",
                    "authors": ["Author B"],
                },
            ],
        )

        books = parse_calibre_library(library)
        assert len(books) == 2
        titles = {b.title for b in books}
        assert titles == {"Book One", "Book Two"}

    def test_parses_book_with_series(self, tmp_path: Path) -> None:
        """Parses a book that belongs to a series."""
        from ragling.parsers.calibre import parse_calibre_library

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Book One",
                    "path": "Author/Book One (1)",
                    "series": "My Series",
                    "series_index": 3.0,
                }
            ],
        )

        books = parse_calibre_library(library)
        assert len(books) == 1
        assert books[0].series == "My Series"
        assert books[0].series_index == 3.0

    def test_parses_book_with_description(self, tmp_path: Path) -> None:
        """Parses a book with HTML description, stripping HTML tags."""
        from ragling.parsers.calibre import parse_calibre_library

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "My Book",
                    "path": "Author/My Book (1)",
                    "comments": "<p>A great <b>book</b> about testing.</p>",
                }
            ],
        )

        books = parse_calibre_library(library)
        assert len(books) == 1
        assert books[0].description is not None
        assert "<p>" not in books[0].description
        assert "great" in books[0].description
        assert "book" in books[0].description

    def test_parses_book_with_identifiers(self, tmp_path: Path) -> None:
        """Parses a book with ISBN and other identifiers."""
        from ragling.parsers.calibre import parse_calibre_library

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "My Book",
                    "path": "Author/My Book (1)",
                    "identifiers": {"isbn": "978-3-16-148410-0", "amazon": "B001234"},
                }
            ],
        )

        books = parse_calibre_library(library)
        assert len(books) == 1
        assert books[0].identifiers == {"isbn": "978-3-16-148410-0", "amazon": "B001234"}

    def test_returns_empty_for_missing_db(self, tmp_path: Path) -> None:
        """Returns empty list when metadata.db doesn't exist."""
        from ragling.parsers.calibre import parse_calibre_library

        library = tmp_path / "nonexistent"
        library.mkdir()

        books = parse_calibre_library(library)
        assert books == []

    def test_parses_book_with_multiple_formats(self, tmp_path: Path) -> None:
        """Parses a book with both EPUB and PDF formats."""
        from ragling.parsers.calibre import parse_calibre_library

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "My Book",
                    "path": "Author/My Book (1)",
                    "formats": {"EPUB": "My Book", "PDF": "My Book"},
                }
            ],
        )

        books = parse_calibre_library(library)
        assert len(books) == 1
        assert books[0].formats == {"EPUB": "My Book", "PDF": "My Book"}


# ---------------------------------------------------------------------------
# Tests for CalibreIndexer.index() with real DB
# ---------------------------------------------------------------------------


class TestCalibreIndexerIndex:
    """Integration tests for CalibreIndexer.index() using real DB and mock Calibre library."""

    def test_indexes_description_only_book(self, tmp_path: Path) -> None:
        """A book with no EPUB/PDF but with a description gets indexed."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Description Only",
                    "path": "Author/Description Only (1)",
                    "comments": "<p>This book has no file, only a description.</p>",
                    "authors": ["Test Author"],
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            result = indexer.index(conn, config)

        assert result.indexed == 1
        assert result.errors == 0

        # Verify source was created with calibre:// URI
        source = conn.execute("SELECT source_path, source_type FROM sources").fetchone()
        assert source is not None
        assert source["source_path"].startswith("calibre://")
        assert source["source_type"] == "calibre-description"

    def test_skips_book_with_no_file_and_no_description(self, tmp_path: Path) -> None:
        """A book with no EPUB/PDF and no description is skipped entirely."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Empty Book",
                    "path": "Author/Empty Book (1)",
                    # No comments, no formats
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        result = indexer.index(conn, config)

        assert result.skipped == 1
        assert result.indexed == 0
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0

    def test_indexes_epub_book(self, tmp_path: Path) -> None:
        """An EPUB book gets indexed with epub chunks and metadata."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        book_dir = library / "Author" / "My Book (1)"
        _create_epub_file(book_dir / "My Book.epub")

        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "My Book",
                    "path": "Author/My Book (1)",
                    "authors": ["Test Author"],
                    "tags": ["testing"],
                    "formats": {"EPUB": "My Book"},
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        mock_chunks = [
            Chunk(text="chapter text", title="My Book", chunk_index=0, metadata={}),
        ]

        with (
            patch(
                "ragling.indexers.calibre_indexer.get_embeddings",
                return_value=[[0.1, 0.2, 0.3, 0.4]],
            ),
            patch("ragling.parsers.epub.parse_epub", return_value=[]),
            patch(
                "ragling.indexers.calibre_indexer.epub_to_docling_doc",
                return_value=MagicMock(),
            ),
            patch(
                "ragling.indexers.calibre_indexer.chunk_with_hybrid",
                return_value=mock_chunks,
            ),
        ):
            result = indexer.index(conn, config)

        assert result.indexed == 1
        assert result.errors == 0

        source = conn.execute("SELECT source_type FROM sources").fetchone()
        assert source["source_type"] == "epub"

    def test_incremental_indexing_skips_unchanged(self, tmp_path: Path) -> None:
        """Running index twice with no changes skips on the second run."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Stable Book",
                    "path": "Author/Stable Book (1)",
                    "comments": "<p>A stable description.</p>",
                    "authors": ["Test Author"],
                    "tags": ["stable"],
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            result1 = indexer.index(conn, config)
            result2 = indexer.index(conn, config)

        assert result1.indexed == 1
        assert result2.skipped == 1
        assert result2.indexed == 0

    def test_force_reindexes_everything(self, tmp_path: Path) -> None:
        """With force=True, all books are reindexed even if unchanged."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Force Book",
                    "path": "Author/Force Book (1)",
                    "comments": "<p>Force indexed.</p>",
                    "authors": ["Author"],
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            result1 = indexer.index(conn, config)
            result2 = indexer.index(conn, config, force=True)

        assert result1.indexed == 1
        assert result2.indexed == 1

    def test_missing_library_path_increments_errors(self, tmp_path: Path) -> None:
        """A non-existent library path increments the error count."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([tmp_path / "nonexistent"])
        result = indexer.index(conn, config)

        assert result.errors == 1
        assert result.indexed == 0

    def test_metadata_refresh_on_incremental(self, tmp_path: Path) -> None:
        """When file content is same but metadata changes, metadata is refreshed."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()

        # First index with original metadata
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Meta Book",
                    "path": "Author/Meta Book (1)",
                    "comments": "<p>Content stays same.</p>",
                    "authors": ["Original Author"],
                    "tags": ["original"],
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            result1 = indexer.index(conn, config)
            assert result1.indexed == 1

        # Now update metadata in the Calibre DB
        db_path = library / "metadata.db"
        meta_conn = sqlite3.connect(str(db_path))
        meta_conn.execute("UPDATE authors SET name = 'Updated Author' WHERE id = 1")
        meta_conn.execute("UPDATE tags SET name = 'updated' WHERE id = 1")
        meta_conn.commit()
        meta_conn.close()

        # Re-create indexer with same library
        indexer2 = CalibreIndexer([library])
        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            result2 = indexer2.index(conn, config)

        # Should detect metadata change and refresh
        assert result2.indexed == 1  # metadata refresh counts as indexed

        # Verify metadata was updated in documents
        row = conn.execute("SELECT metadata FROM documents").fetchone()
        meta = json.loads(row["metadata"])
        assert meta["authors"] == ["Updated Author"]
        assert meta["tags"] == ["updated"]

    def test_status_tracking(self, tmp_path: Path) -> None:
        """IndexingStatus is called with file totals and per-file progress."""
        from ragling.indexing_status import IndexingStatus
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Book A",
                    "path": "Author/Book A (1)",
                    "comments": "<p>Description A</p>",
                },
                {
                    "id": 2,
                    "title": "Book B",
                    "path": "Author/Book B (2)",
                    "comments": "<p>Description B</p>",
                },
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        status = IndexingStatus()
        indexer = CalibreIndexer([library])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            indexer.index(conn, config, status=status)

        # After indexing completes, all files should be processed
        d = status.to_dict()
        assert d is not None
        assert d["collections"]["calibre"]["processed"] == 2
        assert d["collections"]["calibre"]["remaining"] == 0

    def test_status_none_works(self, tmp_path: Path) -> None:
        """CalibreIndexer works fine when status=None."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Book",
                    "path": "Author/Book (1)",
                    "comments": "<p>Desc</p>",
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            result = indexer.index(conn, config, status=None)

        assert result.indexed == 1

    def test_multiple_libraries(self, tmp_path: Path) -> None:
        """CalibreIndexer indexes books from multiple library paths."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        lib1 = tmp_path / "library1"
        lib1.mkdir()
        _create_calibre_metadata_db(
            lib1,
            [
                {
                    "id": 1,
                    "title": "Book From Lib1",
                    "path": "Author/Book From Lib1 (1)",
                    "comments": "<p>From library 1</p>",
                }
            ],
        )

        lib2 = tmp_path / "library2"
        lib2.mkdir()
        _create_calibre_metadata_db(
            lib2,
            [
                {
                    "id": 1,
                    "title": "Book From Lib2",
                    "path": "Author/Book From Lib2 (1)",
                    "comments": "<p>From library 2</p>",
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([lib1, lib2])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            result = indexer.index(conn, config)

        assert result.indexed == 2
        assert result.total_found == 2

    def test_index_result_total_found(self, tmp_path: Path) -> None:
        """total_found reflects all books discovered, not just indexed."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "With Desc",
                    "path": "Author/With Desc (1)",
                    "comments": "<p>Has description</p>",
                },
                {
                    "id": 2,
                    "title": "No Desc No File",
                    "path": "Author/No Desc (2)",
                    # No comments, no formats
                },
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            result = indexer.index(conn, config)

        assert result.total_found == 2
        assert result.indexed == 1
        assert result.skipped == 1  # book with no file and no description

    def test_description_chunks_have_metadata(self, tmp_path: Path) -> None:
        """Description chunks include book metadata (authors, tags, etc.)."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Meta Test",
                    "path": "Author/Meta Test (1)",
                    "comments": "<p>A description.</p>",
                    "authors": ["Alice"],
                    "tags": ["testing"],
                    "publisher": "Test Pub",
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        indexer = CalibreIndexer([library])

        with patch(
            "ragling.indexers.calibre_indexer.get_embeddings",
            return_value=[[0.1, 0.2, 0.3, 0.4]],
        ):
            indexer.index(conn, config)

        row = conn.execute("SELECT metadata FROM documents").fetchone()
        meta = json.loads(row["metadata"])
        assert meta["authors"] == ["Alice"]
        assert meta["tags"] == ["testing"]
        assert meta["publisher"] == "Test Pub"
        assert meta["calibre_id"] == 1
        assert meta["chunk_type"] == "description"

    def test_prunes_stale_sources(self, tmp_path: Path) -> None:
        """Sources whose files no longer exist are pruned after indexing."""
        from ragling.indexers.calibre_indexer import CalibreIndexer

        library = tmp_path / "library"
        library.mkdir()
        book_dir = library / "Author" / "Book (1)"
        epub_path = book_dir / "Book.epub"
        _create_epub_file(epub_path)

        _create_calibre_metadata_db(
            library,
            [
                {
                    "id": 1,
                    "title": "Book",
                    "path": "Author/Book (1)",
                    "formats": {"EPUB": "Book"},
                }
            ],
        )

        config = _make_config(tmp_path)
        conn = _make_conn(tmp_path)

        mock_chunks = [
            Chunk(text="content", title="Book", chunk_index=0, metadata={}),
        ]

        indexer = CalibreIndexer([library])

        with (
            patch(
                "ragling.indexers.calibre_indexer.get_embeddings",
                return_value=[[0.1, 0.2, 0.3, 0.4]],
            ),
            patch("ragling.parsers.epub.parse_epub", return_value=[]),
            patch(
                "ragling.indexers.calibre_indexer.epub_to_docling_doc",
                return_value=MagicMock(),
            ),
            patch(
                "ragling.indexers.calibre_indexer.chunk_with_hybrid",
                return_value=mock_chunks,
            ),
        ):
            result1 = indexer.index(conn, config)
            assert result1.indexed == 1

        # Delete the file and re-index (book removed from Calibre DB too)
        epub_path.unlink()
        _create_calibre_metadata_db(library, [])  # empty library

        indexer2 = CalibreIndexer([library])
        result2 = indexer2.index(conn, config)

        assert result2.pruned == 1
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Tests for _extract_and_chunk_book
# ---------------------------------------------------------------------------


class TestExtractAndChunkBook:
    """Tests for the _extract_and_chunk_book internal function."""

    def test_description_only_produces_chunks(self) -> None:
        """A book with only a description produces description chunks."""
        from ragling.indexers.calibre_indexer import _extract_and_chunk_book

        book = _make_book(description="A great book about testing.")
        config = _make_config(Path("/tmp"))
        book_meta = {"authors": ["Test Author"], "calibre_id": 1}

        chunks = _extract_and_chunk_book(book, None, config, book_meta)

        assert len(chunks) > 0
        assert all(c.metadata.get("chunk_type") == "description" for c in chunks)
        assert all("authors" in c.metadata for c in chunks)

    def test_no_description_and_no_file_returns_empty(self) -> None:
        """A book with no description and no file returns empty chunks."""
        from ragling.indexers.calibre_indexer import _extract_and_chunk_book

        book = _make_book(description=None)
        config = _make_config(Path("/tmp"))
        book_meta = {"calibre_id": 1}

        chunks = _extract_and_chunk_book(book, None, config, book_meta)

        assert chunks == []

    def test_epub_with_description_produces_both_chunk_types(self, tmp_path: Path) -> None:
        """An EPUB book with a description produces both file and description chunks."""
        from ragling.indexers.calibre_indexer import _extract_and_chunk_book

        book = _make_book(
            description="Great book.",
            formats={"EPUB": "Book"},
        )
        config = _make_config(tmp_path)

        epub_path = tmp_path / "Book.epub"
        _create_epub_file(epub_path)
        file_info = (epub_path, "epub")

        book_meta = {"authors": ["Author"], "calibre_id": 1}

        mock_file_chunks = [
            Chunk(text="file content", title="Book", chunk_index=0, metadata={}),
        ]

        with (
            patch("ragling.parsers.epub.parse_epub", return_value=[]),
            patch(
                "ragling.indexers.calibre_indexer.epub_to_docling_doc",
                return_value=MagicMock(),
            ),
            patch(
                "ragling.indexers.calibre_indexer.chunk_with_hybrid",
                side_effect=[
                    mock_file_chunks,
                    [Chunk(text="description", title="Book (description)", chunk_index=0)],
                ],
            ),
        ):
            chunks = _extract_and_chunk_book(book, file_info, config, book_meta)

        assert len(chunks) >= 2
        # First chunk(s) should be from the file
        assert chunks[0].metadata.get("authors") == ["Author"]
        # Last chunk should be a description chunk
        desc_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "description"]
        assert len(desc_chunks) > 0

    def test_chunk_indices_are_sequential(self, tmp_path: Path) -> None:
        """Chunk indices should be sequential starting from 0."""
        from ragling.indexers.calibre_indexer import _extract_and_chunk_book

        book = _make_book(
            description="Description text here.",
            formats={"EPUB": "Book"},
        )
        config = _make_config(tmp_path)

        epub_path = tmp_path / "Book.epub"
        _create_epub_file(epub_path)
        file_info = (epub_path, "epub")

        book_meta = {"calibre_id": 1}

        mock_file_chunks = [
            Chunk(text="chunk 1", title="Book", chunk_index=0, metadata={}),
            Chunk(text="chunk 2", title="Book", chunk_index=1, metadata={}),
        ]

        with (
            patch("ragling.parsers.epub.parse_epub", return_value=[]),
            patch(
                "ragling.indexers.calibre_indexer.epub_to_docling_doc",
                return_value=MagicMock(),
            ),
            patch(
                "ragling.indexers.calibre_indexer.chunk_with_hybrid",
                side_effect=[
                    mock_file_chunks,
                    [Chunk(text="desc", title="Book (description)", chunk_index=0)],
                ],
            ),
        ):
            chunks = _extract_and_chunk_book(book, file_info, config, book_meta)

        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_pdf_without_doc_store_skips_file_content(self, tmp_path: Path) -> None:
        """PDF format without doc_store logs error and skips file content."""
        from ragling.indexers.calibre_indexer import _extract_and_chunk_book

        book = _make_book(description="Has description too.")
        config = _make_config(tmp_path)

        pdf_path = tmp_path / "Book.pdf"
        _create_pdf_file(pdf_path)
        file_info = (pdf_path, "pdf")

        book_meta = {"calibre_id": 1}

        # No doc_store passed -- should skip PDF content but still produce
        # description chunks
        chunks = _extract_and_chunk_book(book, file_info, config, book_meta, doc_store=None)

        # Should only have description chunks, not PDF content
        assert all(c.metadata.get("chunk_type") == "description" for c in chunks)
        assert len(chunks) > 0
