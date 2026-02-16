"""Tests for ragling.chunker module."""

from ragling.chunker import chunk_email


class TestChunkEmail:
    """Tests for chunk_email."""

    def test_short_email_single_chunk(self):
        result = chunk_email("Meeting Tomorrow", "Let's meet at 3pm.")
        assert len(result) == 1
        assert result[0].text == "Let's meet at 3pm."
        assert result[0].title == "Meeting Tomorrow"
        assert result[0].chunk_index == 0

    def test_empty_body_returns_subject_only(self):
        result = chunk_email("Subject Line", "")
        assert len(result) == 1
        assert "Subject Line" in result[0].text
        assert result[0].title == "Subject Line"

    def test_empty_body_and_subject(self):
        result = chunk_email("", "")
        assert len(result) == 1
        assert result[0].title == "(no subject)"

    def test_none_body_returns_subject(self):
        result = chunk_email("Hello", None)
        assert len(result) == 1
        assert "Hello" in result[0].text

    def test_no_subject_uses_placeholder(self):
        result = chunk_email("", "Some body text here.")
        assert result[0].title == "(no subject)"

    def test_long_email_multi_chunk(self):
        # Create a long email with multiple paragraphs
        paragraphs = []
        for i in range(20):
            para = " ".join(f"word{i}_{j}" for j in range(40))
            paragraphs.append(para)
        body = "\n\n".join(paragraphs)
        result = chunk_email("Long Email", body, chunk_size=100, overlap=10)
        assert len(result) > 1
        for chunk in result:
            assert chunk.title == "Long Email"

    def test_oversized_paragraph_gets_windowed(self):
        # Single paragraph with > chunk_size words
        big_para = " ".join(f"w{i}" for i in range(200))
        result = chunk_email("Big", big_para, chunk_size=50, overlap=5)
        assert len(result) > 1

    def test_chunk_indices_are_sequential(self):
        paragraphs = "\n\n".join(" ".join(f"word{j}" for j in range(60)) for _ in range(5))
        result = chunk_email("Seq", paragraphs, chunk_size=100, overlap=10)
        indices = [c.chunk_index for c in result]
        assert indices == list(range(len(result)))
