"""Tests for Swift tree-sitter parsing in ragling.parsers.code."""

from pathlib import Path

from ragling.parsers.code import get_language, is_code_file, parse_code_file


class TestSwiftExtensionAndLanguage:
    """Tests for Swift file extension detection and language mapping."""

    def test_swift_is_code_file(self) -> None:
        assert is_code_file(Path("main.swift")) is True

    def test_swift_returns_swift(self) -> None:
        assert get_language(Path("main.swift")) == "swift"

    def test_swift_case_insensitive(self) -> None:
        assert is_code_file(Path("App.SWIFT")) is True
        assert get_language(Path("App.SWIFT")) == "swift"


class TestSwiftParsing:
    """Tests for Swift code parsing via parse_code_file."""

    SWIFT_SOURCE = """\
import Foundation

class Animal {
    var name: String
    init(name: String) {
        self.name = name
    }
    func speak() -> String {
        return "..."
    }
}

struct Point {
    var x: Double
    var y: Double
    func distanceTo(_ other: Point) -> Double {
        return sqrt(pow(x - other.x, 2) + pow(y - other.y, 2))
    }
}

protocol Drawable {
    func draw()
}

enum Direction {
    case north, south, east, west
}

extension Animal: Drawable {
    func draw() { print(name) }
}

func topLevel() -> Int {
    return 42
}
"""

    def _parse_swift(self, tmp_path: Path, source: str | None = None) -> list:
        """Write Swift source to a temp file and parse it, returning blocks."""
        swift_file = tmp_path / "test.swift"
        swift_file.write_text(source if source is not None else self.SWIFT_SOURCE)
        doc = parse_code_file(swift_file, "swift", "test.swift")
        assert doc is not None, "parse_code_file returned None"
        return doc.blocks

    def test_parses_without_error(self, tmp_path: Path) -> None:
        """Swift source parses successfully and returns a CodeDocument."""
        swift_file = tmp_path / "test.swift"
        swift_file.write_text(self.SWIFT_SOURCE)
        doc = parse_code_file(swift_file, "swift", "test.swift")
        assert doc is not None
        assert doc.language == "swift"
        assert doc.file_path == "test.swift"

    def test_block_count(self, tmp_path: Path) -> None:
        """Swift source produces the expected number of structural blocks.

        Expected blocks:
        1. import Foundation (top-level)
        2. class Animal { ... }
        3. struct Point { ... }
        4. protocol Drawable { ... }
        5. enum Direction { ... }
        6. extension Animal: Drawable { ... }
        7. func topLevel() -> Int { ... }
        """
        blocks = self._parse_swift(tmp_path)
        assert len(blocks) == 7

    def test_import_is_top_level(self, tmp_path: Path) -> None:
        """An import declaration is accumulated into a module_top block."""
        blocks = self._parse_swift(tmp_path)
        import_block = blocks[0]
        assert import_block.symbol_type == "module_top"
        assert import_block.symbol_name == "(top-level)"
        assert "import Foundation" in import_block.text

    def test_class_symbol_name(self, tmp_path: Path) -> None:
        """A class declaration extracts the correct symbol name."""
        blocks = self._parse_swift(tmp_path)
        cls = blocks[1]
        assert cls.symbol_name == "Animal"

    def test_class_symbol_type(self, tmp_path: Path) -> None:
        """A class declaration is classified as symbol_type 'class'."""
        blocks = self._parse_swift(tmp_path)
        cls = blocks[1]
        assert cls.symbol_type == "class"

    def test_class_contains_body(self, tmp_path: Path) -> None:
        """A class block contains its full body text."""
        blocks = self._parse_swift(tmp_path)
        cls = blocks[1]
        assert "func speak()" in cls.text
        assert "init(name: String)" in cls.text

    def test_struct_symbol_name(self, tmp_path: Path) -> None:
        """A struct declaration extracts the correct symbol name."""
        blocks = self._parse_swift(tmp_path)
        struct_block = blocks[2]
        assert struct_block.symbol_name == "Point"

    def test_struct_symbol_type(self, tmp_path: Path) -> None:
        """A struct declaration is classified as symbol_type 'struct'."""
        blocks = self._parse_swift(tmp_path)
        struct_block = blocks[2]
        assert struct_block.symbol_type == "struct"

    def test_protocol_symbol_name(self, tmp_path: Path) -> None:
        """A protocol declaration extracts the correct symbol name."""
        blocks = self._parse_swift(tmp_path)
        proto = blocks[3]
        assert proto.symbol_name == "Drawable"

    def test_protocol_symbol_type(self, tmp_path: Path) -> None:
        """A protocol declaration is classified as symbol_type 'protocol'."""
        blocks = self._parse_swift(tmp_path)
        proto = blocks[3]
        assert proto.symbol_type == "protocol"

    def test_enum_symbol_name(self, tmp_path: Path) -> None:
        """An enum declaration extracts the correct symbol name."""
        blocks = self._parse_swift(tmp_path)
        enum_block = blocks[4]
        assert enum_block.symbol_name == "Direction"

    def test_enum_symbol_type(self, tmp_path: Path) -> None:
        """An enum declaration is classified as symbol_type 'enum'."""
        blocks = self._parse_swift(tmp_path)
        enum_block = blocks[4]
        assert enum_block.symbol_type == "enum"

    def test_extension_symbol_name(self, tmp_path: Path) -> None:
        """An extension declaration extracts the extended type name."""
        blocks = self._parse_swift(tmp_path)
        ext = blocks[5]
        assert ext.symbol_name == "Animal"

    def test_extension_symbol_type(self, tmp_path: Path) -> None:
        """An extension declaration is classified as symbol_type 'extension'."""
        blocks = self._parse_swift(tmp_path)
        ext = blocks[5]
        assert ext.symbol_type == "extension"

    def test_function_symbol_name(self, tmp_path: Path) -> None:
        """A top-level function declaration extracts the correct symbol name."""
        blocks = self._parse_swift(tmp_path)
        func_block = blocks[6]
        assert func_block.symbol_name == "topLevel"

    def test_function_symbol_type(self, tmp_path: Path) -> None:
        """A top-level function declaration is classified as symbol_type 'function'."""
        blocks = self._parse_swift(tmp_path)
        func_block = blocks[6]
        assert func_block.symbol_type == "function"

    def test_start_end_lines_1_based(self, tmp_path: Path) -> None:
        """start_line and end_line use 1-based line numbers."""
        blocks = self._parse_swift(tmp_path)
        for block in blocks:
            assert block.start_line >= 1
            assert block.end_line >= block.start_line

    def test_file_path_propagated(self, tmp_path: Path) -> None:
        """The relative file_path is propagated to all blocks."""
        blocks = self._parse_swift(tmp_path)
        for block in blocks:
            assert block.file_path == "test.swift"

    def test_language_set_on_blocks(self, tmp_path: Path) -> None:
        """All blocks have language set to 'swift'."""
        blocks = self._parse_swift(tmp_path)
        for block in blocks:
            assert block.language == "swift"

    def test_empty_file_produces_no_blocks(self, tmp_path: Path) -> None:
        """An empty .swift file produces no blocks."""
        swift_file = tmp_path / "empty.swift"
        swift_file.write_text("")
        doc = parse_code_file(swift_file, "swift", "empty.swift")
        assert doc is not None
        assert len(doc.blocks) == 0

    def test_only_imports_become_top_level(self, tmp_path: Path) -> None:
        """A file with only imports produces a single module_top block."""
        source = """\
import Foundation
import UIKit
"""
        blocks = self._parse_swift(tmp_path, source)
        assert len(blocks) == 1
        assert blocks[0].symbol_type == "module_top"
        assert "import Foundation" in blocks[0].text
        assert "import UIKit" in blocks[0].text

    def test_struct_with_no_methods(self, tmp_path: Path) -> None:
        """A struct without methods is still parsed as a struct block."""
        source = """\
struct Size {
    var width: Double
    var height: Double
}
"""
        blocks = self._parse_swift(tmp_path, source)
        assert len(blocks) == 1
        assert blocks[0].symbol_name == "Size"
        assert blocks[0].symbol_type == "struct"

    def test_class_line_numbers(self, tmp_path: Path) -> None:
        """Class declaration has correct 1-based line numbers."""
        blocks = self._parse_swift(tmp_path)
        cls = blocks[1]
        # class Animal starts on line 3, ends on line 11
        assert cls.start_line == 3
        assert cls.end_line == 11
