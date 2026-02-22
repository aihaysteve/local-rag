"""Tests for ragling.parsers.code -- extension map, language detection, and parsing."""

from pathlib import Path

from ragling.parsers.code import get_language, is_code_file, parse_code_file


class TestCodeExtensionMap:
    """Tests for _CODE_EXTENSION_MAP and file selection via is_code_file."""

    def test_python_is_code_file(self) -> None:
        assert is_code_file(Path("main.py")) is True

    def test_javascript_is_code_file(self) -> None:
        assert is_code_file(Path("app.js")) is True

    def test_typescript_is_code_file(self) -> None:
        assert is_code_file(Path("index.ts")) is True

    def test_tsx_is_code_file(self) -> None:
        assert is_code_file(Path("component.tsx")) is True

    def test_go_is_code_file(self) -> None:
        assert is_code_file(Path("server.go")) is True

    def test_rust_is_code_file(self) -> None:
        assert is_code_file(Path("lib.rs")) is True

    def test_java_is_code_file(self) -> None:
        assert is_code_file(Path("Main.java")) is True

    def test_c_is_code_file(self) -> None:
        assert is_code_file(Path("main.c")) is True

    def test_cpp_is_code_file(self) -> None:
        assert is_code_file(Path("main.cpp")) is True

    def test_header_is_code_file(self) -> None:
        assert is_code_file(Path("header.h")) is True

    def test_ruby_is_code_file(self) -> None:
        assert is_code_file(Path("script.rb")) is True

    def test_bash_is_code_file(self) -> None:
        assert is_code_file(Path("deploy.sh")) is True

    def test_terraform_is_code_file(self) -> None:
        assert is_code_file(Path("main.tf")) is True

    def test_hcl_is_code_file(self) -> None:
        assert is_code_file(Path("config.hcl")) is True

    def test_yaml_is_code_file(self) -> None:
        assert is_code_file(Path("config.yaml")) is True

    def test_yml_is_code_file(self) -> None:
        assert is_code_file(Path("config.yml")) is True

    def test_csharp_is_code_file(self) -> None:
        assert is_code_file(Path("Program.cs")) is True

    def test_zig_is_code_file(self) -> None:
        assert is_code_file(Path("main.zig")) is True

    def test_dockerfile_is_code_file(self) -> None:
        """Dockerfile is detected via _CODE_FILENAME_MAP, not extension."""
        assert is_code_file(Path("Dockerfile")) is True

    def test_markdown_is_not_code_file(self) -> None:
        assert is_code_file(Path("readme.md")) is False

    def test_pdf_is_not_code_file(self) -> None:
        assert is_code_file(Path("document.pdf")) is False

    def test_txt_is_not_code_file(self) -> None:
        assert is_code_file(Path("notes.txt")) is False

    def test_docx_is_not_code_file(self) -> None:
        assert is_code_file(Path("report.docx")) is False

    def test_unknown_is_not_code_file(self) -> None:
        assert is_code_file(Path("data.xyz")) is False

    def test_no_extension_is_not_code_file(self) -> None:
        """A file with no extension and no filename match is not a code file."""
        assert is_code_file(Path("Makefile")) is False

    def test_case_insensitive_extension(self) -> None:
        """Extension matching should be case-insensitive."""
        assert is_code_file(Path("main.PY")) is True
        assert is_code_file(Path("app.JS")) is True


