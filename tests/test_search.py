"""Tests for ragling.search module."""

import json
import sqlite3

import pytest

from unittest.mock import patch

from ragling.config import Config
from ragling.search import SearchFilters, SearchResult, _escape_fts_query, perform_search, rrf_merge

# Check if sqlite3 supports loading extensions (required for sqlite-vec integration tests)
_conn = sqlite3.connect(":memory:")
_has_load_extension = hasattr(_conn, "enable_load_extension")
_conn.close()

requires_sqlite_extensions = pytest.mark.skipif(
    not _has_load_extension,
    reason="sqlite3 was not compiled with loadable extension support",
)


class TestRRFMerge:
    """Tests for rrf_merge (pure unit tests, no database)."""

    def test_empty_inputs(self):
        result = rrf_merge([], [])
        assert result == []

    def test_vec_only(self):
        vec = [(1, 0.1), (2, 0.2), (3, 0.3)]
        result = rrf_merge(vec, [], k=60, vector_weight=0.7, fts_weight=0.3)
        assert len(result) == 3
        # All scores come from vector only
        doc_ids = [doc_id for doc_id, _ in result]
        assert 1 in doc_ids
        assert 2 in doc_ids
        assert 3 in doc_ids
        # Doc 1 is rank 0, so it should have the highest score
        assert result[0][0] == 1

    def test_fts_only(self):
        fts = [(10, -5.0), (11, -3.0), (12, -1.0)]
        result = rrf_merge([], fts, k=60, vector_weight=0.7, fts_weight=0.3)
        assert len(result) == 3
        # Doc 10 is rank 0 in FTS, should have highest score
        assert result[0][0] == 10

    def test_overlapping_results_combined(self):
        vec = [(1, 0.1), (2, 0.2)]
        fts = [(2, -5.0), (3, -3.0)]
        result = rrf_merge(vec, fts, k=60, vector_weight=0.7, fts_weight=0.3)
        # Doc 2 appears in both lists, should get combined score
        scores = dict(result)
        # Doc 2 gets vector score at rank 1 + fts score at rank 0
        expected_doc2 = 0.7 / (60 + 2) + 0.3 / (60 + 1)
        assert scores[2] == pytest.approx(expected_doc2)

    def test_non_overlapping_results(self):
        vec = [(1, 0.1), (2, 0.2)]
        fts = [(3, -5.0), (4, -3.0)]
        result = rrf_merge(vec, fts, k=60, vector_weight=0.7, fts_weight=0.3)
        assert len(result) == 4
        doc_ids = {doc_id for doc_id, _ in result}
        assert doc_ids == {1, 2, 3, 4}

    def test_scores_are_correct(self):
        vec = [(1, 0.5)]
        fts = [(1, -2.0)]
        result = rrf_merge(vec, fts, k=60, vector_weight=0.7, fts_weight=0.3)
        assert len(result) == 1
        doc_id, score = result[0]
        assert doc_id == 1
        # rank 0 in both: 0.7/(60+1) + 0.3/(60+1)
        expected = 0.7 / 61 + 0.3 / 61
        assert score == pytest.approx(expected)

    def test_sorted_by_score_descending(self):
        vec = [(1, 0.1), (2, 0.2), (3, 0.3)]
        fts = [(3, -5.0), (2, -3.0), (1, -1.0)]
        result = rrf_merge(vec, fts, k=60, vector_weight=0.7, fts_weight=0.3)
        scores = [score for _, score in result]
        assert scores == sorted(scores, reverse=True)

    def test_custom_k_parameter(self):
        vec = [(1, 0.1)]
        fts = []
        result_k10 = rrf_merge(vec, fts, k=10)
        result_k100 = rrf_merge(vec, fts, k=100)
        # Smaller k means higher score for rank 0
        assert result_k10[0][1] > result_k100[0][1]

    def test_weight_influence(self):
        # Same doc ranked #0 in both, different weights should yield different scores
        vec = [(1, 0.1)]
        fts = [(1, -1.0)]
        result_vec_heavy = rrf_merge(vec, fts, vector_weight=0.9, fts_weight=0.1)
        result_fts_heavy = rrf_merge(vec, fts, vector_weight=0.1, fts_weight=0.9)
        # Both result in (0.9+0.1)/61 = 1.0/61 and (0.1+0.9)/61 = 1.0/61
        # When single doc is rank 0 in both, weights sum to same total
        assert result_vec_heavy[0][1] == pytest.approx(result_fts_heavy[0][1])

    def test_weight_influence_with_different_docs(self):
        # Doc 1 only in vec, doc 2 only in fts
        vec = [(1, 0.1)]
        fts = [(2, -1.0)]
        result = rrf_merge(vec, fts, k=60, vector_weight=0.9, fts_weight=0.1)
        scores = dict(result)
        # Doc 1 gets only vec score, doc 2 gets only fts score
        assert scores[1] == pytest.approx(0.9 / 61)
        assert scores[2] == pytest.approx(0.1 / 61)
        # With these weights, doc 1 should rank higher
        assert result[0][0] == 1

    def test_large_number_of_results(self):
        vec = [(i, float(i) * 0.1) for i in range(100)]
        fts = [(i + 50, float(i) * -1.0) for i in range(100)]
        result = rrf_merge(vec, fts)
        # Should have 150 unique docs (0-99 from vec, 50-149 from fts, overlap 50-99)
        assert len(result) == 150
        # Should be sorted descending
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)


