"""Tests for ragling.search_utils module."""

from ragling.search_utils import escape_fts_query


class TestEscapeFtsQuery:
    """Tests for escape_fts_query per SQLite FTS5 spec section 3.1."""

    def test_simple_query_wrapped_as_phrase(self) -> None:
        result = escape_fts_query("hello world")
        assert result == '"hello world"'

    def test_single_word(self) -> None:
        result = escape_fts_query("kubernetes")
        assert result == '"kubernetes"'

    def test_empty_query_returns_empty(self) -> None:
        result = escape_fts_query("")
        assert result == ""

    def test_whitespace_only_returns_empty(self) -> None:
        result = escape_fts_query("   ")
        assert result == ""

    def test_fts_operators_escaped(self) -> None:
        """FTS5 operators like NOT, AND, OR are treated as literal text."""
        result = escape_fts_query("NOT AND OR")
        assert result == '"NOT AND OR"'

    def test_internal_double_quotes_doubled(self) -> None:
        """Internal double quotes are doubled per FTS5 spec."""
        result = escape_fts_query('search for "exact phrase"')
        assert result == '"search for ""exact phrase"""'

    def test_asterisk_escaped(self) -> None:
        """Asterisk (FTS5 prefix operator) is treated as literal."""
        result = escape_fts_query("test*")
        assert result == '"test*"'

    def test_caret_escaped(self) -> None:
        """Caret (FTS5 initial token query) is treated as literal."""
        result = escape_fts_query("^start")
        assert result == '"^start"'

    def test_preserves_internal_whitespace(self) -> None:
        """Internal whitespace is preserved (stripped only from edges)."""
        result = escape_fts_query("hello   world")
        assert result == '"hello   world"'

    def test_strips_leading_trailing_whitespace(self) -> None:
        result = escape_fts_query("  hello world  ")
        assert result == '"hello world"'
