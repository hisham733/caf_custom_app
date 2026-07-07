# Copyright (c) 2025, hisham and contributors
# rearrange_and_change_slot.py — ID-Driven Production Handover & Migration

import pdb
from collections import defaultdict
import frappe
from frappe import _
from frappe.utils import now_datetime
# FIXED: Added get_active_wos_by_link_id to imports
from .wo_helpers import get_active_link_id_from_row, get_wo_by_type, get_active_wos_by_link_id
from .cancellation import _bulk_clean_stock_and_jobs,_cancel_work_orders_by_id
from .rws import rws

STATUS_CHANGE_SLOT = "Change Slot"
STATUS_SWITCH       = "Rearrange"
NO_COOKING          = "No Cooking"
WO_DOCTYPE          = "Work Order"

# ══════════════════════════════════════════════════════════════════════════════
#  Internal ID-Based Logic
# ══════════════════════════════════════════════════════════════════════════════

def _swap_db_link_ids(id_a: str, id_b: str) -> None:
    """Swap custom_link_id between two rows using a temp ID.

    Swaps Work Orders and Stock Entries by reassigning custom_link_id.
    Uses a temporary hash to avoid collisions during the swap.
    Commits if not in_submit.
    """
    cnt_a = frappe.db.count("Work Order", {"custom_link_id": id_a})
    cnt_b = frappe.db.count("Work Order", {"custom_link_id": id_b})

    temp_id = f"TEMP-{frappe.generate_hash(length=8)}"
    

    
    # ─ SWAP WORK ORDERS
    frappe.db.sql("UPDATE `tabWork Order` SET custom_link_id = %s WHERE custom_link_id = %s", (temp_id, id_a))
    frappe.db.sql("UPDATE `tabWork Order` SET custom_link_id = %s WHERE custom_link_id = %s", (id_a, id_b))
    frappe.db.sql("UPDATE `tabWork Order` SET custom_link_id = %s WHERE custom_link_id = %s", (id_b, temp_id))
    
    # ─ SWAP STOCK ENTRIES
    se_cnt_a = frappe.db.count("Stock Entry", {"custom_link_id": id_a})
    se_cnt_b = frappe.db.count("Stock Entry", {"custom_link_id": id_b})
    
    if se_cnt_a > 0 or se_cnt_b > 0:

        
        frappe.db.sql(
            "UPDATE `tabStock Entry` SET custom_link_id = %s WHERE custom_link_id = %s", 
            (temp_id, id_a)
        )
        frappe.db.sql(
            "UPDATE `tabStock Entry` SET custom_link_id = %s WHERE custom_link_id = %s", 
            (id_a, id_b)
        )
        frappe.db.sql(
            "UPDATE `tabStock Entry` SET custom_link_id = %s WHERE custom_link_id = %s", 
            (id_b, temp_id)
        )
        
        if not frappe.flags.in_submit:
            frappe.db.commit()

    else:
        print(f"   ⚠️  No Stock Entries found with custom_link_id")

