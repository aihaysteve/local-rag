"""Search utilities for safe query handling."""


def escape_fts_query(query: str) -> str:
    """Escape user input for safe use in FTS5 MATCH queries.

    Treats the entire input as a literal search phrase.
    Doubles internal double-quotes and wraps in double quotes
    per SQLite FTS5 spec (section 3.1).

    SQL parameterization prevents injection but does NOT prevent
    FTS syntax abuse within the parameter itself. Both layers are needed.
    """
    stripped = query.strip()
    if not stripped:
        return ""
    escaped = stripped.replace('"', '""')
    return f'"{escaped}"'
