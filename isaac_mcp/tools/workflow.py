"""Source-aware workflow tools. No implicit build, playback or whole-layer save."""

from typing import Any, Dict, List, Optional


def register_tools(mcp, get_connection):
    @mcp.tool("preview_source_commit")
    def preview_source_commit(expected_context: Dict[str, Any], prim_path: str, attributes: List[str],
                              target_layer: Optional[str] = None, allow_shared: bool = False) -> dict:
        """Plan selected Session defaults into one owning file; never saves or rebuilds.

        Args:
            expected_context: Exact context from get_stage_composition or get_mpm_config.
            prim_path: Existing prim whose parameters should be committed.
            attributes: Explicit attribute names, not a subtree. No time samples or generated particle data.
            target_layer: Owning layer identifier when composition contains multiple candidates.
            allow_shared: Explicitly accept changes affecting other loaded instances of the source.
        """
        return get_connection().send_command("workflow.preview_source_commit", {
            "expected_context": expected_context, "prim_path": prim_path, "attributes": attributes,
            "target_layer": target_layer, "allow_shared": allow_shared})

    @mcp.tool("commit_source_changes")
    def commit_source_changes(plan_id: str, save: bool = True) -> dict:
        """Apply an explicit source-commit plan. May write one file; never plays or rebuilds.

        Args:
            plan_id: Unexpired plan returned by preview_source_commit. Changed layers invalidate it.
            save: True saves the owning file; false authors memory only and clears selected Session defaults.
        """
        return get_connection().send_command("workflow.commit_source_changes", {"plan_id": plan_id, "save": save})

    @mcp.tool("undo_stage_transaction")
    def undo_stage_transaction(transaction_id: str, preview: bool = True) -> dict:
        """Preview or undo a retained USD memory transaction, not a disk save or particle rebuild.

        Args:
            transaction_id: ID returned by apply_stage_batch or update_mpm_config.
            preview: True checks eligibility; false restores only if no subsequent edit/save conflicts.
        """
        return get_connection().send_command("workflow.undo_stage_transaction", {
            "transaction_id": transaction_id, "preview": preview})
