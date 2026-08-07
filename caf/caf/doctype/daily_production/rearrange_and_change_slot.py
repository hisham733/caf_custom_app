# Copyright (c) 2025, hisham and contributors
# rearrange_and_change_slot.py — ID-Driven Production Handover & Migration

import time
from collections import defaultdict
import frappe
from frappe import _
from frappe.utils import now_datetime
# FIXED: Added get_active_wos_by_link_id to imports
from .wo_helpers import get_active_link_id_from_row, get_wo_by_type, get_active_wos_by_link_id
from .cancellation import _bulk_clean_stock_and_jobs, _cancel_stock_entries_for_wo, _cancel_job_cards_for_wo, _cancel_work_orders_by_id, cancel_wos_by_link_id, cleanup_wos_by_type

STATUS_CHANGE_SLOT = "Change Slot"
STATUS_SWITCH       = "Rearrange"
NO_COOKING          = "No Cooking"
WO_DOCTYPE          = "Work Order"

# ══════════════════════════════════════════════════════════════════════════════
#  Internal ID-Based Logic
# ══════════════════════════════════════════════════════════════════════════════

def _swap_db_link_ids(id_a: str, id_b: str) -> None:
    """Swap custom_link_id between two rows using a temp ID."""
    cnt_a = frappe.db.count("Work Order", {"custom_link_id": id_a})
    cnt_b = frappe.db.count("Work Order", {"custom_link_id": id_b})

    temp_id = f"TEMP-{frappe.generate_hash(length=8)}"

    for attempt in range(3):
        try:
            frappe.db.sql("UPDATE `tabWork Order` SET custom_link_id = %s WHERE custom_link_id = %s", (temp_id, id_a))
            frappe.db.sql("UPDATE `tabWork Order` SET custom_link_id = %s WHERE custom_link_id = %s", (id_a, id_b))
            frappe.db.sql("UPDATE `tabWork Order` SET custom_link_id = %s WHERE custom_link_id = %s", (id_b, temp_id))
            break
        except frappe.QueryDeadlockError:
            if attempt == 2:
                raise
            time.sleep(0.5)
    
    # ─ SWAP STOCK ENTRIES
    se_cnt_a = frappe.db.count("Stock Entry", {"custom_link_id": id_a})
    se_cnt_b = frappe.db.count("Stock Entry", {"custom_link_id": id_b})

    if se_cnt_a > 0 or se_cnt_b > 0:
        for attempt in range(3):
            try:
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
                break
            except frappe.QueryDeadlockError:
                if attempt == 2:
                    raise
                time.sleep(0.5)
    else:
        print(f"   ⚠️  No Stock Entries found with custom_link_id")

def _migrate_db_link_ids(source_id: str, target_id: str) -> None:
    """Migrate custom_link_id from source row to target slot.

    One-way move (not a swap). Used for Change Slot where a recipe
    moves into an empty slot. Reassigns Work Orders and Stock Entries
    from source link_id to target link_id.
    """
    for attempt in range(3):
        try:
            frappe.db.sql(
                "UPDATE `tabWork Order` SET custom_link_id = %s WHERE custom_link_id = %s",
                (target_id, source_id)
            )
            frappe.db.sql(
                "UPDATE `tabStock Entry` SET custom_link_id = %s WHERE custom_link_id = %s",
                (target_id, source_id)
            )
            return
        except frappe.QueryDeadlockError:
            if attempt == 2:
                raise
            time.sleep(0.5)


