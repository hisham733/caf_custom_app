# Copyright (c) 2025, hisham and contributors
# rws.py — ID-Driven Sync for Work Order Notes only

import frappe
from frappe import _

from .wo_helpers import (
    get_wo_by_type,
    get_all_pack_wos_by_link_id,
    get_active_link_id_from_row,
    get_recipe_note_from_parent_row,
    validate_wo_for_change,
    update_wo_field,
)

# ══════════════════════════════════════════════════════════════════════════════
#  Row Processor (Notes Only)
# ══════════════════════════════════════════════════════════════════════════════

def _sync_row_notes_to_wos(row, child_doctype: str) -> None:
    """
    Finds the correct Work Orders via link_id and updates 
    ONLY their custom_note fields.
    """
    # 1. Skip if no item is defined to be packed in this row
    if not row.get("pack_name"):
        return

    # 2. Get Identity (Handle continuation rows by walking up if link_id is empty)
    link_id = get_active_link_id_from_row(row, child_doctype)
    if not link_id:
        return

    # 3. Update Pack Work Order Notes
    # Finds all Pack WOs linked to this identity badge
    pack_wos = get_all_pack_wos_by_link_id(link_id)
    
    for wo_name in pack_wos:
        if wo_name:
            # validate_wo_for_change(wo_name)
            # Sync the Pack Note from the grid to the Work Order
            update_wo_field(wo_name, "custom_note", row.get("pack_note") or "")

    # 4. Update Cook Work Order Notes
    # Finds the Cook WO belonging to this identity badge
    cook_wo = get_wo_by_type(link_id, "Cook")
    
    if cook_wo:
        # validate_wo_for_change(cook_wo)
        
        # Get recipe note (walks up to parent recipe row if current row is empty)
        recipe_note = get_recipe_note_from_parent_row(row, child_doctype)
        
        if recipe_note is not None:
            # Sync the Recipe Note from the grid to the Cook Work Order
            update_wo_field(cook_wo, "custom_note", recipe_note)


# ══════════════════════════════════════════════════════════════════════════════
#  Main Entry Point
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def rws(doc_or_name, child_doctype: str, row_name: str = None) -> None:
    """
    Iterates through all production rows and ensures the linked 
    Work Orders (found via Link ID) have updated notes.

    Phase 3: Accepts doc object OR doc_name string.
    """
    doc_name = doc_or_name.name if hasattr(doc_or_name, 'name') else doc_or_name
    
    # Fetch only rows that have a pack_name (avoids loading 64 empty rows)
    filters = {
        "parent": doc_name,
        "pack_name": ["!=", ""],
    }
    if row_name:
        filters["name"] = row_name
    rows = frappe.get_all(
        child_doctype,
        filters=filters,
        fields=["name", "pack_name", "link_id", "pack_note", "recipe_note", "parent", "idx"],
        order_by="idx asc"
    )

    if not rows:
        return

    processed_count = 0

    for row in rows:
        # Directly pass dict — no frappe.get_doc() needed
        _sync_row_notes_to_wos(row, child_doctype)
        processed_count += 1

    if processed_count > 0:
        frappe.msgprint(
            _("✅ Note Sync complete: Updated notes for {0} production items.")
            .format(processed_count),alert=True
        )