class TestGetLanguage:
    """Tests for get_language returning correct language names."""

    def test_python_returns_python(self) -> None:
        assert get_language(Path("main.py")) == "python"

    def test_go_returns_go(self) -> None:
        assert get_language(Path("server.go")) == "go"

    def test_typescript_returns_typescript(self) -> None:
        assert get_language(Path("index.ts")) == "typescript"

    def test_tsx_returns_tsx(self) -> None:
        assert get_language(Path("component.tsx")) == "tsx"

    def test_javascript_returns_javascript(self) -> None:
        assert get_language(Path("app.js")) == "javascript"

    def test_jsx_returns_javascript(self) -> None:
        assert get_language(Path("component.jsx")) == "javascript"

    def test_rust_returns_rust(self) -> None:
        assert get_language(Path("lib.rs")) == "rust"

    def test_java_returns_java(self) -> None:
        assert get_language(Path("Main.java")) == "java"

    def test_c_returns_c(self) -> None:
        assert get_language(Path("main.c")) == "c"

    def test_header_returns_c(self) -> None:
        assert get_language(Path("header.h")) == "c"

    def test_cpp_returns_cpp(self) -> None:
        assert get_language(Path("main.cpp")) == "cpp"

    def test_cc_returns_cpp(self) -> None:
        assert get_language(Path("main.cc")) == "cpp"

    def test_csharp_returns_csharp(self) -> None:
        assert get_language(Path("Program.cs")) == "csharp"

    def test_ruby_returns_ruby(self) -> None:
        assert get_language(Path("script.rb")) == "ruby"

    def test_bash_returns_bash(self) -> None:
        assert get_language(Path("deploy.sh")) == "bash"

    def test_bash_extension_returns_bash(self) -> None:
        assert get_language(Path("script.bash")) == "bash"

    def test_terraform_returns_hcl(self) -> None:
        assert get_language(Path("main.tf")) == "hcl"

    def test_tfvars_returns_hcl(self) -> None:
        assert get_language(Path("vars.tfvars")) == "hcl"

    def test_hcl_returns_hcl(self) -> None:
        assert get_language(Path("config.hcl")) == "hcl"

    def test_yaml_returns_yaml(self) -> None:
        assert get_language(Path("config.yaml")) == "yaml"

    def test_yml_returns_yaml(self) -> None:
        assert get_language(Path("config.yml")) == "yaml"

    def test_zig_returns_zig(self) -> None:
        assert get_language(Path("main.zig")) == "zig"

    def test_dockerfile_returns_dockerfile(self) -> None:
        """Dockerfile is detected via _CODE_FILENAME_MAP."""
        assert get_language(Path("Dockerfile")) == "dockerfile"

    def test_unsupported_returns_none(self) -> None:
        assert get_language(Path("readme.md")) is None

    def test_unknown_extension_returns_none(self) -> None:
        assert get_language(Path("data.xyz")) is None

    def test_no_extension_non_filename_returns_none(self) -> None:
        """A file with no extension and no filename match returns None."""
        assert get_language(Path("Makefile")) is None

    def test_case_insensitive_extension(self) -> None:
        """Extension matching should be case-insensitive."""
        assert get_language(Path("main.PY")) == "python"
        assert get_language(Path("app.JS")) == "javascript"


