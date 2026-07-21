# Copyright (c) 2025, hisham and contributors
# work_order_cancellation.py — Hierarchical Cancellation Engine

import pdb

import frappe
from frappe import _
from .wo_helpers import get_active_wos_by_link_id
# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 1: BULK CLEANUP (The "Glue")
# ══════════════════════════════════════════════════════════════════════════════

def _bulk_clean_stock_and_jobs(wos: list) -> None:
    """
    Improved Sorting: 
    Sorts by actual BOM hierarchy - parents first, deep children last.
    OPTIMIZED: Batch queries, memoization, O(1) lookups.
    """
    
    wo_list = []
    for wo in wos:
        if isinstance(wo, str):
            wo_list.append(frappe.get_doc("Work Order", wo))
        else:
            wo_list.append(wo)
    
    wo_map = {w.name: w for w in wo_list}
    
    # Extract production items
    prod_items = set()
    for wo in wo_list:
        item = wo.production_item if hasattr(wo, 'production_item') else wo.get('production_item')
        if item:
            prod_items.add(item)
    
    # BATCH QUERY: Get all parent BOMs in ONE query
    print("🔗 Building BOM cache...")
    all_bom_items = frappe.get_all(
        "BOM Item",
        filters={"item_code": ["in", list(prod_items)]},
        fields=["item_code", "parent"],
        limit_page_length=None
    )
    
    all_parent_boms = {}
    for bom_row in all_bom_items:
        all_parent_boms.setdefault(bom_row["item_code"], []).append(bom_row["parent"])
    
    # BATCH QUERY: Get all parent items at once
    unique_boms = set()
    for bom_list in all_parent_boms.values():
        unique_boms.update(bom_list)
    
    bom_data = frappe.get_all("BOM", filters={"name": ["in", list(unique_boms)]}, fields=["name", "item"])
    bom_to_parent_item = {b["name"]: b["item"] for b in bom_data}
    
    # CREATE REVERSE LOOKUP: prod_item → WO (O(1) lookup)
    prod_item_to_wo = {}
    for wo in wo_list:
        item = wo.production_item if hasattr(wo, 'production_item') else wo.get('production_item')
        if item:
            prod_item_to_wo[item] = wo
    
    depth_cache = {}
    
    def get_bom_hierarchy_depth(wo_name, visited=None):
        if visited is None:
            visited = set()
        
        if wo_name in visited:
            return 0
        
        visited.add(wo_name)
        
        wo = wo_map.get(wo_name)
        if not wo:
            return 0
        
        prod_item = wo.production_item if hasattr(wo, 'production_item') else wo.get('production_item')
        if not prod_item:
            return 0
        
        parent_boms = all_parent_boms.get(prod_item, [])
        
        max_parent_depth = 0
        for parent_bom in parent_boms:
            parent_item = bom_to_parent_item.get(parent_bom)
            if not parent_item:
                continue
            
            # O(1) lookup instead of O(N) loop
            parent_wo = prod_item_to_wo.get(parent_item)
            if parent_wo:
                parent_depth = 1 + get_bom_hierarchy_depth(parent_wo.name, visited.copy())
                max_parent_depth = max(max_parent_depth, parent_depth)
        
        return max_parent_depth
    
    wo_depths = {}
    print("\n🔍 Calculating BOM depths...")
    for wo in wo_list:
        wo_depths[wo.name] = get_bom_hierarchy_depth(wo.name)
    
    print("   Done!")
    
    sorted_wos = sorted(wo_list, key=lambda x: (
        wo_depths[x.name],
        x.get("custom_item_type") != "Pack" if hasattr(x, 'get') else getattr(x, 'custom_item_type', '') != "Pack",
        x.get("idx", 0) if hasattr(x, 'get') else getattr(x, 'idx', 0)
    ))
    print(f"\n📋 Cancellation order {sorted_wos}:")
    for wo in sorted_wos:
        _cancel_stock_entries_for_wo(wo.name)
        _cancel_job_cards_for_wo(wo.name)

