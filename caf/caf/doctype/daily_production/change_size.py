# Copyright (c) 2025, hisham and contributors
# change_size.py — ID-Driven Size Change Handler with Quality Data Migration

import frappe
from frappe import _
from frappe.utils import now_datetime
from .wo_helpers import (
    get_wo_by_type,
    get_active_wos_by_link_id,
    get_cook_quality_data_by_wo,
    remove_all_wip_wo
)
from .cancellation import (
    _cancel_work_orders_by_id,
    _cancel_production_plan,
)

# ── Constant ──────────────────────────────────────────────────────────────────
STATUS_CHANGE_SIZE = "Recipe Change"
WO_DOCTYPE = "Work Order"

# ══════════════════════════════════════════════════════════════════════════════
#  Internal Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _relink_quality_docs(quality_docs: list, new_cook_wo: str) -> None:
    """
    Updates the 'custom_work_order' field in Quality/Weight documents 
    to point to the newly created Cook Work Order.
    """
    if not quality_docs or not new_cook_wo:
        return

    for doc in quality_docs:
        # Use db_set to bypass 'Submitted' document restrictions
        frappe.db.set_value(doc["doctype"], doc["name"], "custom_work_order", new_cook_wo)
        
        frappe.msgprint(
            _("🔗 Re-linked <b>{0}</b> ({1}) to new Cook WO <b>{2}</b>")
            .format(doc["doctype"], doc["name"], new_cook_wo), 
            alert=True
        )


def _cleanup_redundant_wips_targeted(newly_born_list: list, row_doc, child_doctype, start_time):
    """
    Removes only 'WIP' Work Orders created in this transaction.
    Draft WIPs: deleted directly. Submitted WIPs: cancelled.
    Protects original WIPs by checking the creation timestamp.
    """
    if not newly_born_list: return
    
    for wo_name in newly_born_list:
        res = frappe.db.get_value(WO_DOCTYPE, wo_name, ["custom_item_type", "docstatus", "creation"], as_dict=True)
        
        if not res or res.custom_item_type != "WIP" or res.creation < start_time:
            continue
        if not frappe.db.exists(WO_DOCTYPE, wo_name):
            continue
        
        if res.docstatus == 0:
            frappe.delete_doc(WO_DOCTYPE, wo_name, ignore_permissions=True, force=True)
        elif res.docstatus == 1:
            wo = frappe.get_doc(WO_DOCTYPE, wo_name)
            wo.flags.ignore_permissions = True
            wo.flags.ignore_workflow = True
            wo.cancel()
    
    # # Update Grid UI to reflect the current active WOs in DB
    # from .rearrange_and_change_slot import _refresh_row_ui_strings
    # _refresh_row_ui_strings(row_doc, child_doctype)


# ══════════════════════════════════════════════════════════════════════════════
#  Main Entry Point
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def process_size_change(doc_name: str, child_doctype: str) -> None:
    """
    Triggered for rows with status "Recipe Change".
    1. Validation: Uses link_id to check if Cook WO is 'Completed'.
    2. Backup: Saves Quality Data linked to the old Cook WO.
    3. Cancellation: Kills old Cook/Pack WOs based on identity.
    4. Re-creation: Triggers fresh production with new quantity.
    5. Cleanup: Purges fresh duplicate WIPs.
    6. Relink: Points old Quality docs to the new Cook WO.
    """
    # 0. Capture process start time for WIP protection
    process_start_time = now_datetime()

    # 1. Fetch rows marked for size change
    rows = frappe.get_all(
        child_doctype,
        filters={
            "parent"      : doc_name,
            "produ_status": STATUS_CHANGE_SIZE,
        },
        fields=["name", "idx", "recipe_name", "link_id", "production_plane","production_type"],
        order_by="idx asc",
    )

    if not rows:
        return

    # Load parent doc explicitly
    parent_doc = frappe.get_doc("Daily Production", doc_name)

    for r in rows:
        row_doc = frappe.get_doc(child_doctype, r.name)
        link_id = r.link_id
        reheat = r.production_type
        # ── STEP 1: IDENTITY & VALIDATION ──────────────────────────────────
        # Find the current active Cook WO for this identity
        old_cook_wo = get_wo_by_type(link_id, "Cook")

        if old_cook_wo:
            # Check the actual status in the database
            wo_status = frappe.db.get_value(WO_DOCTYPE, old_cook_wo, "status")
            if wo_status == "Completed":
                frappe.throw(
                    _("🛑 <b>Row {0} Error:</b> Cannot Change Recipe for <b>{1}</b>. "
                      "The Cook Work Order {2} is already <b>Completed</b>.")
                    .format(row_doc.idx, row_doc.recipe_name, frappe.utils.get_link_to_form(WO_DOCTYPE, old_cook_wo))
                )

        # ── STEP 2: BACKUP QUALITY DATA ────────────────────────────────────
        # Fetch Quality Reviews and Weight Records linked to the old WO
        quality_docs = get_cook_quality_data_by_wo(old_cook_wo)

        # ── STEP 3: CANCELLATION PHASE ─────────────────────────────────────
        # Cancel only Cook and Pack WOs belonging to this Link ID
        _cancel_work_orders_by_id(link_id)

        # Cancel the Production Plan to reset demand for this slot
        if r.production_plane:
            pp = r.production_plane
            row_doc.db_set("production_plane", "")
            # _cancel_production_plan(pp)

            # Clear specific row pointers but KEEP link_id and mr_reference
            row_doc.db_set("wo_list", "")
            row_doc.db_set("production_plane", "")
            row_doc.db_set("wo_list_with_type", "")

            # ── STEP 4: RE-CREATION PHASE ──────────────────────────────────────
            # Returns the list of ONLY the WOs created in this transaction
            full_group = parent_doc.get_full_group_for_row(row_doc)
            newly_born_wos = parent_doc.create_material_request_after_change_size(row_doc.recipe_name, full_group)

            # ── STEP 5: PRECISION WIP CLEANUP ──────────────────────────────────
            # Deletes redundant WIP drafts created in Step 4
            _cleanup_redundant_wips_targeted(newly_born_wos, row_doc, child_doctype, process_start_time)

            # ── STEP 6: RE-LINK PHASE ──────────────────────────────────────────
            # Reload to find the newly created Cook WO ID
            row_doc.reload()
            new_cook_wo = get_wo_by_type(link_id, "Cook")

            if new_cook_wo and quality_docs:
                _relink_quality_docs(quality_docs, new_cook_wo)

            # Update status to finalized (keep on recipe rows, only clear No Cooking)
            if row_doc.recipe_name == "No Cooking":
                row_doc.db_set("produ_status", "")
            if link_id and reheat == "Reheat":
                remove_all_wip_wo(link_id,work=True)

    frappe.msgprint( 
        _("✅ <b>Size Change Successful:</b> Work Orders updated and Quality records migrated via Link ID <b>{0}</b>.")
        .format(link_id)
    )