import frappe
from frappe.utils import now_datetime
from .wo_helpers import get_active_wos_by_link_id
from .cancellation import cancel_wos_by_link_id, cleanup_wos_by_type
# Constants
STATUS_CHANGE_PACK = "Pack Change"
@frappe.whitelist()
def process_pack_change_or_add(doc_or_name, child_doctype: str, row_name: str = None) -> None:
    """
    Workflow for 'Chang or add Pack':
    1. Find existing Pack WO for the row.
    2. Validate: Error if already 'Completed'.
    3. Cancel: Kill ONLY the old Pack WO.
    4. Regenerate: Create new MR/PP/WO chain.
    5. Filter: Delete the new 'Cook' and 'WIP' WOs, keeping only the 'Pack'.

    Phase 3: Accepts doc object OR doc_name string (backward compatible).
    """
    parent_doc = doc_or_name if not isinstance(doc_or_name, str) else frappe.get_doc("Daily Production", doc_or_name)
    doc_name = parent_doc.name
    start_time = now_datetime()
    
    filters = {"parent": doc_name, "produ_status": STATUS_CHANGE_PACK}
    if row_name:
        filters["name"] = row_name
    rows = frappe.get_all(
        child_doctype,
        filters=filters,
        fields=["name", "link_id", "pack_name", "idx", "production_plane", "recipe_name"]
    )

    if not rows:
        return

    for r in rows:
        row_doc = next((d for d in parent_doc.production_table if d.name == r.name), None)
        if not row_doc:
            continue
        
        # 1. Get correct Identity Badge (Handles sub-rows)
        from .wo_helpers import get_active_link_id_from_row, get_all_pack_wos_by_link_id
        link_id = get_active_link_id_from_row(row_doc, child_doctype)
        if not link_id:
            frappe.throw(_("Row {0}: Link ID not found. Cannot process pack change.").format(row_doc.idx))

        # 2. Check existing Pack WO status
        # We look for a WO that belongs to this link_id and produces this row's pack_name
        existing_pack_wo = get_all_pack_wos_by_link_id(link_id)

        for e in existing_pack_wo:
            # if e:
            #       wo_status = frappe.db.get_value("Work Order", e, "status")
            #       if wo_status == "Completed":
            #             frappe.throw(
            #                   _("🛑 Row {0}: Cannot change/add pack because Work Order {1} is already <b>Completed</b>.")
            #                   .format(row_doc.idx, frappe.utils.get_link_to_form("Work Order", existing_pack_wo))
            #             )
            #     #   print(f"existing_pack_wo: {e}")

            _cancel_cook_pack_by_id(link_id)
        # 4. Re-creation Phase
        # This triggers MR -> PP -> full chain of WOs
        full_group = parent_doc.get_full_group_for_row(row_doc)
        newly_born_wos = parent_doc.recreate_mr_after_update_slot(row_doc.recipe_name, full_group)

        # 5. Targeted Deletion: Remove everything EXCEPT the New Pack WO
        _cleanup_everything_except_new_pack(newly_born_wos, row_doc, child_doctype, start_time)

        # Finalize status (keep on recipe rows, only clear No Cooking)
        if row_doc.recipe_name == "No Cooking":
            row_doc.db_set("produ_status", "")

#     frappe.msgprint(_("✅ Packing update complete. Only the Packing Work Order was regenerated."),ala)

# ══════════════════════════════════════════════════════════════════════════════
#  Internal Helper for Pack Cleanup
# ══════════════════════════════════════════════════════════════════════════════
def _cancel_cook_pack_by_id(link_id: str) -> None:
    """Cancels only Pack WOs for a given link_id."""
    cancel_wos_by_link_id(link_id, types=["Pack"])


def _cleanup_everything_except_new_pack(newly_born_wos, row_doc, child_doctype, start_time):
    """Deletes fresh Cook/WIP WOs, keeping ONLY the Pack WO."""
    cleanup_wos_by_type(newly_born_wos, keep_types=["Pack"], child_doctype=child_doctype, start_time=start_time)

