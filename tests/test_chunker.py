"""Tests for ragling.chunker module."""

import pytest

from ragling.chunker import Chunk, chunk_email, chunk_markdown, chunk_plain


class TestChunkMarkdown:
    """Tests for chunk_markdown."""

    def test_empty_text_returns_single_empty_chunk(self):
        result = chunk_markdown("", "Test Note")
        assert len(result) == 1
        assert result[0].text == ""
        assert result[0].title == "Test Note"
        assert result[0].chunk_index == 0

    def test_whitespace_only_returns_single_empty_chunk(self):
        result = chunk_markdown("   \n\n  ", "Blank")
        assert len(result) == 1
        assert result[0].text == ""

    def test_single_paragraph_no_headings(self):
        text = "This is a simple paragraph with no headings."
        result = chunk_markdown(text, "Simple")
        assert len(result) == 1
        assert result[0].text == text
        assert result[0].title == "Simple"
        assert result[0].chunk_index == 0
        assert result[0].metadata == {}

    def test_heading_creates_section(self):
        text = "# Introduction\n\nThis is the introduction body."
        result = chunk_markdown(text, "Doc")
        assert len(result) == 1
        assert "Introduction" in result[0].text
        assert result[0].metadata.get("heading_path") == "Introduction"

    def test_multiple_headings_create_multiple_chunks(self):
        text = "# Section A\n\nContent A.\n\n# Section B\n\nContent B."
        result = chunk_markdown(text, "Doc")
        assert len(result) == 2
        assert "Content A" in result[0].text
        assert "Content B" in result[1].text
        assert result[0].chunk_index == 0
        assert result[1].chunk_index == 1

    def test_nested_headings_preserve_heading_path(self):
        text = "# Top\n\nTop content.\n\n## Sub\n\nSub content.\n\n### Deep\n\nDeep content."
        result = chunk_markdown(text, "Nested")
        paths = [c.metadata.get("heading_path", "") for c in result]
        assert "Top" in paths[0]
        # Sub should include Top > Sub
        assert "Top > Sub" in paths[1]
        # Deep should include Top > Sub > Deep
        assert "Top > Sub > Deep" in paths[2]

    def test_heading_path_resets_on_sibling(self):
        text = (
            "# Chapter 1\n\n## Section 1.1\n\nContent 1.1\n\n"
            "# Chapter 2\n\n## Section 2.1\n\nContent 2.1"
        )
        result = chunk_markdown(text, "Book")
        # The chunk for Section 2.1 should NOT include Chapter 1
        last_chunk = result[-1]
        assert "Chapter 1" not in last_chunk.metadata.get("heading_path", "")
        assert "Chapter 2" in last_chunk.metadata.get("heading_path", "")
        assert "Section 2.1" in last_chunk.metadata.get("heading_path", "")

    def test_preamble_before_first_heading(self):
        text = "Some preamble text here.\n\n# First Heading\n\nHeading content."
        result = chunk_markdown(text, "Doc")
        assert len(result) == 2
        assert "preamble" in result[0].text
        assert result[0].metadata == {}  # no heading path for preamble

    def test_heading_with_no_content_skipped(self):
        text = "# Empty Section\n\n# Has Content\n\nActual content here."
        result = chunk_markdown(text, "Doc")
        # Empty section should be skipped since content is empty after strip
        texts = [c.text for c in result]
        assert any("Actual content" in t for t in texts)

    def test_very_long_section_splits_into_windows(self):
        # Create a section with > 500 words
        long_body = " ".join(f"word{i}" for i in range(600))
        text = f"# Big Section\n\n{long_body}"
        result = chunk_markdown(text, "Long", chunk_size=500, overlap=50)
        assert len(result) > 1
        for chunk in result:
            assert chunk.title == "Long"
            assert "Big Section" in chunk.metadata.get("heading_path", "")

    def test_heading_heavy_markdown(self):
        # Many headings with short content
        sections = "\n\n".join(
            f"# Heading {i}\n\nShort content {i}." for i in range(10)
        )
        result = chunk_markdown(sections, "Many")
        assert len(result) == 10
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i

    def test_chunk_is_dataclass(self):
        result = chunk_markdown("Hello", "T")
        assert isinstance(result[0], Chunk)
        assert hasattr(result[0], "text")
        assert hasattr(result[0], "title")
        assert hasattr(result[0], "metadata")
        assert hasattr(result[0], "chunk_index")


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
        paragraphs = "\n\n".join(
            " ".join(f"word{j}" for j in range(60)) for _ in range(5)
        )
        result = chunk_email("Seq", paragraphs, chunk_size=100, overlap=10)
        indices = [c.chunk_index for c in result]
        assert indices == list(range(len(result)))


class TestChunkPlain:
    """Tests for chunk_plain."""

    def test_empty_text_returns_single_empty_chunk(self):
        result = chunk_plain("", "file.txt")
        assert len(result) == 1
        assert result[0].text == ""
        assert result[0].title == "file.txt"

    def test_whitespace_only_returns_single_empty_chunk(self):
        result = chunk_plain("   \t  \n ", "blank.txt")
        assert len(result) == 1
        assert result[0].text == ""

    def test_short_text_single_chunk(self):
        text = "This is a short document."
        result = chunk_plain(text, "short.txt")
        assert len(result) == 1
        assert result[0].text == text
        assert result[0].title == "short.txt"
        assert result[0].chunk_index == 0

    def test_long_text_multiple_windows(self):
        text = " ".join(f"word{i}" for i in range(200))
        result = chunk_plain(text, "long.txt", chunk_size=50, overlap=10)
        assert len(result) > 1
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i
            assert chunk.title == "long.txt"

    def test_overlap_between_windows(self):
        # Use small chunk size to make overlap observable
        words = [f"w{i}" for i in range(30)]
        text = " ".join(words)
        result = chunk_plain(text, "overlap.txt", chunk_size=10, overlap=3)
        assert len(result) > 1
        # Words at the end of chunk 0 should appear at the start of chunk 1
        words_chunk0 = result[0].text.split()
        words_chunk1 = result[1].text.split()
        # Last `overlap` words of chunk 0 should be the first `overlap` words of chunk 1
        assert words_chunk0[-3:] == words_chunk1[:3]

    def test_exact_chunk_size_single_chunk(self):
        text = " ".join(f"w{i}" for i in range(50))
        result = chunk_plain(text, "exact.txt", chunk_size=50, overlap=5)
        assert len(result) == 1

    def test_chunk_size_plus_one_creates_two_chunks(self):
        text = " ".join(f"w{i}" for i in range(51))
        result = chunk_plain(text, "plusone.txt", chunk_size=50, overlap=5)
        assert len(result) == 2
