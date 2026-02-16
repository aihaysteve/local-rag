"""Tests for ragling.chunker module."""

from ragling.chunker import Chunk


class TestChunkDataclass:
    """Tests for the Chunk dataclass."""

    def test_chunk_has_required_fields(self) -> None:
        c = Chunk(text="hello", title="doc")
        assert c.text == "hello"
        assert c.title == "doc"

    def test_chunk_defaults(self) -> None:
        c = Chunk(text="text", title="title")
        assert c.metadata == {}
        assert c.chunk_index == 0

    def test_chunk_with_metadata(self) -> None:
        c = Chunk(text="t", title="t", metadata={"key": "val"}, chunk_index=3)
        assert c.metadata == {"key": "val"}
        assert c.chunk_index == 3


class TestSplitIntoWindows:
    """Tests for _split_into_windows (still used by git indexer)."""

    def test_short_text_single_window(self) -> None:
        from ragling.chunker import _split_into_windows

        result = _split_into_windows("a b c", 10, 2)
        assert result == ["a b c"]

    def test_long_text_multiple_windows(self) -> None:
        from ragling.chunker import _split_into_windows

        text = " ".join(f"w{i}" for i in range(20))
        result = _split_into_windows(text, 5, 1)
        assert len(result) > 1

    def test_empty_text_empty_result(self) -> None:
        from ragling.chunker import _split_into_windows

        assert _split_into_windows("", 10, 2) == []
