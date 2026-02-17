"""Tests for ragling.parsers.code -- extension map and language detection."""

from pathlib import Path

from ragling.parsers.code import get_language, is_code_file


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
