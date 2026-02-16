"""Path prefix mapping for translating host <-> container paths."""


def apply_forward(path: str, mappings: dict[str, str]) -> str:
    """Map a host path to a container path (longest prefix match).

    Args:
        path: Host-side path.
        mappings: {host_prefix: container_prefix} dict.

    Returns:
        Mapped path, or original if no prefix matches.
    """
    best_prefix = ""
    best_replacement = ""
    for host_prefix, container_prefix in mappings.items():
        if path.startswith(host_prefix) and len(host_prefix) > len(best_prefix):
            best_prefix = host_prefix
            best_replacement = container_prefix
    if best_prefix:
        return best_replacement + path[len(best_prefix) :]
    return path


def apply_reverse(path: str, mappings: dict[str, str]) -> str:
    """Map a container path to a host path (longest prefix match).

    Args:
        path: Container-side path.
        mappings: {host_prefix: container_prefix} dict (same format as forward).

    Returns:
        Mapped host path, or original if no prefix matches.
    """
    best_container = ""
    best_host = ""
    for host_prefix, container_prefix in mappings.items():
        if path.startswith(container_prefix) and len(container_prefix) > len(best_container):
            best_container = container_prefix
            best_host = host_prefix
    if best_container:
        return best_host + path[len(best_container) :]
    return path


def apply_forward_uri(uri: str | None, mappings: dict[str, str]) -> str | None:
    """Apply forward mapping to a source_uri string.

    Handles file:// and vscode:// URIs. Leaves obsidian:// and https:// unchanged.

    Args:
        uri: Source URI string or None.
        mappings: {host_prefix: container_prefix} dict.

    Returns:
        Mapped URI, or original if not applicable.
    """
    if uri is None:
        return None
    if uri.startswith("file:///"):
        path = uri[len("file://") :]
        mapped = apply_forward(path, mappings)
        return f"file://{mapped}"
    if uri.startswith("vscode://file"):
        path = uri[len("vscode://file") :]
        mapped = apply_forward(path, mappings)
        return f"vscode://file{mapped}"
    return uri