def _cancel_cook_pack_by_id(link_id: str) -> None:
    """Cancel all active Cook and Pack WOs for a given link_id."""
    cancel_wos_by_link_id(link_id, types=["Cook", "Pack"])

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
    """Removes only WIP Work Orders created in the current transaction."""
    cleanup_wos_by_type(newly_created_wos, keep_types=["Cook", "Pack"], child_doctype=child_doctype, start_time=start_time)
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
    """Return user-editable field names from the child doctype, excluding fixed/system fields.

    Mirrors the JS `get_moveable_fields` + `SWAP_EXTRA_FIELDS` set: `mr_reference` and
    `production_plane` travel with the recipe, while `link_id`/slot identity stays fixed.
    """
    meta = frappe.get_meta(child_doctype)
    fixed = {
        "recipe_cook_workstaion", "recipe_cook_round", "link_id",
        "rq_status", "custom_yield", "total_input", "total_output",
        "custom_pair_id", "idx", "name", "produ_status", "parent",
    }
    return [
        f.fieldname for f in meta.fields
        if f.fieldname not in fixed
        and f.fieldtype not in {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Fold"}
    ]

# ══════════════════════════════════════════════════════════════════════════════
#  Pair Grouping Helper
# ══════════════════════════════════════════════════════════════════════════════

def _group_rows_by_pair(rows: list, status_label: str, child_doctype: str) -> list:
    """
    Groups rows by custom_pair_id. Each group must have exactly 2 rows.
    Falls back to sequential pairing (2 at a time by idx) if no pair_id is set.
    Orphaned single rows (partner already cleared) are cleaned up automatically.
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

    valid_pairs = []
    for pid, group in groups.items():
        if len(group) == 2:
            valid_pairs.append(group)
        elif len(group) == 1:
            frappe.db.set_value(child_doctype, group[0].name, "produ_status", "")
            frappe.db.set_value(child_doctype, group[0].name, "custom_pair_id", "")

    return valid_pairs


# ══════════════════════════════════════════════════════════════════════════════
#  Main Entry Points
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def process_switch(dp_doc, child_doctype: str) -> None:
    """Entry point for Rearrange: swap link_ids between paired rows, cancel/recreate WOs.

    Phase 3: Accepts DailyProduction doc object directly — no reload.
    """
    doc_name = dp_doc.name
    start_time = now_datetime()
    rows = frappe.get_all(
        child_doctype,
        filters={"parent": doc_name, "produ_status": STATUS_SWITCH, "rq_status": ["!=", "Done"]},
        fields=["name", "recipe_name", "link_id", "idx", "custom_pair_id"],
        order_by="idx asc"
    )
    if not rows:
        return []

    pairs = _group_rows_by_pair(rows, "Rearrange", child_doctype)

    for pair in pairs:
        _process_one_switch_pair(pair, dp_doc, child_doctype, start_time)

    paired_names = {r.name for pair in pairs for r in pair}

    for row in rows:
        frappe.db.set_value(child_doctype, row.name, "produ_status", "")
        frappe.db.set_value(child_doctype, row.name, "custom_pair_id", "")
        if row.name in paired_names:
            frappe.db.set_value(child_doctype, row.name, "rq_status", "Done")

    # No internal commit here — the caller (process_manual_updates) owns the
    # transaction boundary so a failure rolls back the whole slot swap atomically.
    frappe.msgprint(_("✅ Rearrange Complete. {0} pair(s) processed.").format(len(pairs)))
    return list(paired_names)


def _process_one_switch_pair(pair: list, parent_doc, child_doctype: str, start_time) -> None:
    """Process a single Rearrange pair (swap link_ids, cancel, recreate, relink)."""
    row_a = next((d for d in parent_doc.production_table if d.name == pair[0].name), None)
    row_b = next((d for d in parent_doc.production_table if d.name == pair[1].name), None)
    if not row_a or not row_b:
        return

    qual_a = _get_quality_data_by_id(row_a.link_id)
    qual_b = _get_quality_data_by_id(row_b.link_id)
    _swap_db_link_ids(row_a.link_id, row_b.link_id)

    _cancel_cook_pack_by_id(row_a.link_id)
    _cancel_cook_pack_by_id(row_b.link_id)

    for r in (row_a, row_b):
        r.reload()
        full_group = parent_doc.get_full_group_for_row(r)
        new_cycle_wos = parent_doc.recreate_mr_after_update_slot(r.recipe_name, full_group)
        _cleanup_redundant_wips(new_cycle_wos, r, child_doctype, start_time)

    for r, q_data in [(row_a, qual_b), (row_b, qual_a)]:
        new_cook = get_wo_by_type(r.link_id, "Cook")
        if new_cook:
            _relink_quality_docs(q_data, new_cook)


@frappe.whitelist()
def process_slot_swaps(dp_doc, child_doctype: str) -> None:
    """Entry point for Change Slot: migrate link_id from a source row into an empty target slot.

    Phase 3: Accepts DailyProduction doc object directly — no reload.
    """
    doc_name = dp_doc.name
    start_time = now_datetime()
    rows = frappe.get_all(
        child_doctype,
        filters={"parent": doc_name, "produ_status": STATUS_CHANGE_SLOT, "rq_status": ["!=", "Done"]},
        fields=["name", "recipe_name", "link_id", "idx", "custom_pair_id"],
        order_by="idx asc"
    )

    if not rows:
        return []

    pairs = _group_rows_by_pair(rows, "Change Slot", child_doctype)

    for pair in pairs:
        _process_one_slot_swap_pair(pair, dp_doc, child_doctype, start_time)

    # Recipe-bearing target rows keep the "Change Slot" marker (source goes blank).
    target_names = [
        r.name for pair in pairs
        for r in pair
        if r.recipe_name and r.recipe_name != NO_COOKING
    ]

    for row in rows:
        frappe.db.set_value(child_doctype, row.name, "produ_status", "")
        frappe.db.set_value(child_doctype, row.name, "custom_pair_id", "")
        frappe.db.set_value(child_doctype, row.name, "rq_status", "Done")

    # No internal commit here — the caller (process_manual_updates) owns the
    # transaction boundary so a failure rolls back the whole slot swap atomically.
    frappe.msgprint(_("✅ Slot swap complete. {0} pair(s) processed.").format(len(pairs)))
    return target_names


def _process_one_slot_swap_pair(pair: list, parent_doc, child_doctype: str, start_time) -> None:
    """Process a single Change Slot pair (migrate link_id, cancel, recreate, relink)."""
    row_1 = next((d for d in parent_doc.production_table if d.name == pair[0].name), None)
    row_2 = next((d for d in parent_doc.production_table if d.name == pair[1].name), None)
    if not row_1 or not row_2:
        return

    if row_1.recipe_name != NO_COOKING:
        target, source = row_1, row_2
    else:
        target, source = row_2, row_1

    quality_data = _get_quality_data_by_id(source.link_id)

    _migrate_db_link_ids(source_id=source.link_id, target_id=target.link_id)
    _cancel_cook_pack_by_id(target.link_id)

    target.reload()
    new_cycle_wos = parent_doc.recreate_mr_after_update_slot(target.recipe_name, [target])
    _cleanup_redundant_wips(new_cycle_wos, target, child_doctype, start_time)

    new_cook = get_wo_by_type(target.link_id, "Cook")
    if new_cook:
        _relink_quality_docs(quality_data, new_cook)


# ══════════════════════════════════════════════════════════════════════════════
#  DP-Form-Only Atomic Change Slot
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def process_slot_swap_atomic(dp_name: str, source_row: str, target_row: str) -> dict:
    """DP-form-only atomic Change Slot.

    Performs the field swap AND the WO migration (link_id migrate, Cook/Pack cancel,
    MR/WO recreate, quality relink) inside ONE transaction. The DP form calls this
    directly instead of pre-swapping + frm.save() + process_manual_updates, so on any
    failure the whole transaction rolls back and the rows return to their original
    slots. Does NOT touch the WPD drag-drop path.

    Args:
        dp_name: Daily Production name
        source_row: Child row name that currently holds the recipe
        target_row: Child row name of the empty/No Cooking target slot

    Returns:
        Dict with success status
    """
    try:
        dp = frappe.get_doc("Daily Production", dp_name)
        rows_by_name = {r.name: r for r in dp.production_table}
        src = rows_by_name.get(source_row)
        tgt = rows_by_name.get(target_row)
        if not src or not tgt:
            return {"success": False, "message": _("Row not found")}

        # Normalize: src = the row holding the recipe, tgt = the empty slot.
        if src.recipe_name == NO_COOKING and tgt.recipe_name != NO_COOKING:
            src, tgt = tgt, src
        if src.recipe_name == NO_COOKING:
            return {"success": False, "message": _("Source row has no recipe to move.")}

        # Guard: Cook WO must not be Completed
        cook_status = frappe.db.get_value(
            "Work Order",
            {"custom_link_id": src.link_id, "custom_item_type": "Cook", "docstatus": ["<", 2]},
            "status",
        )
        if cook_status == "Completed":
            return {"success": False, "message": _("Cook Work Order is already Completed. Cannot change slot.")}

        # ── 1. Swap moveable fields server-side (link_id / slot identity stays fixed) ──
        for fn in _get_movable_fields(src.doctype):
            s_val = src.get(fn)
            t_val = tgt.get(fn)
            frappe.db.set_value(src.doctype, src.name, fn, t_val)
            frappe.db.set_value(src.doctype, tgt.name, fn, s_val)
            setattr(src, fn, t_val)
            setattr(tgt, fn, s_val)

        # ── 2. Migrate WOs to the new slot and recreate the MR/WO chain ──
        start_time = now_datetime()
        quality_data = _get_quality_data_by_id(src.link_id)

        _migrate_db_link_ids(source_id=src.link_id, target_id=tgt.link_id)
        _cancel_cook_pack_by_id(tgt.link_id)

        tgt.reload()
        new_cycle_wos = dp.recreate_mr_after_update_slot(tgt.recipe_name, [tgt])
        _cleanup_redundant_wips(new_cycle_wos, tgt, src.doctype, start_time)

        new_cook = get_wo_by_type(tgt.link_id, "Cook")
        if new_cook:
            _relink_quality_docs(quality_data, new_cook)

        # ── 3. Clear markers, mark Done, single commit ──
        for row in (src, tgt):
            frappe.db.set_value(row.doctype, row.name, "produ_status", "")
            frappe.db.set_value(row.doctype, row.name, "custom_pair_id", "")
            frappe.db.set_value(row.doctype, row.name, "rq_status", "Done")

        frappe.db.commit()
        return {"success": True, "message": _("Slot changed successfully")}
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), _("Atomic Slot Swap Failed"))
        raise


# ══════════════════════════════════════════════════════════════════════════════
#  DP-Form-Only Atomic Rearrange
# ══════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def process_rearrange_atomic(dp_name: str, row_a_name: str, row_b_name: str) -> dict:
    """DP-form-only atomic Rearrange.

    Swaps the two rows' recipe data AND migrates the WOs (link_id swap, Cook/Pack
    cancel, MR/WO recreate, quality relink) inside ONE transaction. The DP form calls
    this directly instead of pre-swapping + frm.save() + process_manual_updates, so on
    any failure the whole transaction rolls back and the rows return to their original
    slots. Does NOT touch the WPD drag-drop path.

    Args:
        dp_name: Daily Production name
        row_a_name: Child row name of the first recipe slot
        row_b_name: Child row name of the second recipe slot

    Returns:
        Dict with success status
    """
    try:
        dp = frappe.get_doc("Daily Production", dp_name)
        rows_by_name = {r.name: r for r in dp.production_table}
        row_a = rows_by_name.get(row_a_name)
        row_b = rows_by_name.get(row_b_name)
        if not row_a or not row_b:
            return {"success": False, "message": _("Row not found")}
        if row_a.recipe_name == NO_COOKING or row_b.recipe_name == NO_COOKING:
            return {"success": False, "message": _("Both slots must hold a recipe to rearrange.")}

        # Guard: neither Cook WO must be Completed
        for r, label in ((row_a, "first"), (row_b, "second")):
            cook_status = frappe.db.get_value(
                "Work Order",
                {"custom_link_id": r.link_id, "custom_item_type": "Cook", "docstatus": ["<", 2]},
                "status",
            )
            if cook_status == "Completed":
                return {"success": False, "message": _("Cook Work Order is already Completed for the {0} recipe. Cannot rearrange.").format(label)}

        # ── 1. Swap moveable fields server-side (link_id / slot identity stays fixed) ──
        for fn in _get_movable_fields(row_a.doctype):
            a_val = row_a.get(fn)
            b_val = row_b.get(fn)
            frappe.db.set_value(row_a.doctype, row_a.name, fn, b_val)
            frappe.db.set_value(row_a.doctype, row_b.name, fn, a_val)
            setattr(row_a, fn, b_val)
            setattr(row_b, fn, a_val)

        # ── 2. Swap WOs, cancel Cook/Pack, recreate, relink ──
        start_time = now_datetime()
        qual_a = _get_quality_data_by_id(row_a.link_id)
        qual_b = _get_quality_data_by_id(row_b.link_id)

        _swap_db_link_ids(row_a.link_id, row_b.link_id)
        _cancel_cook_pack_by_id(row_a.link_id)
        _cancel_cook_pack_by_id(row_b.link_id)

        for r in (row_a, row_b):
            r.reload()
            full_group = dp.get_full_group_for_row(r)
            new_cycle_wos = dp.recreate_mr_after_update_slot(r.recipe_name, full_group)
            _cleanup_redundant_wips(new_cycle_wos, r, row_a.doctype, start_time)

        for r, q_data in [(row_a, qual_b), (row_b, qual_a)]:
            new_cook = get_wo_by_type(r.link_id, "Cook")
            if new_cook:
                _relink_quality_docs(q_data, new_cook)

        # ── 3. Clear markers, mark Done, single commit ──
        for r in (row_a, row_b):
            frappe.db.set_value(r.doctype, r.name, "produ_status", "")
            frappe.db.set_value(r.doctype, r.name, "custom_pair_id", "")
            frappe.db.set_value(r.doctype, r.name, "rq_status", "Done")

        frappe.db.commit()
        return {"success": True, "message": _("Rearrange completed successfully")}
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), _("Atomic Rearrange Failed"))
        raise
