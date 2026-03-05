"""MCP tool: rag_convert — document conversion to markdown."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_convert tool."""

    @mcp.tool()
    def rag_convert(file_path: str) -> str:
        """Convert a document (PDF, DOCX, etc.) to markdown text.

        Supports PDF, DOCX, PPTX, XLSX, HTML, EPUB, images, and plain text.
        Results are cached — converting the same file twice is instant.

        Args:
            file_path: Path to the document file.
        """
        from ragling.tools.helpers import _convert_document, _get_user_context

        user_ctx = _get_user_context(ctx.server_config)
        mappings = user_ctx.path_mappings if user_ctx else {}
        return _convert_document(
            file_path,
            path_mappings=mappings,
            restrict_paths=user_ctx is not None,
            config=ctx.get_config(),
        )