class TestZigParsing:
    """Tests for Zig code parsing via parse_code_file."""

    # A comprehensive Zig source file covering all major declaration types
    ZIG_SOURCE = """\
const std = @import("std");

pub fn add(a: i32, b: i32) i32 {
    return a + b;
}

fn privateHelper() void {}

const Point = struct {
    x: f64,
    y: f64,
};

const Color = enum {
    red,
    green,
    blue,
};

test "addition works" {
    const result = add(2, 3);
    try std.testing.expectEqual(@as(i32, 5), result);
}

comptime {
    _ = @import("other.zig");
}
"""

    def _parse_zig(self, tmp_path: Path, source: str | None = None) -> list:
        """Write Zig source to a temp file and parse it, returning blocks."""
        zig_file = tmp_path / "test.zig"
        zig_file.write_text(source if source is not None else self.ZIG_SOURCE)
        doc = parse_code_file(zig_file, "zig", "test.zig")
        assert doc is not None, "parse_code_file returned None"
        return doc.blocks

    def test_parses_without_error(self, tmp_path: Path) -> None:
        """Zig source parses successfully and returns a CodeDocument."""
        zig_file = tmp_path / "test.zig"
        zig_file.write_text(self.ZIG_SOURCE)
        doc = parse_code_file(zig_file, "zig", "test.zig")
        assert doc is not None
        assert doc.language == "zig"
        assert doc.file_path == "test.zig"

    def test_block_count(self, tmp_path: Path) -> None:
        """Zig source produces the expected number of structural blocks.

        Expected blocks:
        1. const std = @import("std"); (variable — Decl with VarDecl)
        2. pub fn add (function)
        3. fn privateHelper (function)
        4. const Point = struct { ... } (struct)
        5. const Color = enum { ... } (enum)
        6. test "addition works" (test)
        7. comptime { ... } (comptime)
        """
        blocks = self._parse_zig(tmp_path)
        assert len(blocks) == 7

    def test_import_declaration(self, tmp_path: Path) -> None:
        """A top-level @import is a Decl/VarDecl classified as 'variable'."""
        blocks = self._parse_zig(tmp_path)
        import_block = blocks[0]
        assert import_block.symbol_type == "variable"
        assert import_block.symbol_name == "std"
        assert "@import" in import_block.text

    def test_pub_function_symbol_name(self, tmp_path: Path) -> None:
        """A pub fn declaration extracts the correct symbol name."""
        blocks = self._parse_zig(tmp_path)
        pub_fn = blocks[1]
        assert pub_fn.symbol_name == "add"

    def test_pub_function_symbol_type(self, tmp_path: Path) -> None:
        """A pub fn declaration is classified as symbol_type 'function'."""
        blocks = self._parse_zig(tmp_path)
        pub_fn = blocks[1]
        assert pub_fn.symbol_type == "function"

    def test_pub_prefix_prepended_to_text(self, tmp_path: Path) -> None:
        """The ``pub`` visibility modifier is prepended to the block text."""
        blocks = self._parse_zig(tmp_path)
        pub_fn = blocks[1]
        assert pub_fn.text.startswith("pub ")

    def test_pub_prefix_adjusts_start_line(self, tmp_path: Path) -> None:
        """The start_line for a pub declaration includes the pub keyword line."""
        blocks = self._parse_zig(tmp_path)
        pub_fn = blocks[1]
        # "pub fn add" starts on line 3 (1-based)
        assert pub_fn.start_line == 3

    def test_private_function(self, tmp_path: Path) -> None:
        """A private fn declaration is correctly parsed."""
        blocks = self._parse_zig(tmp_path)
        priv_fn = blocks[2]
        assert priv_fn.symbol_name == "privateHelper"
        assert priv_fn.symbol_type == "function"
        assert not priv_fn.text.startswith("pub ")

    def test_struct_declaration(self, tmp_path: Path) -> None:
        """A const = struct { ... } declaration is classified as 'struct'."""
        blocks = self._parse_zig(tmp_path)
        struct_block = blocks[3]
        assert struct_block.symbol_name == "Point"
        assert struct_block.symbol_type == "struct"

    def test_enum_declaration(self, tmp_path: Path) -> None:
        """A const = enum { ... } declaration is classified as 'enum'."""
        blocks = self._parse_zig(tmp_path)
        enum_block = blocks[4]
        assert enum_block.symbol_name == "Color"
        assert enum_block.symbol_type == "enum"

    def test_test_declaration_name(self, tmp_path: Path) -> None:
        """A test declaration extracts the test name string."""
        blocks = self._parse_zig(tmp_path)
        test_block = blocks[5]
        assert test_block.symbol_name == "addition works"

    def test_test_declaration_type(self, tmp_path: Path) -> None:
        """A test declaration is classified as symbol_type 'test'."""
        blocks = self._parse_zig(tmp_path)
        test_block = blocks[5]
        assert test_block.symbol_type == "test"

    def test_comptime_declaration(self, tmp_path: Path) -> None:
        """A comptime block is classified as symbol_type 'comptime'."""
        blocks = self._parse_zig(tmp_path)
        comptime_block = blocks[6]
        assert comptime_block.symbol_name == "(comptime)"
        assert comptime_block.symbol_type == "comptime"

    def test_start_end_lines_1_based(self, tmp_path: Path) -> None:
        """start_line and end_line use 1-based line numbers."""
        blocks = self._parse_zig(tmp_path)
        # All blocks should have positive line numbers
        for block in blocks:
            assert block.start_line >= 1
            assert block.end_line >= block.start_line

    def test_file_path_propagated(self, tmp_path: Path) -> None:
        """The relative file_path is propagated to all blocks."""
        blocks = self._parse_zig(tmp_path)
        for block in blocks:
            assert block.file_path == "test.zig"

    def test_language_set_on_blocks(self, tmp_path: Path) -> None:
        """All blocks have language set to 'zig'."""
        blocks = self._parse_zig(tmp_path)
        for block in blocks:
            assert block.language == "zig"

    def test_variable_declaration(self, tmp_path: Path) -> None:
        """A plain const variable (not struct/enum) is classified as 'variable'."""
        source = """\
const max_size: usize = 1024;
"""
        blocks = self._parse_zig(tmp_path, source)
        assert len(blocks) >= 1
        var_block = blocks[0]
        assert var_block.symbol_name == "max_size"
        assert var_block.symbol_type == "variable"

    def test_empty_file_produces_no_blocks(self, tmp_path: Path) -> None:
        """An empty .zig file produces no blocks."""
        zig_file = tmp_path / "empty.zig"
        zig_file.write_text("")
        doc = parse_code_file(zig_file, "zig", "empty.zig")
        assert doc is not None
        assert len(doc.blocks) == 0

    def test_pub_not_carried_across_non_decl_nodes(self, tmp_path: Path) -> None:
        """A stale ``pub`` modifier is cleared if a non-Decl node follows."""
        source = """\
pub fn first() void {}
fn second() void {}
"""
        blocks = self._parse_zig(tmp_path, source)
        # first should have pub prefix, second should not
        first = [b for b in blocks if b.symbol_name == "first"][0]
        second = [b for b in blocks if b.symbol_name == "second"][0]
        assert first.text.startswith("pub ")
        assert not second.text.startswith("pub ")


