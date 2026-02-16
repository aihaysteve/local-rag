"""Bridge between legacy parsers and DoclingDocument for unified chunking.

Converts parsed markdown, epub, and plaintext content into DoclingDocument
objects so all formats can be chunked by HybridChunker with contextualize().
"""

import re

from docling_core.types.doc import DocItemLabel, DoclingDocument
from docling_core.types.doc.document import NodeItem

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _add_paragraphs(
    doc: DoclingDocument, text: str, parent: NodeItem | None = None
) -> None:
    """Split text on double newlines and add non-empty paragraphs to doc."""
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if para:
            doc.add_text(label=DocItemLabel.PARAGRAPH, text=para, parent=parent)


def markdown_to_docling_doc(text: str, title: str) -> DoclingDocument:
    """Convert markdown text into a DoclingDocument preserving heading hierarchy.

    Args:
        text: Markdown body text (frontmatter already stripped).
        title: Document title for the DoclingDocument name.

    Returns:
        A DoclingDocument with headings and paragraphs.
    """
    doc = DoclingDocument(name=title)

    if not text.strip():
        return doc

    segments = _split_markdown_segments(text)

    # Track heading nodes for nesting: level -> NodeItem
    heading_stack: dict[int, NodeItem] = {}

    for level, heading_text, body in segments:
        parent: NodeItem | None = None

        if level > 0 and heading_text:
            # Find parent: the nearest heading with a lower level
            for lv in range(level - 1, 0, -1):
                if lv in heading_stack:
                    parent = heading_stack[lv]
                    break

            heading_item = doc.add_heading(text=heading_text, level=level, parent=parent)
            heading_stack[level] = heading_item
            # Clear deeper headings from stack
            for deeper in list(heading_stack.keys()):
                if deeper > level:
                    del heading_stack[deeper]
            parent = heading_item

        if body.strip():
            _add_paragraphs(doc, body, parent=parent)

    return doc


def _split_markdown_segments(
    text: str,
) -> list[tuple[int, str | None, str]]:
    """Split markdown into segments of (heading_level, heading_text, body_text).

    Level 0 with heading_text=None means preamble (text before any heading).
    """
    segments: list[tuple[int, str | None, str]] = []
    parts = _HEADING_RE.split(text)

    # parts = [preamble, hashes, heading_text, body, hashes, heading_text, body, ...]
    preamble = parts[0]
    if preamble.strip():
        segments.append((0, None, preamble))

    i = 1
    while i + 2 <= len(parts):
        level = len(parts[i])
        heading_text = parts[i + 1].strip()
        body = parts[i + 2] if i + 2 < len(parts) else ""
        segments.append((level, heading_text, body))
        i += 3

    return segments


def epub_to_docling_doc(chapters: list[tuple[int, str]], title: str) -> DoclingDocument:
    """Convert parsed epub chapters into a DoclingDocument.

    Args:
        chapters: List of (chapter_number, text) tuples from parse_epub().
        title: Book title for the DoclingDocument name.

    Returns:
        A DoclingDocument with chapter headings and paragraph content.
    """
    doc = DoclingDocument(name=title)

    for chapter_num, text in chapters:
        heading = doc.add_heading(text=f"Chapter {chapter_num}", level=1)

        if text.strip():
            _add_paragraphs(doc, text, parent=heading)

    return doc


def plaintext_to_docling_doc(text: str, title: str) -> DoclingDocument:
    """Convert plain text into a DoclingDocument.

    Args:
        text: Raw text content.
        title: Document title for the DoclingDocument name.

    Returns:
        A DoclingDocument with paragraphs split on double newlines.
    """
    doc = DoclingDocument(name=title)

    if not text.strip():
        return doc

    _add_paragraphs(doc, text)

    return doc