def _cancel_stock_entries_for_wo(wo_name) -> None:
    # ✅ normalize
    wo_name = wo_name.name if hasattr(wo_name, "name") else wo_name

    print(f"\n🧹 Cleaning Stock Entries for WO {wo_name}...")

    entries = frappe.get_all(
        "Stock Entry",
        filters={"work_order": wo_name, "docstatus": ["in", [0, 1]]},
        fields=["name", "stock_entry_type", "docstatus"]
    )

    print("FOUND ENTRIES:", entries)

    # ✅ Manufacture first
    sorted_entries = sorted(
        entries,
        key=lambda x: x["stock_entry_type"] != "Manufacture"
    )

    for se in sorted_entries:
        print(f"Processing {se['name']} ({se['stock_entry_type']})")
        _process_single_se(se)

def _process_single_se(se_row):
    try:
        se_name = se_row["name"] if isinstance(se_row, dict) else se_row.name

        se_doc = frappe.get_doc("Stock Entry", se_name)
        se_doc.flags.ignore_permissions = True

        if se_doc.docstatus == 0:
            print(f"Deleting Draft SE: {se_name}")
            se_doc.delete()
        elif se_doc.docstatus == 1:
            print(f"Cancelling Submitted SE: {se_name}")
            se_doc.cancel()

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Failed SE {se_row}"
        )
        frappe.throw(
            _("Could not process Stock Entry {0}. It may be linked or locked.")
            .format(se_name)
        )

def _cancel_job_cards_for_wo(wo_name) -> None:
    # ✅ normalize
    wo_name = wo_name.name if hasattr(wo_name, "name") else wo_name

    print(f"\n🧹 Cleaning Job Cards for WO {wo_name}...")

    jcs = frappe.get_all(
        "Job Card",
        filters={"work_order": wo_name, "docstatus": ["in", [0, 1]]},
        fields=["name", "docstatus"]
    )

    print("FOUND JOB CARDS:", jcs)

    for jc in jcs:
        jc_name = jc["name"]

        jc_doc = frappe.get_doc("Job Card", jc_name)
        jc_doc.flags.ignore_permissions = True

        if jc_doc.docstatus == 1:
            print(f"Cancelling JC: {jc_name}")
            jc_doc.cancel()
        else:
            print(f"Deleting JC: {jc_name}")
            jc_doc.delete()
# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2: WORK ORDER CANCELLATION (The "Kill")
# ══════════════════════════════════════════════════════════════════════════════

