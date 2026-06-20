# Copyright (c) 2025, hisham and contributors
# wo_helpers.py — ID-Driven Helpers (Database-First)

import frappe
from frappe import _

# ══════════════════════════════════════════════════════════════════════════════
#  Database Lookups (The Source of Truth)
# ══════════════════════════════════════════════════════════════════════════════

def get_active_wos_by_link_id(link_id: str, _cache=None) -> list:
    """
    Queries the database directly for all active Work Orders carrying this link_id.
    'Active' means not cancelled (docstatus < 2).
    Results are cached per request via frappe.flags to avoid redundant queries
    when the same link_id is queried multiple times (e.g. for Pack + Cook WO lookups).
    """
    if not link_id:
        return []
    
    # Request-local cache using frappe.flags
    cache = frappe.flags.get("_wo_by_link_id_cache")
    if cache is None:
        cache = {}
        frappe.flags["_wo_by_link_id_cache"] = cache
    
    if link_id in cache:
        return cache[link_id]
    
    result = frappe.get_all(
        "Work Order",
        filters={
            "custom_link_id": link_id,
            "docstatus": ["<", 2] 
        },
        fields=["name", "custom_item_type", "status", "production_item", "docstatus", "creation","modified","custom_link_id"]
    )
    
    cache[link_id] = result
    return result


def get_wo_by_type(link_id: str, item_type: str) -> str | None:
    """Finds the first Work Order name matching the type (e.g. 'Cook') for this ID."""
    wos = get_active_wos_by_link_id(link_id)
    for wo in wos:
        if wo.custom_item_type == item_type:
            return wo.name
    return None


def get_pack_wo_for_item(link_id: str, pack_name: str) -> str | None:
    """Finds a specific Pack WO for an item using the ID badge."""
    wos = get_active_wos_by_link_id(link_id)
    for wo in wos:
        if wo.custom_item_type == "Pack":
            return wo.name
    return None
    
def get_all_pack_wos_by_link_id(link_id: str) -> list:
    """Returns a list of ALL Pack WO names for this ID badge."""
    wos = get_active_wos_by_link_id(link_id)
    pack_wo_list = []
    
    for wo in wos:
        if wo.custom_item_type == "Pack":
            pack_wo_list.append(wo.name)
            
    return pack_wo_list


# ══════════════════════════════════════════════════════════════════════════════
#  Grid Navigation (Handling Continuation Rows)
# ══════════════════════════════════════════════════════════════════════════════

def get_active_link_id_from_row(row, child_doctype: str) -> str | None:
    """
    If a row is a continuation (no link_id), walk up to find the nearest 
    parent recipe row and return its link_id.
    """
    if row.get("link_id"):
        return row.get("link_id")

    # Walk up the table grid index
    parent_link_id = frappe.db.get_value(
        child_doctype,
        {
            "parent": row.parent,
            "idx": ["<", row.idx],
            "link_id": ["!=", ""],
        },
        "link_id",
        order_by="idx desc",
    )
    return parent_link_id


def get_recipe_note_from_parent_row(row, child_doctype: str) -> str:
    """
    If this row has no recipe_note, walk up to find the nearest
    recipe row above it that has one.
    """
    recipe_note = row.get("recipe_note")
    if recipe_note:
        return recipe_note

    return frappe.db.get_value(
        child_doctype,
        {
            "parent": row.parent,
            "idx": ["<", row.idx],
            "recipe_note": ["!=", ""],
        },
        "recipe_note",
        order_by="idx desc",
    ) or ""


# ══════════════════════════════════════════════════════════════════════════════
#  Validators & Updaters
# ══════════════════════════════════════════════════════════════════════════════

def validate_wo_for_change(wo_name: str) -> None:
    """Standard validation: Ensure WO exists and is in an editable state."""
    if not frappe.db.exists("Work Order", wo_name):
        return

    wo = frappe.db.get_value("Work Order", wo_name, ["status", "docstatus"], as_dict=True)

    if wo.docstatus == 2:
        frappe.throw(_("Work Order {0} is cancelled and cannot be modified.").format(wo_name))

    if wo.status in ("Completed", "Stopped"):
        frappe.throw(_("Work Order {0} is {1} and cannot be modified.").format(wo_name, wo.status))


def update_wo_operations_workstation(wo_name: str, new_workstation: str) -> None:
    """Updates the workstation field inside the Operations table of a Work Order."""
    operations = frappe.get_all(
        "Work Order Operation",
        filters={
            "parent": wo_name,
            "workstation_type": ["in", ["Packing", "Cooker", "Kettle", "Fryer"]],
        },
        fields=["name"],
    )
    for op in operations:
        frappe.db.set_value("Work Order Operation", op.name, "workstation", new_workstation)


def update_wo_field(wo_name: str, field: str, value) -> None:
    """Performs a direct database update on a Work Order header field."""
    frappe.db.set_value("Work Order", wo_name, field, value)


def get_cook_quality_data_by_wo(wo_name: str) -> list:
    """
    Returns Quality Reviews and Weight Records for a specific WO.
    Used for migration during Rearrange or Recipe Change.
    """
    if not wo_name: return []
    
    qrs = [{"name": d.name, "doctype": "Quality Review"} 
           for d in frappe.get_all("Quality Review", filters={"custom_work_order": wo_name})]
    
    wrs = [{"name": d.name, "doctype": "Weight Record"} 
           for d in frappe.get_all("Weight Record", filters={"custom_work_order": wo_name})]
    
    return qrs + wrs


def remove_all_wip_wo(link_id,work=False):
    """Delete all draft WIP Work Orders for a link_id. Used during Reheat to clear stale WIPs."""
    if work == False:
        return
    wos = get_active_wos_by_link_id(link_id)

    for wo in wos:
        if wo.get("custom_item_type") != "WIP":
            continue

        wo_doc = frappe.get_doc("Work Order", wo.get("name"))

        if wo_doc.docstatus == 1:
            frappe.throw(f"Error Link ID {link_id} has finished WIP so cannot be Reheat")

        wo_doc.delete()

