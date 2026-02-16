"""Tests for the markdown parser."""

import datetime
from pathlib import Path

from ragling.parsers.markdown import parse_markdown

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class TestFrontmatter:
    def test_extracts_title(self):
        doc = parse_markdown(
            "---\ntitle: My Note\ntags:\n  - test\n---\nBody text here.",
            "fallback.md",
        )
        assert doc.title == "My Note"

    def test_extracts_tags(self):
        doc = parse_markdown(
            "---\ntags:\n  - alpha\n  - beta\n---\nSome body.",
            "note.md",
        )
        assert "alpha" in doc.tags
        assert "beta" in doc.tags

    def test_extracts_arbitrary_fields(self):
        doc = parse_markdown(
            "---\ntitle: Test\ndate: 2025-01-15\ncustom_field: value\n---\nBody.",
            "note.md",
        )
        assert doc.frontmatter["date"] == datetime.date(2025, 1, 15)
        assert doc.frontmatter["custom_field"] == "value"

    def test_handles_no_frontmatter(self):
        doc = parse_markdown("Just a plain note.\nNo frontmatter.", "plain.md")
        assert doc.frontmatter == {}
        assert doc.title == "plain"
        assert "Just a plain note." in doc.body_text

    def test_handles_invalid_yaml(self):
        doc = parse_markdown("---\n: invalid: yaml: [[\n---\nBody.", "bad.md")
        assert doc.frontmatter == {}
        assert doc.title == "bad"

    def test_comma_separated_tags(self):
        doc = parse_markdown("---\ntags: alpha, beta, gamma\n---\nBody.", "note.md")
        assert "alpha" in doc.tags
        assert "beta" in doc.tags
        assert "gamma" in doc.tags


class TestWikilinks:
    def test_simple_wikilink(self):
        doc = parse_markdown("See [[Docker Basics]] for info.", "note.md")
        assert "Docker Basics" in doc.links
        assert "Docker Basics" in doc.body_text
        assert "[[" not in doc.body_text

    def test_aliased_wikilink(self):
        doc = parse_markdown("Use [[Helm Charts|Helm]] for packaging.", "note.md")
        assert "Helm Charts" in doc.links
        assert "Helm" in doc.body_text
        assert "Helm Charts" in doc.body_text
        assert "[[" not in doc.body_text

    def test_multiple_wikilinks(self):
        doc = parse_markdown("See [[Note A]] and [[Note B|B link]].", "note.md")
        assert "Note A" in doc.links
        assert "Note B" in doc.links
        assert len(doc.links) == 2


class TestEmbeds:
    def test_embed_stripped(self):
        doc = parse_markdown("Before\n![[image.png]]\nAfter", "note.md")
        assert "![[" not in doc.body_text
        assert "image.png" not in doc.body_text
        assert "Before" in doc.body_text
        assert "After" in doc.body_text

    def test_multiple_embeds(self):
        doc = parse_markdown("Text\n![[file1.pdf]]\nMore\n![[file2.png]]", "note.md")
        assert "![[" not in doc.body_text

    def test_embed_not_confused_with_wikilink(self):
        doc = parse_markdown("See [[Real Link]] and ![[embedded.png]]", "note.md")
        assert "Real Link" in doc.links
        assert "embedded.png" not in doc.body_text