class TestKotlinParsing:
    """Tests for Kotlin code parsing via parse_code_file."""

    KOTLIN_SOURCE = """\
package com.example

class MyClass {
    fun greet(name: String): String {
        return "Hello, $name"
    }

    companion object {
        const val VERSION = "1.0"
    }
}

interface Greeter {
    fun greet(): String
}

enum class Color {
    RED, GREEN, BLUE
}

fun topLevelFunction(): Int {
    return 42
}

data class Point(val x: Int, val y: Int)

object Singleton {
    fun doStuff() {}
}
"""

    def _parse_kotlin(self, tmp_path: Path, source: str | None = None) -> list:
        """Write Kotlin source to a temp file and parse it, returning blocks."""
        kt_file = tmp_path / "test.kt"
        kt_file.write_text(source if source is not None else self.KOTLIN_SOURCE)
        doc = parse_code_file(kt_file, "kotlin", "test.kt")
        assert doc is not None, "parse_code_file returned None"
        return doc.blocks

    def test_kotlin_is_code_file(self) -> None:
        assert is_code_file(Path("Main.kt")) is True

    def test_kotlin_returns_kotlin(self) -> None:
        assert get_language(Path("Main.kt")) == "kotlin"

    def test_parses_without_error(self, tmp_path: Path) -> None:
        kt_file = tmp_path / "test.kt"
        kt_file.write_text(self.KOTLIN_SOURCE)
        doc = parse_code_file(kt_file, "kotlin", "test.kt")
        assert doc is not None
        assert doc.language == "kotlin"
        assert doc.file_path == "test.kt"

    def test_block_count(self, tmp_path: Path) -> None:
        """Expected: package (module_top), MyClass, Greeter, Color, topLevelFunction, Point, Singleton."""
        blocks = self._parse_kotlin(tmp_path)
        assert len(blocks) == 7

    def test_top_level_package_declaration(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        top = blocks[0]
        assert top.symbol_type == "module_top"
        assert "package" in top.text

    def test_class_declaration(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        cls = [b for b in blocks if b.symbol_name == "MyClass"][0]
        assert cls.symbol_type == "class"
        assert "fun greet" in cls.text

    def test_interface_declaration(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        iface = [b for b in blocks if b.symbol_name == "Greeter"][0]
        assert iface.symbol_type == "interface"

    def test_enum_class_declaration(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        enum = [b for b in blocks if b.symbol_name == "Color"][0]
        assert enum.symbol_type == "enum"

    def test_top_level_function(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        func = [b for b in blocks if b.symbol_name == "topLevelFunction"][0]
        assert func.symbol_type == "function"
        assert "return 42" in func.text

    def test_data_class_declaration(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        dc = [b for b in blocks if b.symbol_name == "Point"][0]
        assert dc.symbol_type == "data_class"

    def test_object_declaration(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        obj = [b for b in blocks if b.symbol_name == "Singleton"][0]
        assert obj.symbol_type == "object"
        assert "fun doStuff" in obj.text

    def test_companion_object_not_split(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        companions = [b for b in blocks if b.symbol_name == "companion"]
        assert len(companions) == 0

    def test_symbol_names(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        names = {b.symbol_name for b in blocks if b.symbol_type != "module_top"}
        assert names == {
            "MyClass",
            "Greeter",
            "Color",
            "topLevelFunction",
            "Point",
            "Singleton",
        }

    def test_start_end_lines_1_based(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        for block in blocks:
            assert block.start_line >= 1
            assert block.end_line >= block.start_line

    def test_file_path_propagated(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        for block in blocks:
            assert block.file_path == "test.kt"

    def test_language_set_on_blocks(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        for block in blocks:
            assert block.language == "kotlin"

    def test_sealed_class(self, tmp_path: Path) -> None:
        source = "sealed class Result {}\n"
        blocks = self._parse_kotlin(tmp_path, source)
        assert len(blocks) == 1
        assert blocks[0].symbol_name == "Result"
        assert blocks[0].symbol_type == "class"

    def test_abstract_class(self, tmp_path: Path) -> None:
        source = "abstract class Base {}\n"
        blocks = self._parse_kotlin(tmp_path, source)
        assert len(blocks) == 1
        assert blocks[0].symbol_name == "Base"
        assert blocks[0].symbol_type == "class"

    def test_annotation_class(self, tmp_path: Path) -> None:
        source = "annotation class MyAnnotation\n"
        blocks = self._parse_kotlin(tmp_path, source)
        assert len(blocks) == 1
        assert blocks[0].symbol_name == "MyAnnotation"
        assert blocks[0].symbol_type == "class"

    def test_empty_file_produces_no_blocks(self, tmp_path: Path) -> None:
        kt_file = tmp_path / "empty.kt"
        kt_file.write_text("")
        doc = parse_code_file(kt_file, "kotlin", "empty.kt")
        assert doc is not None
        assert len(doc.blocks) == 0

    def test_function_only_file(self, tmp_path: Path) -> None:
        source = 'fun main() { println("Hello") }\n'
        blocks = self._parse_kotlin(tmp_path, source)
        assert len(blocks) == 1
        assert blocks[0].symbol_name == "main"
        assert blocks[0].symbol_type == "function"

    def test_class_start_end_lines(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        cls = [b for b in blocks if b.symbol_name == "MyClass"][0]
        assert cls.start_line == 3
        assert cls.end_line == 11

    def test_function_start_end_lines(self, tmp_path: Path) -> None:
        blocks = self._parse_kotlin(tmp_path)
        func = [b for b in blocks if b.symbol_name == "topLevelFunction"][0]
        assert func.start_line == 21
        assert func.end_line == 23
