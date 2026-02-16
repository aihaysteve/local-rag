"""Tests for building DoclingDocument from legacy-parsed content."""

from docling_core.types.doc import DoclingDocument


class TestMarkdownToDoclingDoc:
    def test_returns_docling_document(self) -> None:
        from ragling.docling_bridge import markdown_to_docling_doc

        doc = markdown_to_docling_doc("Hello world", "test")
        assert isinstance(doc, DoclingDocument)

    def test_document_name_matches_title(self) -> None:
        from ragling.docling_bridge import markdown_to_docling_doc

        doc = markdown_to_docling_doc("text", "My Note")
        assert doc.name == "My Note"

    def test_heading_creates_section_header(self) -> None:
        from ragling.docling_bridge import markdown_to_docling_doc

        text = "# Introduction\n\nSome body text."
        doc = markdown_to_docling_doc(text, "Doc")
        items = list(doc.iterate_items())
        labels = [item.label.value for item, _level in items]
        assert "section_header" in labels

    def test_nested_headings_create_hierarchy(self) -> None:
        from ragling.docling_bridge import markdown_to_docling_doc

        text = "# Top\n\nTop text.\n\n## Sub\n\nSub text."
        doc = markdown_to_docling_doc(text, "Doc")
        items = list(doc.iterate_items())
        headers = [
            (item.text, level) for item, level in items if item.label.value == "section_header"
        ]
        assert len(headers) == 2
        # Sub should be at a deeper level than Top
        assert headers[1][1] > headers[0][1]

    def test_body_text_preserved(self) -> None:
        from ragling.docling_bridge import markdown_to_docling_doc

        text = "# Heading\n\nThis is the body content."
        doc = markdown_to_docling_doc(text, "Doc")
        items = list(doc.iterate_items())
        texts = [item.text for item, _level in items if item.label.value == "paragraph"]
        assert any("body content" in t for t in texts)

    def test_empty_text_returns_valid_document(self) -> None:
        from ragling.docling_bridge import markdown_to_docling_doc

        doc = markdown_to_docling_doc("", "Empty")
        assert isinstance(doc, DoclingDocument)
        assert doc.name == "Empty"

    def test_preamble_before_heading(self) -> None:
        from ragling.docling_bridge import markdown_to_docling_doc

        text = "Preamble text.\n\n# First Heading\n\nBody."
        doc = markdown_to_docling_doc(text, "Doc")
        items = list(doc.iterate_items())
        # First item should be the preamble paragraph
        first_item = items[0][0]
        assert "Preamble" in first_item.text


class TestEpubToDoclingDoc:
    def test_returns_docling_document(self) -> None:
        from ragling.docling_bridge import epub_to_docling_doc

        chapters = [(1, "Chapter one text."), (2, "Chapter two text.")]
        doc = epub_to_docling_doc(chapters, "My Book")
        assert isinstance(doc, DoclingDocument)

    def test_chapters_become_headings(self) -> None:
        from ragling.docling_bridge import epub_to_docling_doc

        chapters = [(1, "First chapter."), (2, "Second chapter.")]
        doc = epub_to_docling_doc(chapters, "Book")
        items = list(doc.iterate_items())
        headers = [item for item, _level in items if item.label.value == "section_header"]
        assert len(headers) == 2
        assert "Chapter 1" in headers[0].text
        assert "Chapter 2" in headers[1].text

    def test_chapter_text_preserved(self) -> None:
        from ragling.docling_bridge import epub_to_docling_doc

        chapters = [(1, "The story begins here.")]
        doc = epub_to_docling_doc(chapters, "Book")
        items = list(doc.iterate_items())
        texts = [item.text for item, _level in items if item.label.value == "paragraph"]
        assert any("story begins" in t for t in texts)

    def test_empty_chapters_returns_valid_document(self) -> None:
        from ragling.docling_bridge import epub_to_docling_doc

        doc = epub_to_docling_doc([], "Empty Book")
        assert isinstance(doc, DoclingDocument)


class TestPlaintextToDoclingDoc:
    def test_returns_docling_document(self) -> None:
        from ragling.docling_bridge import plaintext_to_docling_doc

        doc = plaintext_to_docling_doc("Hello world.", "file.txt")
        assert isinstance(doc, DoclingDocument)

    def test_text_content_preserved(self) -> None:
        from ragling.docling_bridge import plaintext_to_docling_doc

        doc = plaintext_to_docling_doc("Important content here.", "notes.txt")
        items = list(doc.iterate_items())
        texts = [item.text for item, _level in items]
        assert any("Important content" in t for t in texts)

    def test_paragraphs_split_on_double_newline(self) -> None:
        from ragling.docling_bridge import plaintext_to_docling_doc

        text = "First paragraph.\n\nSecond paragraph."
        doc = plaintext_to_docling_doc(text, "doc.txt")
        items = list(doc.iterate_items())
        paragraphs = [item for item, _level in items if item.label.value == "paragraph"]
        assert len(paragraphs) == 2

    def test_empty_text_returns_valid_document(self) -> None:
        from ragling.docling_bridge import plaintext_to_docling_doc

        doc = plaintext_to_docling_doc("", "empty.txt")
        assert isinstance(doc, DoclingDocument)
