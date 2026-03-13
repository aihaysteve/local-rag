"""MCP tool: rag_search_task — task-aware SPEC.md search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ragling.tools.context import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the rag_search_task tool."""

    @mcp.tool()
    def rag_search_task(
        query: str,
        task_context: dict[str, Any] | None = None,
        task_type: str = "implementation",
    ) -> dict[str, Any]:
        """Search SPEC.md files with task-aware retrieval strategy.

        Implements H1 (query reformulation) and H2 (subsystem-aware filtering + dependency
        expansion) solutions from issue #45 experiments. Optimizes spec retrieval for code
        review, cross-subsystem discovery, invariant checking, and implementation tasks.

        Task types select different retrieval strategies:
        - **"code_review"**: Subsystem-aware filtering + dependency expansion
          Best for reviewing commits that touch multiple subsystems. Detects subsystems
          from file paths, queries each SPEC.md separately (eliminates corpus skew),
          then expands results with documented cross-subsystem dependencies.
        - **"cross_cutting"**: Per-subsystem querying with explicit subsystem list
          Best for commits that affect multiple subsystems. Requires subsystems list
          in task_context["subsystems"] or will auto-detect from commit/files.
        - **"invariant_check"**: Invariant-targeted query reformulation
          Best for checking what invariants a change might violate. Appends "invariant"
          to query to shift embedding toward declarative constraint language.
        - **"implementation"**: Hybrid (all approaches)
          Combines filtering, expansion, and query reformulation for maximum coverage.

        Args:
            query: The search query (commit message, task description, etc.)
            task_context: Optional context dict with:
                - commit_sha: Git commit SHA (auto-detects subsystems touched)
                - file_paths: List of file paths changed (detects subsystems)
                - subsystems: Explicit list of subsystem names to query
            task_type: Strategy to use ("code_review", "cross_cutting", "invariant_check",
                "implementation"). Default: "implementation" (maximum coverage).

        Returns:
            Dict with:
            - "results": List of SPEC.md results organized by subsystem
            - "strategy": Strategy used
            - "subsystems_queried": Subsystems that were searched
            - "coverage": Summary of coverage achieved
        """
        from ragling.config import load_config
        from ragling.parsers.spec import parse_dependency_edges
        from ragling.search.search import BatchQuery, perform_batch_search, perform_search
        from ragling.tools.helpers import (
            _detect_subsystems_from_paths,
            _get_visible_collections,
            _result_to_dict,
        )

        visible = _get_visible_collections(ctx.server_config)
        task_context = task_context or {}

        # --- Detect subsystems from context ---
        subsystems: list[str] = task_context.get("subsystems", [])

        if not subsystems and task_context.get("file_paths"):
            subsystems = _detect_subsystems_from_paths(task_context["file_paths"])

        # --- H1: Query reformulation ---
        reformulated_query = query
        if task_type in ("invariant_check", "implementation"):
            reformulated_query = f"{query} invariant"

        # --- Step 1: Generic spec search ---
        generic_results, _reranked = perform_search(
            query=reformulated_query,
            source_type="spec",
            top_k=10,
            group_name=ctx.group_name,
            config=ctx.server_config,
            visible_collections=visible,
        )

        # Collect subsystems found so far
        found_subsystems: dict[str, list] = {}
        for r in generic_results:
            sub = r.metadata.get("subsystem_name", "")
            if sub and sub not in found_subsystems:
                found_subsystems[sub] = []
            if sub:
                found_subsystems[sub].append(r)

        # --- Step 2: Per-subsystem filtered search (H2) ---
        if task_type in ("code_review", "cross_cutting", "implementation") and subsystems:
            missing = [s for s in subsystems if s not in found_subsystems]
            if missing:
                batch = [
                    BatchQuery(
                        query=f"{s} subsystem invariant",
                        source_type="spec",
                        subsystem=s,
                        top_k=3,
                    )
                    for s in missing
                ]
                per_sub_results, _flags = perform_batch_search(
                    batch,
                    group_name=ctx.group_name,
                    config=ctx.server_config,
                    visible_collections=visible,
                )
                for sub_name, results in zip(missing, per_sub_results):
                    if results:
                        found_subsystems[sub_name] = results

        # --- Step 3: Dependency expansion (H2) ---
        if task_type in ("code_review", "cross_cutting", "implementation"):
            dep_subsystems: set[str] = set()
            for sub_name, results in list(found_subsystems.items()):
                for r in results:
                    section_type = r.metadata.get("section_type", "")
                    if section_type == "dependencies":
                        edges = parse_dependency_edges(r.content)
                        for edge_path in edges:
                            parts = edge_path.replace("SPEC.md", "").rstrip("/").split("/")
                            if parts:
                                dep_subsystems.add(parts[-1].title())

            # Fetch dependency sections for found subsystems to discover edges
            if found_subsystems:
                dep_batch = [
                    BatchQuery(
                        query=f"{s} dependencies internal SPEC.md",
                        source_type="spec",
                        subsystem=s,
                        top_k=1,
                    )
                    for s in found_subsystems
                ]
                dep_results, _dep_flags = perform_batch_search(
                    dep_batch,
                    group_name=ctx.group_name,
                    config=ctx.server_config,
                    visible_collections=visible,
                )
                for results in dep_results:
                    for r in results:
                        if r.metadata.get("section_type") == "dependencies":
                            edges = parse_dependency_edges(r.content)
                            for edge_path in edges:
                                parts = edge_path.replace("SPEC.md", "").rstrip("/").split("/")
                                if parts:
                                    dep_subsystems.add(parts[-1].title())

            # Fetch specs for dependency subsystems not yet found
            expansion_targets = [s for s in dep_subsystems if s not in found_subsystems]
            if expansion_targets:
                exp_batch = [
                    BatchQuery(
                        query=f"{s} subsystem invariant",
                        source_type="spec",
                        subsystem=s,
                        top_k=3,
                    )
                    for s in expansion_targets
                ]
                exp_results, _exp_flags = perform_batch_search(
                    exp_batch,
                    group_name=ctx.group_name,
                    config=ctx.server_config,
                    visible_collections=visible,
                )
                for sub_name, results in zip(expansion_targets, exp_results):
                    if results:
                        found_subsystems[sub_name] = results

        # --- Build response ---
        obsidian_vaults = (ctx.server_config or load_config()).obsidian_vaults
        response_results = []
        for sub_name, results in found_subsystems.items():
            for r in results:
                result_dict = _result_to_dict(r, obsidian_vaults)
                result_dict["subsystem"] = sub_name
                response_results.append(result_dict)

        return {
            "results": response_results,
            "strategy": task_type,
            "subsystems_queried": list(found_subsystems.keys()),
            "coverage": {
                "subsystems_found": len(found_subsystems),
                "requested_subsystems": subsystems or [],
                "expanded_via_deps": list(
                    set(found_subsystems.keys())
                    - set(subsystems)
                    - set(s for r in generic_results if (s := r.metadata.get("subsystem_name")))
                )
                if subsystems
                else [],
            },
        }