class TestEscapeFtsQuery:
    """Tests for _escape_fts_query."""

    def test_simple_query(self):
        result = _escape_fts_query("hello world")
        assert result == '"hello" "world"'

    def test_single_word(self):
        result = _escape_fts_query("kubernetes")
        assert result == '"kubernetes"'

    def test_empty_query(self):
        result = _escape_fts_query("")
        assert result == ""

    def test_special_characters_quoted(self):
        # FTS5 special chars like * and - should be safely wrapped in quotes
        result = _escape_fts_query("NOT AND OR")
        assert result == '"NOT" "AND" "OR"'

    def test_query_with_punctuation(self):
        result = _escape_fts_query("hello, world!")
        assert result == '"hello," "world!"'

    def test_extra_whitespace(self):
        result = _escape_fts_query("  hello   world  ")
        # split() handles extra whitespace
        assert result == '"hello" "world"'


class TestDataclasses:
    """Tests for SearchResult and SearchFilters dataclass construction."""

    def test_search_result_construction(self):
        sr = SearchResult(
            content="some text",
            title="My Doc",
            metadata={"key": "value"},
            score=0.95,
            collection="obsidian",
            source_path="/path/to/file.md",
            source_type="markdown",
        )
        assert sr.content == "some text"
        assert sr.title == "My Doc"
        assert sr.metadata == {"key": "value"}
        assert sr.score == 0.95
        assert sr.collection == "obsidian"
        assert sr.source_path == "/path/to/file.md"
        assert sr.source_type == "markdown"

    def test_search_filters_defaults(self):
        sf = SearchFilters()
        assert sf.collection is None
        assert sf.source_type is None
        assert sf.date_from is None
        assert sf.date_to is None
        assert sf.sender is None

    def test_search_filters_with_values(self):
        sf = SearchFilters(
            collection="email",
            source_type="email",
            date_from="2025-01-01",
            date_to="2025-12-31",
            sender="alice@example.com",
        )
        assert sf.collection == "email"
        assert sf.source_type == "email"
        assert sf.date_from == "2025-01-01"
        assert sf.date_to == "2025-12-31"
        assert sf.sender == "alice@example.com"

    def test_search_filters_partial(self):
        sf = SearchFilters(collection="obsidian")
        assert sf.collection == "obsidian"
        assert sf.source_type is None