def _migrate_db_link_ids(source_id: str, target_id: str) -> None:
    """Migrate custom_link_id from source row to target slot.

    One-way move (not a swap). Used for Change Slot where a recipe
    moves into an empty slot. Reassigns Work Orders and Stock Entries
    from source link_id to target link_id.

    Args:
        source_id: Link ID with active WOs (currently has the recipe)
        target_id: Link ID in the target slot (becomes new home)
    """
    # ─────────────────────────────────────────────────────────────────────
    # 1. MIGRATE WORK ORDERS
    # ─────────────────────────────────────────────────────────────────────
    frappe.db.sql(
        "UPDATE `tabWork Order` SET custom_link_id = %s WHERE custom_link_id = %s", 
        (target_id, source_id)
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # 2. MIGRATE STOCK ENTRIES
    # ─────────────────────────────────────────────────────────────────────
    frappe.db.sql(
        "UPDATE `tabStock Entry` SET custom_link_id = %s WHERE custom_link_id = %s", 
        (target_id, source_id)
    )


def _cancel_cook_pack_by_id(link_id: str) -> None:
    """Cancel all active Cook and Pack WOs for a given link_id.

    Gets active WOs via get_active_wos_by_link_id, filters to Cook/Pack
    types, then cancels (or deletes if draft) each one.
    """
    wos = get_active_wos_by_link_id(link_id)
    cook_pack_wos = [wo for wo in wos if wo.get("custom_item_type") in ["Cook", "Pack"]]
    if cook_pack_wos:
       for wo in cook_pack_wos:
        if not frappe.db.exists("Work Order", wo.name): continue
        wo = frappe.get_doc("Work Order", wo.name)
        
        if wo.docstatus == 2: continue
        
        wo.flags.ignore_permissions = True
        wo.flags.ignore_workflow = True
        
        if wo.docstatus == 0:
            wo.delete()
        else:
            wo.cancel()

def _get_quality_data_by_id(link_id: str) -> list:
    """Get Quality Reviews and Weight Records for a link_id's Cook WO."""
    cook_wo = get_wo_by_type(link_id, "Cook")
    if not cook_wo: return []
    
    qrs = [{"name": d.name, "doctype": "Quality Review"} for d in frappe.get_all("Quality Review", filters={"custom_work_order": cook_wo})]
    wrs = [{"name": d.name, "doctype": "Weight Record"} for d in frappe.get_all("Weight Record", filters={"custom_work_order": cook_wo})]
    return qrs + wrs

def _relink_quality_docs(quality_docs: list, new_cook_wo: str) -> None:
    """Reassign quality docs (QR/Weight Record) to a new Cook WO."""
    if not quality_docs or not new_cook_wo: return
    for doc in quality_docs:
        frappe.db.set_value(doc["doctype"], doc["name"], "custom_work_order", new_cook_wo)

def _cleanup_redundant_wips(newly_created_wos: list, row_doc, child_doctype: str, start_time) -> None:
    """Deletes only WIP Work Orders created in the current transaction."""
    if not newly_created_wos: return

    for wo_name in newly_created_wos:
        res = frappe.db.get_value(WO_DOCTYPE, wo_name, ["custom_item_type", "docstatus", "creation"], as_dict=True)
        if res and res.custom_item_type == "WIP" and res.docstatus == 0 :
            if frappe.db.exists(WO_DOCTYPE, wo_name):
                frappe.delete_doc(WO_DOCTYPE, wo_name, ignore_permissions=True, force=True)

    # UI Cleanup: Regenerates the grid strings based on live database state
    _refresh_row_from_db(row_doc, child_doctype)

def _refresh_row_from_db(row_doc, child_doctype: str):
    """Syncs the grid UI with the current Work Orders in the database for this ID."""
    # FIXED: Changed from get_active_link_id_from_row to get_active_wos_by_link_id
    wos = get_active_wos_by_link_id(row_doc.link_id)
    valid_names = [w.name for w in wos]
    valid_types = [f"({w.name},{w.get('custom_item_type')})" for w in wos]

    frappe.db.set_value(child_doctype, row_doc.name, {
        "wo_list": "\n".join(valid_names),
        "wo_list_with_type": ",".join(valid_types)
    }, update_modified=False)

def _get_movable_fields(child_doctype: str) -> list:
    """Return user-editable field names from the child doctype, excluding fixed/system fields."""
    meta = frappe.get_meta(child_doctype)
    fixed = {"recipe_cook_workstaion", "recipe_cook_round", "link_id", "idx", "name", "produ_status", "parent"}
    return [f.fieldname for f in meta.fields if f.fieldname not in fixed and f.fieldtype not in {"Section Break", "Column Break", "Tab Break", "HTML", "Button"}]

# ══════════════════════════════════════════════════════════════════════════════
#  Pair Grouping Helper
# ══════════════════════════════════════════════════════════════════════════════

def _group_rows_by_pair(rows: list, status_label: str) -> list:
    """
    Groups rows by custom_pair_id. Each group must have exactly 2 rows.
    Falls back to sequential pairing (2 at a time by idx) if no pair_id is set.
    """
    groups = defaultdict(list)

    has_pair_id = any(r.get("custom_pair_id") for r in rows)
    if has_pair_id:
        for r in rows:
            groups[r.custom_pair_id].append(r)
    else:
        for i in range(0, len(rows), 2):
            if i + 1 < len(rows):
                groups[f"seq_{i//2}"] = [rows[i], rows[i + 1]]

    for pid, group in groups.items():
        if len(group) != 2:
            frappe.throw(
                _("{0}: Pair has {1} rows instead of 2 (Row {2}). Please redo the operation.")
                .format(status_label, len(group), group[0].idx)
            )

    return list(groups.values())


# ══════════════════════════════════════════════════════════════════════════════
#  Main Entry Points
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def process_switch(doc_name: str, child_doctype: str) -> None:
    """Entry point for Rearrange: swap link_ids between paired rows, cancel/recreate WOs, and relink quality docs.

    Args:
        doc_name: Name of the parent Daily Production document.
        child_doctype: Child table doctype containing production rows.
    """
    start_time = now_datetime()
    rows = frappe.get_all(
        child_doctype,
        filters={"parent": doc_name, "produ_status": STATUS_SWITCH},
        fields=["name", "link_id", "idx", "custom_pair_id"],
        order_by="idx asc"
    )
    if not rows:
        return

    parent_doc = frappe.get_doc("Daily Production", doc_name)
    pairs = _group_rows_by_pair(rows, "Rearrange")

    for pair in pairs:
        _process_one_switch_pair(pair, parent_doc, child_doctype, start_time)

    rws(doc_name, child_doctype)
    frappe.msgprint(_("✅ Rearrange Complete. {0} pair(s) processed.").format(len(pairs)))


def _process_one_switch_pair(pair: list, parent_doc, child_doctype: str, start_time) -> None:
    """Process a single Rearrange pair (swap link_ids, cancel, recreate, relink)."""
    row_a = frappe.get_doc(child_doctype, pair[0].name)
    row_b = frappe.get_doc(child_doctype, pair[1].name)

    qual_a = _get_quality_data_by_id(row_a.link_id)
    qual_b = _get_quality_data_by_id(row_b.link_id)
    _swap_db_link_ids(row_a.link_id, row_b.link_id)

    _cancel_cook_pack_by_id(row_a.link_id)
    _cancel_cook_pack_by_id(row_b.link_id)

    for r in (row_a, row_b):
        r.reload()
        full_group = parent_doc.get_full_group_for_row(r)
        new_cycle_wos = parent_doc.create_material_request_after_change_size(r.recipe_name, full_group)
        _cleanup_redundant_wips(new_cycle_wos, r, child_doctype, start_time)

    for r, q_data in [(row_a, qual_b), (row_b, qual_a)]:
        new_cook = get_wo_by_type(r.link_id, "Cook")
        if new_cook:
            _relink_quality_docs(q_data, new_cook)


@frappe.whitelist()
def process_slot_swaps(doc_name: str, child_doctype: str) -> None:
    """Entry point for Change Slot: migrate link_id from a source row into an empty target slot.

    Args:
        doc_name: Name of the parent Daily Production document.
        child_doctype: Child table doctype containing production rows.
    """
    start_time = now_datetime()
    rows = frappe.get_all(
        child_doctype,
        filters={"parent": doc_name, "produ_status": STATUS_CHANGE_SLOT},
        fields=["name", "recipe_name", "link_id", "idx", "custom_pair_id"],
        order_by="idx asc"
    )

    if not rows:
        return

    parent_doc = frappe.get_doc("Daily Production", doc_name)
    pairs = _group_rows_by_pair(rows, "Change Slot")

    for pair in pairs:
        _process_one_slot_swap_pair(pair, parent_doc, child_doctype, start_time)

    frappe.msgprint(_("✅ Slot swap complete. {0} pair(s) processed.").format(len(pairs)))


def _process_one_slot_swap_pair(pair: list, parent_doc, child_doctype: str, start_time) -> None:
    """Process a single Change Slot pair (migrate link_id, cancel, recreate, relink)."""
    row_1 = frappe.get_doc(child_doctype, pair[0].name)
    row_2 = frappe.get_doc(child_doctype, pair[1].name)

    if row_1.recipe_name != NO_COOKING:
        target, source = row_1, row_2
    else:
        target, source = row_2, row_1

    quality_data = _get_quality_data_by_id(source.link_id)

    _migrate_db_link_ids(source_id=source.link_id, target_id=target.link_id)
    _cancel_cook_pack_by_id(target.link_id)

    target.reload()
    new_cycle_wos = parent_doc.create_material_request_after_change_size(target.recipe_name, [target])
    _cleanup_redundant_wips(new_cycle_wos, target, child_doctype, start_time)

    new_cook = get_wo_by_type(target.link_id, "Cook")
    if new_cook:
        _relink_quality_docs(quality_data, new_cook)