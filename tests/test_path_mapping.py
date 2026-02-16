"""Tests for ragling.path_mapping module."""


class TestApplyForwardMapping:
    """Forward mapping: host path -> container path in search results."""

    def test_replaces_matching_prefix(self) -> None:
        from ragling.path_mapping import apply_forward

        mappings = {"/Users/me/NanoClaw/groups/kitchen/": "/workspace/group/"}
        result = apply_forward("/Users/me/NanoClaw/groups/kitchen/notes/recipe.md", mappings)
        assert result == "/workspace/group/notes/recipe.md"

    def test_longest_prefix_wins(self) -> None:
        from ragling.path_mapping import apply_forward

        mappings = {
            "/Users/me/NanoClaw/": "/workspace/",
            "/Users/me/NanoClaw/groups/kitchen/": "/workspace/group/",
        }
        result = apply_forward("/Users/me/NanoClaw/groups/kitchen/notes.md", mappings)
        assert result == "/workspace/group/notes.md"

    def test_no_match_returns_original(self) -> None:
        from ragling.path_mapping import apply_forward

        mappings = {"/Users/me/NanoClaw/groups/kitchen/": "/workspace/group/"}
        result = apply_forward("/Users/me/Documents/other.md", mappings)
        assert result == "/Users/me/Documents/other.md"

    def test_empty_mappings_returns_original(self) -> None:
        from ragling.path_mapping import apply_forward

        result = apply_forward("/some/path.md", {})
        assert result == "/some/path.md"


class TestApplyReverseMapping:
    """Reverse mapping: container path -> host path for file access."""

    def test_replaces_matching_prefix(self) -> None:
        from ragling.path_mapping import apply_reverse

        mappings = {"/Users/me/NanoClaw/groups/kitchen/": "/workspace/group/"}
        result = apply_reverse("/workspace/group/report.pdf", mappings)
        assert result == "/Users/me/NanoClaw/groups/kitchen/report.pdf"

    def test_longest_container_prefix_wins(self) -> None:
        from ragling.path_mapping import apply_reverse

        mappings = {
            "/Users/me/NanoClaw/": "/workspace/",
            "/Users/me/NanoClaw/groups/kitchen/": "/workspace/group/",
        }
        result = apply_reverse("/workspace/group/doc.pdf", mappings)
        assert result == "/Users/me/NanoClaw/groups/kitchen/doc.pdf"

    def test_no_match_returns_original(self) -> None:
        from ragling.path_mapping import apply_reverse

        mappings = {"/Users/me/NanoClaw/groups/kitchen/": "/workspace/group/"}
        result = apply_reverse("/other/path.pdf", mappings)
        assert result == "/other/path.pdf"


class TestApplyMappingsToUri:
    """Forward mapping applied to source_uri strings."""

    def test_maps_file_uri(self) -> None:
        from ragling.path_mapping import apply_forward_uri

        mappings = {"/Users/me/groups/kitchen/": "/workspace/group/"}
        result = apply_forward_uri("file:///Users/me/groups/kitchen/doc.pdf", mappings)
        assert result == "file:///workspace/group/doc.pdf"

    def test_maps_vscode_uri(self) -> None:
        from ragling.path_mapping import apply_forward_uri

        mappings = {"/Users/me/groups/kitchen/": "/workspace/group/"}
        result = apply_forward_uri("vscode://file/Users/me/groups/kitchen/main.py:42", mappings)
        assert result == "vscode://file/workspace/group/main.py:42"

    def test_leaves_obsidian_uri_unchanged(self) -> None:
        from ragling.path_mapping import apply_forward_uri

        mappings = {"/Users/me/": "/workspace/"}
        result = apply_forward_uri("obsidian://open?vault=MyVault&file=note.md", mappings)
        assert result == "obsidian://open?vault=MyVault&file=note.md"

    def test_leaves_none_unchanged(self) -> None:
        from ragling.path_mapping import apply_forward_uri

        mappings = {"/Users/me/": "/workspace/"}
        assert apply_forward_uri(None, mappings) is None