def _cancel_work_orders_by_id(link_id: str) -> None:
    if not link_id: return
    # pdb.set_trace()
    wos = get_active_wos_by_link_id(link_id)

    # 1. Validation (Check if any part of the chain is already finished)
    for wo in wos:
        if wo.custom_item_type == "Cook" and wo.status == "Completed":
            frappe.throw(_("🛑 Aborted: Cook WO {0} is Completed. Cannot cancel chain.").format(wo.name))

    # 2. CLEAR ALL STOCK ENTRIES FIRST (For all WOs in group)
    # This is what prevents your Onion vs IB error.
    _bulk_clean_stock_and_jobs(wos)

    # 3. CANCEL WORK ORDERS (Parent → Children via BOM Structure)
    wo_map = {w.name: w for w in wos}
    
    # Build BOM to parent item mapping
    bom_to_parent_item_phase3 = {}
    prod_items_phase3 = [w.production_item if hasattr(w, 'production_item') else w.get('production_item') for w in wos]
    
    all_parent_boms_phase3 = {}
    for item in prod_items_phase3:
        bom_items = frappe.get_all(
            "BOM Item",
            filters={"item_code": item},
            fields=["parent"],
            limit_page_length=None
        )
        all_parent_boms_phase3[item] = [b['parent'] for b in bom_items]
        for bom_name in [b['parent'] for b in bom_items]:
            if bom_name not in bom_to_parent_item_phase3:
                try:
                    bom_doc = frappe.get_doc("BOM", bom_name)
                    bom_to_parent_item_phase3[bom_name] = bom_doc.item
                except:
                    pass
    
    def get_bom_depth_cancel(wo_name, visited=None):
        """Calculate depth based on BOM structure"""
        if visited is None:
            visited = set()
        
        if wo_name in visited:
            return 0
        visited.add(wo_name)
        
        wo = wo_map.get(wo_name)
        if not wo:
            return 0
        
        # Get produced item
        prod_item = wo.production_item if hasattr(wo, 'production_item') else wo.get('production_item')
        if not prod_item:
            return 0
        
        # Get parent BOMs for this item
        parent_boms = all_parent_boms_phase3.get(prod_item, [])
        
        max_parent_depth = 0
        for parent_bom in parent_boms:
            # Get what ITEM this BOM is for
            parent_item = bom_to_parent_item_phase3.get(parent_bom)
            if not parent_item:
                continue
            
            # Find which WO in our group produces this parent_item
            for other_wo in wos:
                if other_wo.name == wo_name:
                    continue
                
                other_prod_item = other_wo.production_item if hasattr(other_wo, 'production_item') else other_wo.get('production_item')
                if other_prod_item != parent_item:
                    continue
                
                parent_depth = 1 + get_bom_depth_cancel(other_wo.name, visited.copy())
                max_parent_depth = max(max_parent_depth, parent_depth)
        
        return max_parent_depth
    
    # Calculate and sort by BOM depth
    wos_with_depth = []
    print("\n📋 Calculating cancellation order...")
    for w in wos:
        depth = get_bom_depth_cancel(w.name)
        wos_with_depth.append((w, depth))
    
    wos_with_depth.sort(key=lambda x: (
        x[1],  # Shallower/parents first
        x[0].get("custom_item_type") != "Pack" if hasattr(x[0], 'get') else getattr(x[0], 'custom_item_type', '') != "Pack",
        x[0].get("idx", 0) if hasattr(x[0], 'get') else getattr(x[0], 'idx', 0)
    ))
    
    # print(f"✓ Cancel Order (by BOM depth):")
    for idx, (w, d) in enumerate(wos_with_depth, 1):
        prod_item = w.production_item if hasattr(w, 'production_item') else w.get('production_item')
        # print(f"   {idx}. {w.name} ({prod_item}) - depth {d}")
    
    for wo_row, depth in wos_with_depth:
        if not frappe.db.exists("Work Order", wo_row.name): continue
        wo = frappe.get_doc("Work Order", wo_row.name)
        
        if wo.docstatus == 2: continue
        
        wo.flags.ignore_permissions = True
        wo.flags.ignore_workflow = True
        
        if wo.docstatus == 0:
            wo.delete()
        else:
            wo.cancel()

# ══════════════════════════════════════════════════════════════════════════════
#  UI & RECORD CLEANUP
# ══════════════════════════════════════════════════════════════════════════════

def _cancel_production_plan(pp_name: str) -> None:
    if not pp_name or not frappe.db.exists("Production Plan", pp_name): return
    pp = frappe.get_doc("Production Plan", pp_name)
    if pp.docstatus == 2: return
    pp.flags.ignore_permissions = True
    if pp.docstatus == 1: pp.cancel()
    else: pp.delete()

def _clear_mr_link_id(mr_name: str) -> None:
    if not mr_name or not frappe.db.exists("Material Request", mr_name): return
    frappe.db.set_value("Material Request", mr_name, {"custom_link_id": "", "custom_daily_production_id": ""})

def _process_cancel_row(row_name: str, child_doctype: str) -> None:
    row = frappe.get_doc(child_doctype, row_name)
    
    # Run the 2-Phase Cancellation
    _cancel_work_orders_by_id(row.link_id)

    if row.production_plane: _cancel_production_plan(row.production_plane)
    if row.mr_reference: _clear_mr_link_id(row.mr_reference)

    frappe.db.set_value(child_doctype, row_name, {
        "wo_list": "", "production_plane": "", "mr_reference": "",
        "produ_status": "Cancelled", "wo_list_with_type": ""
    })

@frappe.whitelist()
def process_cancellations(doc_name: str, doctype: str, child_doctype: str) -> None:
    cancel_rows = frappe.get_all(child_doctype, filters={"parent": doc_name, "produ_status": "Cancelled"}, fields=["name"])
    if not cancel_rows: return
    for row in cancel_rows:
        _process_cancel_row(row.name, child_doctype)