class TestTags:
    def test_inline_tag(self):
        doc = parse_markdown("Some text #mytag here.", "note.md")
        assert "mytag" in doc.tags

    def test_nested_tag(self):
        doc = parse_markdown("Text with #nested/tag here.", "note.md")
        assert "nested/tag" in doc.tags

    def test_tag_at_line_start(self):
        doc = parse_markdown("#topic at start of line", "note.md")
        # A heading line like "# heading" should not produce a tag,
        # but "#topic" without a space after # is an inline tag at line start
        assert "topic" in doc.tags

    def test_tag_not_in_code_block(self):
        doc = parse_markdown("```\n#not-a-tag\n```\nOutside.", "note.md")
        assert "not-a-tag" not in doc.tags

    def test_tag_not_in_inline_code(self):
        doc = parse_markdown("Use `#not-a-tag` in code.", "note.md")
        assert "not-a-tag" not in doc.tags

    def test_heading_not_treated_as_tag(self):
        doc = parse_markdown("# Heading\n\nBody text.", "note.md")
        assert "Heading" not in doc.tags

    def test_combined_frontmatter_and_inline_tags(self):
        doc = parse_markdown(
            "---\ntags:\n  - from-fm\n---\nText with #inline-tag.",
            "note.md",
        )
        assert "from-fm" in doc.tags
        assert "inline-tag" in doc.tags

    def test_no_duplicate_tags(self):
        doc = parse_markdown("---\ntags:\n  - dup\n---\nText with #dup again.", "note.md")
        assert doc.tags.count("dup") == 1


class TestDataviewBlocks:
    def test_dataview_stripped(self):
        doc = parse_markdown(
            'Before\n\n```dataview\nTABLE file.mtime\nFROM "Notes"\n```\n\nAfter',
            "note.md",
        )
        assert "dataview" not in doc.body_text
        assert "TABLE" not in doc.body_text
        assert "Before" in doc.body_text
        assert "After" in doc.body_text


class TestTitleFallback:
    def test_uses_filename_stem(self):
        doc = parse_markdown("No frontmatter here.", "My Great Note.md")
        assert doc.title == "My Great Note"

    def test_frontmatter_title_takes_precedence(self):
        doc = parse_markdown("---\ntitle: Explicit Title\n---\nBody.", "fallback.md")
        assert doc.title == "Explicit Title"

    def test_empty_frontmatter_title_falls_back(self):
        doc = parse_markdown("---\ntitle:\n---\nBody.", "fallback.md")
        assert doc.title == "fallback"


class TestMinimalInput:
    def test_empty_string(self):
        doc = parse_markdown("", "empty.md")
        assert doc.title == "empty"
        assert doc.body_text == ""
        assert doc.tags == []
        assert doc.links == []

    def test_whitespace_only(self):
        doc = parse_markdown("   \n\n   ", "spaces.md")
        assert doc.title == "spaces"
        assert doc.body_text == ""

    def test_frontmatter_only(self):
        doc = parse_markdown("---\ntitle: Just FM\n---\n", "fm.md")
        assert doc.title == "Just FM"
        assert doc.body_text == ""


class TestSampleFixture:
    """Integration test using the full sample_note.md fixture."""

    def test_parse_sample_note(self):
        text = _load_fixture("sample_note.md")
        doc = parse_markdown(text, "sample_note.md")

        # Title from frontmatter
        assert doc.title == "Kubernetes Deployment Guide"

        # Frontmatter fields
        assert doc.frontmatter["date"] == datetime.date(2025, 1, 15)
        assert "k8s guide" in doc.frontmatter["aliases"]

        # Tags from frontmatter + inline
        assert "devops" in doc.tags
        assert "kubernetes" in doc.tags
        assert "infrastructure" in doc.tags
        assert "yaml" in doc.tags
        assert "deployment" in doc.tags
        assert "zero-downtime" in doc.tags
        assert "community-support" in doc.tags

        # Wikilinks extracted
        assert "Helm Charts" in doc.links
        assert "Docker Basics" in doc.links
        assert "Cluster Setup" in doc.links
        assert "Monitoring Setup" in doc.links

        # Wikilinks converted in text (no [[ ]] remaining)
        assert "[[" not in doc.body_text

        # Embeds stripped
        assert "![[" not in doc.body_text
        assert "architecture-diagram.png" not in doc.body_text

        # Dataview block stripped
        assert "dataview" not in doc.body_text
        assert "TABLE file.mtime" not in doc.body_text

        # Content still present
        assert "Rolling updates gradually replace" in doc.body_text
        assert "kubectl" in doc.body_text

        # Hash in inline code not treated as tag
        assert "ff0000" not in doc.tags
