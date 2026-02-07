"""Obsidian-flavored Markdown parser for local-rag."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class MarkdownDocument:
    """Parsed representation of an Obsidian markdown note."""

    title: str
    body_text: str
    frontmatter: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


# Regex patterns
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n?", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")
_DATAVIEW_RE = re.compile(r"```dataview\s*\n.*?\n```", re.DOTALL)
_INLINE_TAG_RE = re.compile(r"(?<!\S)#([\w][\w/\-]*)", re.UNICODE)
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


def _extract_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from the beginning of text.

    Returns:
        Tuple of (frontmatter_dict, remaining_text).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    yaml_str = match.group(1)
    remaining = text[match.end():]

    try:
        fm = yaml.safe_load(yaml_str)
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse frontmatter: %s", e)
        fm = {}

    return fm, remaining


def _extract_embeds(text: str) -> tuple[str, list[str]]:
    """Strip ![[embed]] references from text, collecting referenced targets.

    Returns:
        Tuple of (cleaned_text, list_of_embed_targets).
    """
    embeds: list[str] = []

    def _replace_embed(m: re.Match) -> str:
        embeds.append(m.group(1))
        return ""

    cleaned = _EMBED_RE.sub(_replace_embed, text)
    return cleaned, embeds


def _convert_wikilinks(text: str) -> tuple[str, list[str]]:
    """Convert [[target|display]] and [[target]] wikilinks to plain text.

    Keeps both target and display as searchable content.

    Returns:
        Tuple of (converted_text, list_of_link_targets).
    """
    links: list[str] = []

    def _replace_link(m: re.Match) -> str:
        inner = m.group(1)
        if "|" in inner:
            target, display = inner.split("|", 1)
            links.append(target.strip())
            return f"{display.strip()} ({target.strip()})"
        else:
            links.append(inner.strip())
            return inner.strip()

    converted = _WIKILINK_RE.sub(_replace_link, text)
    return converted, links


def _strip_dataview_blocks(text: str) -> str:
    """Remove ```dataview ... ``` code blocks."""
    return _DATAVIEW_RE.sub("", text)


def _extract_tags(text: str, frontmatter: dict) -> list[str]:
    """Extract tags from both frontmatter and inline #tags.

    Inline tags inside code blocks and heading lines are ignored.
    """
    tags: list[str] = []

    # Tags from frontmatter
    fm_tags = frontmatter.get("tags", [])
    if isinstance(fm_tags, list):
        tags.extend(str(t) for t in fm_tags)
    elif isinstance(fm_tags, str):
        tags.extend(t.strip() for t in fm_tags.split(",") if t.strip())

    # Strip code blocks and inline code so we don't match tags inside them
    cleaned = _CODE_BLOCK_RE.sub("", text)
    cleaned = _INLINE_CODE_RE.sub("", cleaned)

    # Strip heading lines so # in headings aren't matched
    cleaned = _HEADING_LINE_RE.sub("", cleaned)

    for match in _INLINE_TAG_RE.finditer(cleaned):
        tag = match.group(1)
        if tag not in tags:
            tags.append(tag)

    return tags


def parse_markdown(text: str, filename: str) -> MarkdownDocument:
    """Parse an Obsidian-flavored markdown note.

    Args:
        text: Raw markdown text content.
        filename: The filename (e.g. 'My Note.md') used as title fallback.

    Returns:
        Parsed MarkdownDocument with extracted metadata.
    """
    frontmatter, body = _extract_frontmatter(text)

    # Strip dataview blocks
    body = _strip_dataview_blocks(body)

    # Extract and strip embeds
    body, embeds = _extract_embeds(body)

    # Convert wikilinks
    body, links = _convert_wikilinks(body)

    # Extract tags (from frontmatter + inline)
    tags = _extract_tags(body, frontmatter)

    # Determine title
    title = frontmatter.get("title", "") or Path(filename).stem

    # Clean up extra blank lines
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return MarkdownDocument(
        title=title,
        body_text=body,
        frontmatter=frontmatter,
        tags=tags,
        links=links,
    )
