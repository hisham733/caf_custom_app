import frappe
from frappe.utils import now_datetime
from .rws import rws
import pdb
from frappe import _
from .wo_helpers import  get_active_wos_by_link_id
# Constants
STATUS_CHANGE_PACK = "Pack Change"
@frappe.whitelist()
def process_pack_change_or_add(doc_name: str, child_doctype: str) -> None:
    """
    Workflow for 'Chang or add Pack':
    1. Find existing Pack WO for the row.
    2. Validate: Error if already 'Completed'.
    3. Cancel: Kill ONLY the old Pack WO.
    4. Regenerate: Create new MR/PP/WO chain.
    5. Filter: Delete the new 'Cook' and 'WIP' WOs, keeping only the 'Pack'.
    """
    start_time = now_datetime()
    
    rows = frappe.get_all(
        child_doctype,
        filters={"parent": doc_name, "produ_status": STATUS_CHANGE_PACK},
        fields=["name", "link_id", "pack_name", "idx", "production_plane", "recipe_name"]
    )

    if not rows:
        return

    parent_doc = frappe.get_doc("Daily Production", doc_name)

    for r in rows:
        row_doc = frappe.get_doc(child_doctype, r.name)
        
        # 1. Get correct Identity Badge (Handles sub-rows)
        from .wo_helpers import get_active_link_id_from_row, get_all_pack_wos_by_link_id
        link_id = get_active_link_id_from_row(row_doc, child_doctype)
        # print(f"link_id:{link_id}")
        if not link_id:
            frappe.throw(_("Row {0}: Link ID not found. Cannot process pack change.").format(row_doc.idx))

        # 2. Check existing Pack WO status
        # We look for a WO that belongs to this link_id and produces this row's pack_name
        # pdb.set_trace()
        existing_pack_wo = get_all_pack_wos_by_link_id(link_id)

        print(existing_pack_wo)
        # pdb.set_trace()
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
        newly_born_wos = parent_doc.create_material_request_after_change_size(row_doc.recipe_name, full_group)

        # 5. Targeted Deletion: Remove everything EXCEPT the New Pack WO
        _cleanup_everything_except_new_pack(newly_born_wos, row_doc, child_doctype, start_time)

        # Finalize status (keep on recipe rows, only clear No Cooking)
        if row_doc.recipe_name == "No Cooking":
            row_doc.db_set("produ_status", "")

    rws(doc_name, child_doctype)
#     frappe.msgprint(_("✅ Packing update complete. Only the Packing Work Order was regenerated."),ala)

# ══════════════════════════════════════════════════════════════════════════════
#  Internal Helper for Pack Cleanup
# ══════════════════════════════════════════════════════════════════════════════
def _cancel_cook_pack_by_id(link_id: str) -> None:
    """Finds active WOs by ID badge and cancels only Pack types."""

    wos = get_active_wos_by_link_id(link_id)

    cook_pack_wos = [
        wo for wo in wos
        if wo.get("custom_item_type") in ["Pack"]
    ]

    from .cancellation import (
        _cancel_stock_entries_for_wo,
        _cancel_job_cards_for_wo
    )

    if not cook_pack_wos:
        return

    for wo_row in cook_pack_wos:
        wo_name = wo_row.name

        if not frappe.db.exists("Work Order", wo_name):
            continue

        print(f"\n🔥 Processing WO: {wo_name}")

        wo = frappe.get_doc("Work Order", wo_name)

        # ✅ STEP 1: Cancel dependencies first
        _cancel_stock_entries_for_wo(wo_name)
        _cancel_job_cards_for_wo(wo_name)

        # ✅ Skip already cancelled
        if wo.docstatus == 2:
            print(f"⏭ Already cancelled: {wo_name}")
            continue

        wo.flags.ignore_permissions = True
        wo.flags.ignore_workflow = True

        # ✅ Draft → delete
        if wo.docstatus == 0:
            print(f"🗑 Deleting WO: {wo_name}")
            wo.delete()
            continue

        # ✅ Submitted → cancel with retry
        success = False

        for attempt in range(2):
            try:
                wo.reload()
                wo.flags.ignore_version = True

                print(f"❌ Cancelling WO (attempt {attempt+1}): {wo_name}")
                wo.cancel()

                success = True
                break

            except frappe.TimestampMismatchError:
                print(f"⚠ Retry {attempt+1} due to version conflict: {wo_name}")

        if not success:
            frappe.log_error(
                f"Failed to cancel WO after retries: {wo_name}",
                "WO Cancellation Failed"
            )
            frappe.throw(
                f"Failed to cancel Work Order {wo_name} after retries."
            )

    # ✅ Commit after batch

def _cleanup_everything_except_new_pack(newly_born_wos, row_doc, child_doctype, start_time):
    """
    The opposite of WIP cleanup. 
    Deletes any fresh Cook or WIP WOs, keeping ONLY the Pack WO.
    Draft: deleted directly. Submitted: cancelled.
    """
    if not newly_born_wos:
        return

    for wo_name in newly_born_wos:
        info = frappe.db.get_value("Work Order", wo_name, ["custom_item_type", "docstatus", "creation"], as_dict=True)
        if not info: continue

        # Logic: If it is fresh and NOT a Pack WO, delete/cancel it.
        is_fresh = info.creation >= start_time if info.creation else False
        
        if is_fresh and info.custom_item_type in ["Cook", "WIP"]:
            if not frappe.db.exists("Work Order", wo_name):
                continue
            if info.docstatus == 0:
                frappe.delete_doc("Work Order", wo_name, ignore_permissions=True, force=True)
            elif info.docstatus == 1:
                wo = frappe.get_doc("Work Order", wo_name)
                wo.flags.ignore_permissions = True
                wo.flags.ignore_workflow = True
                wo.cancel()