@requires_sqlite_extensions
class TestSearchWithDatabase:
    """Integration tests that use an in-memory SQLite database with sqlite-vec."""

    @pytest.fixture()
    def db(self, tmp_path):
        """Create an in-memory DB with schema initialized."""
        import sqlite_vec

        config = Config(
            db_path=tmp_path / "test.db",
            embedding_dimensions=4,
        )
        conn = sqlite3.connect(str(config.db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row

        from ragling.db import init_db

        init_db(conn, config)

        yield conn, config
        conn.close()

    @staticmethod
    def _insert_document(
        conn,
        collection_name,
        source_path,
        title,
        content,
        embedding,
        metadata=None,
        source_type="markdown",
    ):
        """Helper to insert a document with its embedding."""
        from ragling.db import get_or_create_collection
        from ragling.embeddings import serialize_float32

        col_id = get_or_create_collection(conn, collection_name)

        cursor = conn.execute(
            "INSERT OR IGNORE INTO sources (collection_id, source_type, source_path) VALUES (?, ?, ?)",
            (col_id, source_type, source_path),
        )
        if cursor.lastrowid == 0:
            source_id = conn.execute(
                "SELECT id FROM sources WHERE collection_id = ? AND source_path = ?",
                (col_id, source_path),
            ).fetchone()["id"]
        else:
            source_id = cursor.lastrowid

        cursor = conn.execute(
            "INSERT INTO documents (source_id, collection_id, chunk_index, title, content, metadata) "
            "VALUES (?, ?, 0, ?, ?, ?)",
            (source_id, col_id, title, content, json.dumps(metadata or {})),
        )
        doc_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO vec_documents (rowid, embedding, document_id) VALUES (?, ?, ?)",
            (doc_id, serialize_float32(embedding), doc_id),
        )
        conn.commit()
        return doc_id

    def test_fts_search_finds_document(self, db):
        conn, config = db
        self._insert_document(
            conn,
            "test",
            "/test.md",
            "Test Doc",
            "kubernetes deployment strategies for production",
            [1.0, 0.0, 0.0, 0.0],
        )

        from ragling.search import _escape_fts_query

        query = _escape_fts_query("kubernetes deployment")
        rows = conn.execute(
            "SELECT rowid, rank FROM documents_fts WHERE documents_fts MATCH ?",
            (query,),
        ).fetchall()
        assert len(rows) == 1

    def test_fts_search_no_match(self, db):
        conn, config = db
        self._insert_document(
            conn,
            "test",
            "/test.md",
            "Test Doc",
            "kubernetes deployment strategies",
            [1.0, 0.0, 0.0, 0.0],
        )

        from ragling.search import _escape_fts_query

        query = _escape_fts_query("postgresql replication")
        rows = conn.execute(
            "SELECT rowid, rank FROM documents_fts WHERE documents_fts MATCH ?",
            (query,),
        ).fetchall()
        assert len(rows) == 0

    def test_vec_search_finds_similar(self, db):
        conn, config = db

        self._insert_document(conn, "test", "/a.md", "A", "content a", [1.0, 0.0, 0.0, 0.0])
        self._insert_document(conn, "test", "/b.md", "B", "content b", [0.0, 1.0, 0.0, 0.0])

        from ragling.embeddings import serialize_float32

        query_blob = serialize_float32([0.9, 0.1, 0.0, 0.0])
        rows = conn.execute(
            "SELECT document_id, distance FROM vec_documents WHERE embedding MATCH ? ORDER BY distance LIMIT 2",
            (query_blob,),
        ).fetchall()

        assert len(rows) == 2
        # Doc A (embedding [1,0,0,0]) should be closer to query [0.9,0.1,0,0]
        assert rows[0]["document_id"] == 1

    def test_full_hybrid_search(self, db):
        """Test the full search() function with real DB."""
        conn, config = db
        self._insert_document(
            conn,
            "obsidian",
            "/notes/k8s.md",
            "Kubernetes Guide",
            "kubernetes deployment strategies for production environments",
            [1.0, 0.0, 0.0, 0.0],
        )
        self._insert_document(
            conn,
            "obsidian",
            "/notes/docker.md",
            "Docker Guide",
            "docker containerization basics and best practices",
            [0.0, 1.0, 0.0, 0.0],
        )

        from ragling.search import search

        results = search(
            conn=conn,
            query_embedding=[0.9, 0.1, 0.0, 0.0],
            query_text="kubernetes deployment",
            top_k=10,
            filters=None,
            config=config,
        )

        assert len(results) >= 1
        # The kubernetes doc should be the top result (matches both vector and FTS)
        assert results[0].title == "Kubernetes Guide"
        assert results[0].collection == "obsidian"
        assert "kubernetes" in results[0].content

    def test_search_with_collection_filter(self, db):
        conn, config = db
        self._insert_document(
            conn, "obsidian", "/a.md", "Note A", "common search term alpha", [1.0, 0.0, 0.0, 0.0]
        )
        self._insert_document(
            conn,
            "project-x",
            "/b.md",
            "Doc B",
            "common search term beta",
            [0.9, 0.1, 0.0, 0.0],
        )

        from ragling.search import search

        results = search(
            conn=conn,
            query_embedding=[1.0, 0.0, 0.0, 0.0],
            query_text="common search term",
            top_k=10,
            filters=SearchFilters(collection="obsidian"),
            config=config,
        )

        assert all(r.collection == "obsidian" for r in results)
        assert len(results) == 1

    def test_search_returns_search_result_objects(self, db):
        conn, config = db
        self._insert_document(
            conn,
            "test-col",
            "/doc.md",
            "Title",
            "body text here",
            [1.0, 0.0, 0.0, 0.0],
            metadata={"key": "val"},
            source_type="markdown",
        )

        from ragling.search import search

        results = search(
            conn=conn,
            query_embedding=[1.0, 0.0, 0.0, 0.0],
            query_text="body text",
            top_k=5,
            filters=None,
            config=config,
        )

        assert len(results) == 1
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.content == "body text here"
        assert r.title == "Title"
        assert r.metadata == {"key": "val"}
        assert r.collection == "test-col"
        assert r.source_path == "/doc.md"
        assert r.source_type == "markdown"
        assert r.score > 0

    def test_search_with_visible_collections_filter(self, db):
        """visible_collections limits results to allowed collections only."""
        conn, config = db
        self._insert_document(
            conn,
            "kitchen",
            "/kitchen/notes.md",
            "Kitchen Note",
            "recipe for pasta carbonara",
            [1.0, 0.0, 0.0, 0.0],
        )
        self._insert_document(
            conn,
            "garage",
            "/garage/tools.md",
            "Garage Tools",
            "recipe for workshop organization",
            [0.9, 0.1, 0.0, 0.0],
        )
        self._insert_document(
            conn,
            "global",
            "/global/shared.md",
            "Shared Doc",
            "recipe for global knowledge base",
            [0.8, 0.2, 0.0, 0.0],
        )

        from ragling.search import search

        results = search(
            conn=conn,
            query_embedding=[1.0, 0.0, 0.0, 0.0],
            query_text="recipe",
            top_k=10,
            filters=None,
            config=config,
            visible_collections=["kitchen", "global"],
        )

        collections_in_results = {r.collection for r in results}
        assert "kitchen" in collections_in_results
        assert "global" in collections_in_results
        assert "garage" not in collections_in_results

    def test_search_visible_collections_none_returns_all(self, db):
        """visible_collections=None returns results from all collections."""
        conn, config = db
        self._insert_document(
            conn,
            "col-a",
            "/a.md",
            "A",
            "unique text alpha",
            [1.0, 0.0, 0.0, 0.0],
        )
        self._insert_document(
            conn,
            "col-b",
            "/b.md",
            "B",
            "unique text alpha beta",
            [0.9, 0.1, 0.0, 0.0],
        )

        from ragling.search import search

        results = search(
            conn=conn,
            query_embedding=[1.0, 0.0, 0.0, 0.0],
            query_text="unique text alpha",
            top_k=10,
            filters=None,
            config=config,
            visible_collections=None,
        )

        assert len(results) == 2

    def test_search_visible_collections_empty_returns_nothing(self, db):
        """visible_collections=[] returns no results."""
        conn, config = db
        self._insert_document(
            conn,
            "test",
            "/test.md",
            "Test",
            "some content here",
            [1.0, 0.0, 0.0, 0.0],
        )

        from ragling.search import search

        results = search(
            conn=conn,
            query_embedding=[1.0, 0.0, 0.0, 0.0],
            query_text="some content",
            top_k=10,
            filters=None,
            config=config,
            visible_collections=[],
        )

        assert len(results) == 0


class TestPerformSearchParams:
    """Tests for perform_search config and visible_collections parameters."""

    @patch("ragling.search.get_embedding", return_value=[1.0, 0.0, 0.0, 0.0])
    @patch("ragling.search.get_connection")
    @patch("ragling.search.init_db")
    @patch("ragling.search.search", return_value=[])
    @patch("ragling.search.load_config")
    def test_uses_provided_config(self, mock_load, mock_search, mock_init, mock_conn, mock_embed):
        """perform_search uses provided config instead of calling load_config."""
        custom_config = Config(embedding_dimensions=4)
        perform_search("test query", config=custom_config)
        mock_load.assert_not_called()

    @patch("ragling.search.get_embedding", return_value=[1.0, 0.0, 0.0, 0.0])
    @patch("ragling.search.get_connection")
    @patch("ragling.search.init_db")
    @patch("ragling.search.search", return_value=[])
    @patch("ragling.search.load_config")
    def test_passes_visible_collections(
        self, mock_load, mock_search, mock_init, mock_conn, mock_embed
    ):
        """perform_search passes visible_collections through to search."""
        perform_search("test query", visible_collections=["kitchen", "global"])
        _, kwargs = mock_search.call_args
        assert kwargs["visible_collections"] == ["kitchen", "global"]

    @patch("ragling.search.get_embedding", return_value=[1.0, 0.0, 0.0, 0.0])
    @patch("ragling.search.get_connection")
    @patch("ragling.search.init_db")
    @patch("ragling.search.search", return_value=[])
    @patch("ragling.search.load_config")
    def test_defaults_visible_collections_to_none(
        self, mock_load, mock_search, mock_init, mock_conn, mock_embed
    ):
        """perform_search defaults visible_collections to None (full access)."""
        perform_search("test query")
        _, kwargs = mock_search.call_args
        assert kwargs["visible_collections"] is None
