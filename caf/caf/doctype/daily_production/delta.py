
import json
from frappe import _
import frappe
from frappe.utils import nowdate
from caf.caf.overrides.production_plan import CustomProductionPlan, get_items_for_material_requests
import pdb
import math
CHILD_TABLE = "custom_max_table"

def transfer_materials_for_pp_doc(pp):
    """Server-side version of Transfer Materials button logic"""
    
    # 1. Mandatory check for Manufacturing Settings warehouse
    mat_warehouse = frappe.db.get_single_value("Manufacturing Settings", "material_warehouse")
    
    if not mat_warehouse:
        frappe.throw(_("Please set Material Warehouse in Manufacturing Settings before creating a Production Plan."))

    # 2. Use frappe._dict to handle object/dict compatibility for the override
    pp_dict = frappe._dict(pp.as_dict())
    
    # Ensure child tables are correctly initialized for the override
    pp_dict["po_items"] = [d.as_dict() for d in pp.po_items]
    pp_dict["sub_assembly_items"] = [d.as_dict() for d in pp.sub_assembly_items]
    pp_dict["material_requests"] = [d.as_dict() for d in pp.material_requests]
    pp_dict["mr_items"] = [] 

    # 3. Format warehouse for the override (expects a JSON string)
    warehouses_json = json.dumps([{"warehouse": mat_warehouse}])

    # 4. Call the override and capture the result
    result = get_items_for_material_requests(pp_dict, warehouses=warehouses_json)

    # 5. Extract calculated raw materials from either the return value or the dict
    raw_materials = []
    if isinstance(result, list):
        raw_materials = result
    elif isinstance(result, dict) and result.get("mr_items"):
        raw_materials = result.get("mr_items")
    elif pp_dict.get("mr_items"):
        raw_materials = pp_dict.get("mr_items")

    # 6. Sync back to the actual Document Object
    if raw_materials:
        pp.set("mr_items", []) 
        for item in raw_materials:
            pp.append("mr_items", item)




def get_already_transferred_today(item_code, dp_date_prefix):
    """
    Finds the total quantity of an item already transferred in 
    Stock Entries linked to Daily Productions from the same day.
    """
    # Sum qty from submitted Stock Entries where custom_daily_production_id matches the date prefix
    qty = frappe.db.sql("""
        SELECT SUM(sed.qty)
        FROM `tabStock Entry Detail` sed
        INNER JOIN `tabStock Entry` se ON sed.parent = se.name
        WHERE se.docstatus = 1 
        AND se.stock_entry_type = 'Material Transfer'
        AND se.custom_daily_production_name LIKE %s
        AND sed.item_code = %s
    """, (f"{dp_date_prefix}%", item_code))
    
    return qty[0][0] or 0.0


def create_stock_entry_direct_from_pp(pp, items_in_table=None):
    """
    Creates a Stock Entry from items_in_table for initial population.
    If items_in_table is None, uses pp.mr_items.
    """
    if items_in_table is None:
        items_in_table = {}
    
    if not items_in_table and not pp.mr_items:
        return None

    dp_name = pp.custom_daily_production_id
    if not dp_name:
        frappe.throw(_("Production Plan is not linked to a Daily Production ID."))

    default_source_wh = frappe.db.get_single_value("Manufacturing Settings", "material_warehouse")

    # --- Initialize the Stock Entry ---
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.company = pp.company
    se.posting_date = nowdate()
    se.custom_daily_production_name = dp_name
    se.production_plan = pp.name

    # --- Add items to SE ---
    added_any_item = False

    for item in items_in_table.values():
        added_any_item = True
        se.append("items", {
            "item_code": item.get("item_code"),
            "qty": item.get("p_qty"),
            "uom": item.get("purchase_uom"),
            "stock_uom": item.get("uom"),
            "s_warehouse": item.get("s_warehouse") or default_source_wh,
            "t_warehouse": item.get("t_warehouse"),
        })

    # --- Save or Handle empty SE ---
    if not added_any_item:
        frappe.msgprint(_("No items to transfer."))
        return None

    se.flags.ignore_permissions = True
    se.insert()
    
    return se.name
# from erpnext.stock.doctype.stock_entry.stock_entry import make_stock_entry

def old_create_stock_entry_direct_from_pp(pp):
    """
    Creates a Stock Entry from mr_items.
    Validates that NO items are marked for Purchase (meaning out of stock).
    """
    if not pp.mr_items:
        return None

    # --- 1. VALIDATION: Check for Purchase Items ---
    # In mr_items, if material_request_type is 'Purchase', it means no stock was found.
    purchase_items = [item.item_code for item in pp.mr_items if item.material_request_type == "Purchase"]
    
    if purchase_items:
        # We use set() to avoid repeating the same item code multiple times
        unique_purchase_items = ", ".join(set(purchase_items))
        frappe.throw(_(
            "Cannot create Stock Entry. The following items are out of stock and marked for <b>Purchase</b>: "
            "<br><br><b>{0}</b><br><br>"
            "Please purchase these items or update your inventory before attempting a transfer."
        ).format(unique_purchase_items))

    # --- 2. Fallback Warehouse from Manufacturing Settings ---
    # default_source_wh = frappe.db.get_single_value("Manufacturing Settings", "material_warehouse")
    # if not default_source_wh:
    #     frappe.throw(_("Please set the 'Material Warehouse' in Manufacturing Settings first."))

    # --- 3. Consolidation Logic (Combine same Item Codes) ---
    consolidated_items = {}

    for item in pp.mr_items:
        code = item.item_code
        source_wh = item.from_warehouse 
        
        if code not in consolidated_items:
            consolidated_items[code] = {
                "item_code": code,
                "qty": 0.0,
                "uom": item.uom,
                "s_warehouse": source_wh,
                "t_warehouse": item.warehouse or pp.for_warehouse
            }
        
        consolidated_items[code]["qty"] += item.quantity

    # --- 4. Initialize the Stock Entry ---
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.company = pp.company
    se.posting_date = frappe.utils.nowdate()
    
    if pp.custom_daily_production_id:
        se.custom_daily_production_name = pp.custom_daily_production_id
    # se.production_plan = pp.name



    for code, data in consolidated_items.items():
        if data["qty"] <= 0:
            continue

        se.append("items", {
            "item_code": data["item_code"],
            "qty": data["qty"],
            "uom": data["uom"],
            "stock_uom": data["uom"],
            "s_warehouse": data["s_warehouse"],
            "t_warehouse": data["t_warehouse"],
        })

    # --- 6. Final Save ---
    se.flags.ignore_permissions = True
    se.insert()
    
    return se.name


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _get_default_warehouse():
    return frappe.db.get_value("Warehouse", "HA Production - CAF", "name")


def _add_material_requests(pp, dp_doc):
    for mr_dp in dp_doc.production_table:
        if mr_dp.mr_reference:
            pp.append("material_requests", {"material_request": mr_dp.mr_reference})


def _filter_sub_assembly_items(pp, item_group):
    table = pp.get("sub_assembly_items")
    print(f"[DEBUG] sub_assembly_items count: {len(table)}")
    print(f"[DEBUG] sub_assembly_items: {[item.production_item for item in table]}")
    filtered = [
        item for item in table
        if frappe.db.get_value("Item", item.production_item, "item_group") == item_group
    ]
    pp.set("sub_assembly_items", filtered)


def _filter_sub_assembly_items_delete(pp):
    table = pp.get("sub_assembly_items")
    delete_table = get_delete_table_items_delet()
    print(f"[DEBUG] delete table keys: {list(delete_table.items())}")

    filtered = []
    for item in table:
        delete_entry = delete_table.get(item.production_item)
        if delete_entry and int(delete_entry["class"]) == 0 or frappe.get_value("Item", item.production_item, "item_group") == "WIP TIM":
            continue
        filtered.append(item)

    pp.set("sub_assembly_items", filtered)
    return filtered 


def _cleanup_after_submit(pp, filtered):  # ✅ receive filtered as parameter
    """Remove non-matching rows if on_submit repopulated the table."""
    if not filtered:
        return

    keeping = [i.production_item for i in filtered]  # ✅ extract item names

    saved = frappe.get_all(
        "Production Plan Sub Assembly Item",
        filters={"parent": pp.name},  # ✅ fixed
        fields=["production_item"]
    )
    non_matching = [
        row.production_item for row in saved
        if row.production_item not in keeping
    ]
    if non_matching:
        frappe.db.delete("Production Plan Sub Assembly Item", {
            "parent": pp.name,  # ✅ fixed
            "production_item": ["in", non_matching]
        })
        frappe.db.commit()

def _save_pp_to_daily_production(dp_doc, pp_name, item_group):
    field_map = {
        "Recipe":  "custom_recipe_requisition_form",
        "WIP TIM": "custom_tim_form",
        "WIP":     "custom_wip_form",
    }
    field = field_map.get(item_group)
    
    if field or not field:
        frappe.db.set_value("Daily Production", dp_doc.name, field, pp_name)


# ============================================================
# MAIN FUNCTION
# ============================================================

@frappe.whitelist()
def create_production_plan(dp_name: str, item_group: str) -> str:

    # 1. Validate
    if not item_group:
        frappe.throw("NO Item Group Selected")
    # pdb.set_trace()
    existing_pp = frappe.db.exists(
        "Production Plan",
        {
            "custom_daily_production_id": dp_name,
            "custom_pd_group": item_group,
            "docstatus": ["!=", 2]
        }
    )
    if existing_pp:
        pass

    # 2. Setup
    dp_doc = frappe.get_doc("Daily Production", dp_name)
    target_warehouse = _get_default_warehouse()
    avaliable_warehouse = frappe.db.get_value("Warehouse","W Dummy - CAF")
    if not avaliable_warehouse:
        frappe.throw(_("Please set up the 'W Dummy - CAF' warehouse to skip available sub_assembly items before creating a Production Plan."))
    pp = frappe.new_doc("Production Plan")
    pp.company = frappe.db.get_single_value("Global Defaults", "default_company")
    pp.custom_daily_production_id = dp_name
    pp.custom_pd_group = item_group
    pp.get_items_from = "Material Request"
    pp.skip_available_sub_assembly_item = 1
    pp.for_warehouse = target_warehouse
    pp.sub_assembly_warehouse = avaliable_warehouse  
    pp.custom_ignore_materials_warehouse_for_code = 1
    pp.custom_ignore_for_warehouses_qty = 1

    # if item_group == "WIP":
    pp.custom_remove_items_that_in_delete_table_custom_code = 0

    # 3. Add Material Requests
    _add_material_requests(pp, dp_doc)

    # 4. Populate Items
    pp.get_items()
    pp.get_sub_assembly_items()

    # 5. Filter Sub Assembly Items
    # _filter_sub_assembly_items(pp, item_group)
    # pdb.set_trace() 
    filtered = _filter_sub_assembly_items_delete(pp)

    # 6. Material Explosion
    transfer_materials_for_pp_doc(pp)

    # 7. Insert
    pp.flags.ignore_permissions = True
    pp.insert()
#     pdb.set_trace()
    if item_group != "WIP":
        create_delta(pp)
    # 8. Create Stock Entry is now handled inside create_delta
    # 9. Submit
    pp.submit()
    # 10. Cleanup in case on_submit repopulated the table
    _cleanup_after_submit(pp, filtered)  # ✅ pass filtered as parameter
    # 11. Link PP to Daily Production
    _save_pp_to_daily_production(dp_doc, pp.name, item_group)
    if item_group == "WIP":
        make_work_order = CustomProductionPlan.make_work_order
        single_wo_pp_list = []
        single_wo_pp_list = make_work_order(pp, wip = True)
        for wo in single_wo_pp_list:
            if wo:
                item_code = frappe.db.get_value("Work Order", wo, "production_item")
                print(f"Work Order {wo} has production item {item_code}")
                if item_code:
                    item_type = frappe.db.get_value("Item", item_code, "item_group")
                if item_type != "WIP":
                    frappe.delete_doc("Work Order", wo)
    return pp.name



def _adjust_qty_by_uom(uom, qty):
    """
    If UOM does NOT allow decimals → round UP
    If allows decimals → keep precision
    """
    must_be_whole = frappe.db.get_value("UOM", uom, "must_be_whole_number") or 0

    if must_be_whole:
        return math.ceil(qty)
    else:
        return round(qty, 4)


def create_delta(pp):
    if not pp.mr_items:
        return

    mr_items = pp.mr_items

    # Message collectors to avoid one popup/log per row
    merge_messages = []
    purchase_default_wh_messages = []
    purchase_fallback_wh_messages = []
    delete_skip_items = []

    # -----------------------------
    # 1. Validate Purchase Items
    # -----------------------------
    purchase_items = [
        f"{item.item_code} (Required BOM Qty: {frappe.utils.flt(item.required_bom_qty, 3)})"
        for item in mr_items
        if item.material_request_type == "Purchase"
    ]

    if purchase_items:
        frappe.msgprint(
            _("Cannot transfer. These items are marked for Purchase:<br><br>{0}")
            .format("<br>".join(purchase_items))
        )
        # Log simplified message to avoid character limit (max 140 chars)
        item_codes = [item.split(" ")[0] for item in purchase_items]
        error_summary = f"Transfer blocked: {len(purchase_items)} items marked for Purchase"
        frappe.log_error(error_summary, "create_delta: Purchase Items Blocked")
    
   
    # -----------------------------
    # 2. Validate Production Plan Link
    # -----------------------------
    dp_name = pp.custom_daily_production_id
    if not dp_name:
        frappe.throw(_("Production Plan is not linked to a Daily Production ID."))

    # -----------------------------
    # 3. Default Warehouse
    # -----------------------------
    default_warehouse = frappe.db.get_single_value(
        "Manufacturing Settings",
        "material_warehouse"
    )

    if not default_warehouse:
        frappe.throw(_("Setup Material Warehouse in Manufacturing Settings"))

    # -----------------------------
    # 4. Identify items with multiple warehouses and log errors
    # (Allow multiple warehouses but log them)
    # -----------------------------
    items_with_multiple_wh = {}

    for item in mr_items:
        code = item.item_code
        from_wh = item.from_warehouse

        if code not in items_with_multiple_wh:
            items_with_multiple_wh[code] = set()
        
        if from_wh:
            items_with_multiple_wh[code].add(from_wh)

    # Log items with multiple source warehouses
    for code, warehouses in items_with_multiple_wh.items():
        if len(warehouses) > 1:
            error_msg = f"Item {code} has multiple source warehouses: {', '.join(warehouses)}"
            frappe.log_error(error_msg, "create_delta: Multiple Warehouses")
            frappe.msgprint(_(error_msg))
                

    # -----------------------------
    # 5. Cache Items + Item Defaults
    # -----------------------------
    item_codes = list({d.item_code for d in mr_items})

    items = frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes]},
        fields=["name", "item_name", "purchase_uom", "stock_uom"]
    )

    item_defaults = frappe.get_all(
        "Item Default",
        filters={"parent": ["in", item_codes]},
        fields=["parent", "company", "default_warehouse"]
    )

    # map item defaults
    defaults_map = {}
    for d in item_defaults:
        defaults_map.setdefault(d.parent, []).append(d)

    # build final item map
    items_map = {}
    for d in items:
        items_map[d.name] = {
            "name": d.name,
            "item_name": d.item_name,
            "purchase_uom": d.purchase_uom,
            "stock_uom": d.stock_uom,
            "item_defaults": defaults_map.get(d.name, [])
        }

    # -----------------------------
    # 6. Group Items by Code & Destination Warehouse & Source Warehouse
    # (Keeps different source warehouses separate, combines transfer+purchase)
    # -----------------------------
    items_grouped = {}
    
    for item in mr_items:
        code = item.item_code
        dest_wh = item.warehouse or pp.for_warehouse
        source_wh = item.from_warehouse or None  # Transfer rows have from_warehouse
        
        # Group by (code, dest_wh, source_wh) to keep different source warehouses separate
        key = (code, dest_wh, source_wh)
        if key not in items_grouped:
            items_grouped[key] = []
        items_grouped[key].append(item)
    
    # Post-processing: Combine transfer + purchase rows for same item
    # Rules:
    # 1. If item X has: one row with source_wh='WH-A' (transfer) and one with source_wh=None (purchase)
    #    → Merge purchase into the transfer row
    # 2. If item X has MULTIPLE transfer warehouses (WH-A, WH-B) + one purchase row
    #    → Merge purchase into the FIRST transfer warehouse found (WH-A)
    #    → Keep other transfer warehouses (WH-B) separate
    
    items_grouped_merged = {}
    processed_keys = set()
    
    for key, group_items in items_grouped.items():
        if key in processed_keys:
            continue
            
        code, dest_wh, source_wh = key
        
        # If this is a purchase row (source_wh is None), check for matching transfer row
        if source_wh is None:
            # Look for the FIRST transfer row with same item and destination warehouse
            transfer_key = None
            transfer_source_wh = None
            for existing_key in items_grouped.keys():
                ex_code, ex_dest_wh, ex_source_wh = existing_key
                if ex_code == code and ex_dest_wh == dest_wh and ex_source_wh is not None:
                    transfer_key = existing_key
                    transfer_source_wh = ex_source_wh
                    break  # Take FIRST transfer warehouse found
            
            # If found, merge purchase into the first transfer warehouse
            if transfer_key:
                items_grouped_merged[transfer_key] = items_grouped[transfer_key] + group_items
                processed_keys.add(transfer_key)
                processed_keys.add(key)
                error_msg = f"Item {code}: Merged purchase row into transfer row (using source warehouse: {transfer_source_wh})"
                merge_messages.append(error_msg)
                continue
        
        # Otherwise, keep as is
        items_grouped_merged[key] = group_items
        processed_keys.add(key)
    
    items_grouped = items_grouped_merged
        # pdb.set_trace()
    update_store_purchase_table(dp_name, pp, items_grouped, default_warehouse)

    # -----------------------------
    # 7. Process Grouped Items
    # (Sum quantities, use source warehouse from group key)
    # -----------------------------
    items_in_table = {}
    
    for (code, dest_wh, key_source_wh), group_items in items_grouped.items():
        raw = items_map.get(code)
        if not raw:
            frappe.throw(f"Item not found: {code}")

        first_item = group_items[0]

        # Prevent duplicate totals when the same BOM requirement is repeated
        # across split rows (e.g. multiple transfer allocations or transfer+purchase).
        required_qty_values = [
            frappe.utils.flt(item.required_bom_qty, 9) for item in group_items
        ]
        unique_required_qty = set(required_qty_values)
        if len(unique_required_qty) == 1:
            total_required_qty = required_qty_values[0]
        else:
            total_required_qty = sum(required_qty_values)
        # Determine Source Warehouse
        # Check if this is a purchase-only item
        is_purchase_only = all(item.material_request_type == "Purchase" for item in group_items)
        
        # 1. Use the source warehouse from the group key (if set - transfer row)
        source_wh = key_source_wh
        warehouse_source = "transfer"
        
        # 2. For purchase-only items, prioritize Item default warehouse
        if not source_wh and is_purchase_only:
            defaults = raw.get("item_defaults", [])
            item_default_wh = next(
                (d.get("default_warehouse") for d in defaults if d.get("default_warehouse")),
                None
            )
            if item_default_wh:
                source_wh = item_default_wh
                warehouse_source = "item_default"
                error_msg = f"Item {code}: Purchase-only row using Item default warehouse ({source_wh})"
                purchase_default_wh_messages.append(error_msg)
        
        # 3. If still no warehouse, check for explicit from_warehouse in items
        if not source_wh:
            for item in group_items:
                if item.from_warehouse:
                    source_wh = item.from_warehouse
                    warehouse_source = "explicit_from_warehouse"
                    break
        
        # 4. Final fallback to Manufacturing Settings default
        if not source_wh:
            source_wh = default_warehouse
            warehouse_source = "manufacturing_settings"
            
            # Log fallback to manufacturing settings
            if is_purchase_only:
                error_msg = f"Item {code}: Purchase-only row using Manufacturing Settings default warehouse ({source_wh})"
                purchase_fallback_wh_messages.append(error_msg)

        # Get Purchase UOM
        purchase_uom = raw.get("purchase_uom") or raw.get("stock_uom")
        conversion_factor = 1.0

        # Validate UOM Conversion
        if purchase_uom != first_item.uom:
            exists = frappe.db.exists(
                "UOM Conversion Detail",
                {"parent": code, "uom": purchase_uom}
            )

            if not exists:
                frappe.throw(
                    f"Missing UOM Conversion for Item: {code}, UOM: {purchase_uom}"
                )

            conversion_factor = frappe.db.get_value(
                "UOM Conversion Detail",
                {"parent": code, "uom": purchase_uom},
                "conversion_factor"
            ) or 1.0

        # Calculate combined quantity
        raw_qty = total_required_qty / conversion_factor
        final_qty = _adjust_qty_by_uom(purchase_uom, raw_qty)

        # Build consolidated row
        # Use unique key: item_code + source_warehouse to allow multiple SE rows per item if different warehouses
        unique_key = f"{code}|{source_wh}" if source_wh else code
        
        items_in_table[unique_key] = {
            "item_code": code,
            "s_warehouse": source_wh,
            "t_warehouse": dest_wh,
            "required_bom_qty": total_required_qty,
            "uom": first_item.uom,
            "purchase_uom": purchase_uom,
            "conversion_": conversion_factor,
            "raw_qty": final_qty * conversion_factor,
            "p_qty": final_qty
        }

    # Filter out items that exist in delete table
    delete_table_items = get_delete_table_items()
    keys_to_remove = []
    
    for unique_key in items_in_table.keys():
        # Extract item_code from unique_key (format: "ITEM-CODE" or "ITEM-CODE|WAREHOUSE")
        item_code = unique_key.split("|")[0] if "|" in unique_key else unique_key
        
        if item_code in delete_table_items:
            keys_to_remove.append(unique_key)
            delete_skip_items.append(item_code)
    
    # Remove filtered items
    for key in keys_to_remove:
        del items_in_table[key]

    # Emit batched notifications/logs (one message per category)
    if merge_messages:
        merged_msg = "Merged purchase rows into transfer rows:<br><br>" + "<br>".join(merge_messages)
        frappe.msgprint(_(merged_msg))
        frappe.log_error("\n".join(merge_messages), "create_delta: Merge to First Transfer Warehouse")

    if purchase_default_wh_messages:
        default_wh_msg = "Purchase-only rows using Item default warehouse:<br><br>" + "<br>".join(purchase_default_wh_messages)
        frappe.msgprint(_(default_wh_msg))
        frappe.log_error("\n".join(purchase_default_wh_messages), "create_delta: Purchase-Only Item")

    if purchase_fallback_wh_messages:
        fallback_wh_msg = "Purchase-only rows using Manufacturing Settings default warehouse:<br><br>" + "<br>".join(purchase_fallback_wh_messages)
        frappe.msgprint(_(fallback_wh_msg))
        frappe.log_error("\n".join(purchase_fallback_wh_messages), "create_delta: Purchase-Only Item (Fallback)")

    if delete_skip_items:
        unique_delete_skip_items = sorted(set(delete_skip_items))
        delete_msg = "Items skipped - exist in delete table:<br><br>" + "<br>".join(
            f"Item {item_code}" for item_code in unique_delete_skip_items
        )
        frappe.msgprint(_(delete_msg))
        frappe.log_error(
            "\n".join(f"Item {item_code} skipped - exists in delete table" for item_code in unique_delete_skip_items),
            "create_delta: Delete Table Filtering",
        )
    
    # Get the Daily Production doc
    dp_doc = frappe.get_doc("Daily Production", dp_name)
    existing_table = dp_doc.get(CHILD_TABLE, [])
    
    # If table is empty, populate it and create stock entry with full quantities
    if not existing_table:

        se_id = create_stock_entry_direct_from_pp(pp, items_in_table)

        _add_to_max_table(dp_name, CHILD_TABLE, items_in_table, se_id)
    else:
        # Delta logic: compare quantities and create stock entry for differences
        _update_delta_and_create_se(dp_name, pp, CHILD_TABLE, items_in_table)
    
    return items_in_table

def _add_to_max_table(pd_name, child_table, data, se_id=None):
    """Populate child table with all items."""
    dp_doc = frappe.get_doc("Daily Production", pd_name)
    dp_doc.flags.ignore_permissions = True
    dp_doc.flags.ignore_validate_update_after_submit = True

    # Validate child table field exists
    if not dp_doc.meta.get_field(child_table):
        frappe.throw(
            _("Child table field '{0}' does not exist on Daily Production doctype.").format(child_table)
        )

    dp_doc.set(child_table, [])

    for unique_key, row in data.items():
        # Extract item_code from unique_key (format: "ITEM-CODE" or "ITEM-CODE|WAREHOUSE")
        item_code = row.get("item_code")
        source_warehouse = row.get("s_warehouse")
        
        dp_doc.append(child_table, {
            "item_code": item_code,
            "qty": row.get("raw_qty"),
            "uom": row.get("uom"),
            "purchase_uom": row.get("purchase_uom"),
            "purchase_qty": row.get("p_qty"),
            "se": se_id,
            "source_warehouse": source_warehouse,  # Track which warehouse this came from
        })

    dp_doc.save()


def _update_delta_and_create_se(pd_name, pp, child_table, new_items):

    """
    Delta logic: Compare new items with existing table.
    - If item qty increased, add delta to stock entry and update table.
    - If qty not changed or decreased, ignore.
    """
    # pdb.set_trace()
    dp_doc = frappe.get_doc("Daily Production", pd_name)
    dp_doc.flags.ignore_permissions = True
    dp_doc.flags.ignore_validate_update_after_submit = True

    existing_table = dp_doc.get(child_table, [])
    existing_map = {row.item_code: row for row in existing_table}
    
    delta_items = {}
    delta_item_codes = set()  # Track which items get delta SE
    
    # Compare new vs existing
    for unique_key, new_row in new_items.items():
        # Extract item_code from unique_key (format: "ITEM-CODE" or "ITEM-CODE|WAREHOUSE")
        item_code = new_row.get("item_code")
        
        if item_code in existing_map:
            existing_row = existing_map[item_code]
            new_qty = new_row.get("raw_qty", 0)
            existing_qty = existing_row.qty or 0
            
            # If new qty is more, calculate delta
            if new_qty > existing_qty:
                delta_qty = new_qty - existing_qty
                delta_items[unique_key] = {
                    "item_code": item_code,
                    "qty": delta_qty,
                    "uom": new_row.get("purchase_uom"),
                    "from_warehouse": new_row.get("s_warehouse"),
                    "warehouse": new_row.get("t_warehouse"),
                }
                delta_item_codes.add(item_code)
                # print(f"Item {item_code} qty increased: existing {existing_qty} → new {new_qty} (delta {delta_qty})")
                
                # Update existing table row with new qty
                existing_row.qty = new_qty
        else:
            # New item not in table - add it
            dp_doc.append(child_table, {
                "item_code": item_code,
                "qty": new_row.get("raw_qty"),
                "uom": new_row.get("uom"),
                "purchase_uom": new_row.get("purchase_uom"),
                "purchase_qty": new_row.get("p_qty"),
                "source_warehouse": new_row.get("s_warehouse"),
            })
            
            delta_items[unique_key] = {
                "item_code": item_code,
                "qty": new_row.get("p_qty"),
                "uom": new_row.get("purchase_uom"),
                "from_warehouse": new_row.get("s_warehouse"),
                "warehouse": new_row.get("t_warehouse"),
            }
            delta_item_codes.add(item_code)
        # print(f"New item added to table: {item_code} with qty {new_row.get('raw_qty')}")
    # Create stock entry if there are delta items
    se_id = None
    if delta_items:
        se = frappe.new_doc("Stock Entry")
        se.stock_entry_type = "Material Transfer"
        se.company = pp.company
        se.posting_date = nowdate()
        se.custom_daily_production_name = pd_name
        se.production_plan = pp.name
        
        for code, item_data in delta_items.items():
            frappe.log_error(f"Adding to SE: {item_data['item_code']} with delta qty {item_data['qty']}", "create_delta: Adding to SE")
            se.append("items", {
                "item_code": item_data["item_code"],
                "qty": item_data["qty"],
                "uom": item_data["uom"],
                "stock_uom": item_data["uom"],
                "s_warehouse": item_data.get("from_warehouse"),
                "t_warehouse": item_data.get("warehouse"),
            })
        
        se.flags.ignore_permissions = True
        se.insert()
        se_id = se.name
        
        # Update only delta items with SE ID
        for row in existing_table:
            if row.item_code in delta_item_codes:
                row.se = se_id
    
    # Save updated table
    dp_doc.save()
    
    return se_id


def get_delete_table_items(child_table='custom_requisition_items'):
    result = frappe.db.get_value(
        "start and delete items",
        filters={"custom_is_default": 1},
        fieldname=["name", "docstatus"],
        order_by="creation desc"
    )
    
    if not result:
        frappe.throw(_("No default 'start and delete items' document found. Please create and submit one before proceeding."))
    
    dp_name, docstatus = result
    
    if docstatus != 1:
        frappe.throw(_("Default 'start and delete items' document is not submitted."))
    
    dp_doc = frappe.get_doc("start and delete items", dp_name)
    items = dp_doc.get(child_table, []) or []
    return {row.item_short_name: row for row in items}



def get_delete_table_items_delet(child_table='delet'):
    result = frappe.db.get_value(
        "start and delete items",
        filters={"custom_is_default": 1},
        fieldname=["name", "docstatus"],
        order_by="creation desc"
    )
    
    if not result:
        frappe.throw(_("No default 'start and delete items' document found. Please create and submit one before proceeding."))
    
    dp_name, docstatus = result
    
    if docstatus != 1:
        frappe.throw(_("Default 'start and delete items' document is not submitted."))
    
    dp_doc = frappe.get_doc("start and delete items", dp_name)
    items = dp_doc.get(child_table, []) or []
    
    return {
        row.item_short_name: {
            "class": getattr(row, 'class', None),
            "row": row  # keep full row in case you need other fields later
        }
        for row in items
    }
def update_store_purchase_table(dp_name, pp, items_grouped, manufacturing_default_wh):
    """
    Populates 'store_purchase_items' in Daily Production.
    Hierarchy for Source Warehouse:
    1. Transfer Warehouse (from group key)
    2. Item Default Warehouse (from Item Master for this company)
    3. Manufacturing Settings Warehouse (fallback)
    """
    dp_doc = frappe.get_doc("Daily Production", dp_name)
    dp_doc.set("store_purchase_items", [])
    
    delete_map = get_delete_table_items()
    company = pp.company

    for (code, dest_wh, key_source_wh), group_items in items_grouped.items():
        # Identify if this group contains Purchase or Deleted items
        is_deleted = code in delete_map
        purchase_rows = [
            i for i in group_items
            if i.material_request_type == "Purchase" and not is_deleted
        ]
        
        if purchase_rows or is_deleted:
            # --- UOM LOGIC ---
            # Priority: 1. Use UOM from a Purchase row if it exists
            #           2. Use UOM from a 'Deleted' row
            #           3. Fallback to first row
            if purchase_rows:
                representative_row = purchase_rows[0]
            elif is_deleted:
                # If deleted, find the first row that matches the delete criteria
                representative_row = group_items[0]
            else:
                representative_row = group_items[0]

            uom = representative_row.uom

            # --- WAREHOUSE LOGIC ---
            source_wh = key_source_wh # From transfer row
            
            if not source_wh:
                # Get Default Warehouse from Item for this specific company
                source_wh = frappe.db.get_value("Item Default", 
                    {"parent": code, "company": company}, "default_warehouse")
            
            if not source_wh:
                source_wh = manufacturing_default_wh

            # --- QTY LOGIC ---
            # We sum required_bom_qty (Stock Qty) because it's consistent for calculations
            

            # --- PURPOSE & REASON LOGIC ---
            total_required_qty = 0
            purpose_status = ""
            reasons = ""
            actual_qty = 0.0
            
            if purchase_rows:
                # For purchase rows, keep the row quantity (do not combine).
                total_required_qty = purchase_rows[0].quantity
                reasons = "Purchase"
                purpose_status = "Unavailable"
            elif is_deleted:
                total_required_qty = sum(item.quantity for item in group_items)
                reasons = "In Delete Table"
                actual_qty = frappe.db.get_value("Bin", 
                    {"item_code": code, "warehouse": source_wh}, "actual_qty") or 0
                
                if actual_qty >= total_required_qty:
                    purpose_status = "Pass"
                else:
                    purpose_status = "Unavailable"

                # 4. Append to child table
            dp_doc.append("store_purchase_items", {
                "item_code": code,
                "s_warehouse": source_wh,
                "qty": total_required_qty,
                "purpes": purpose_status , # Named per your requirement
                "reason" : reasons,
                "uom": uom,
                "actual_qty": actual_qty or 0.0

                # "uom": 
            })
    dp_doc.flags.ignore_permissions = True
    dp_doc.flags.ignore_validate_update_after_submit = True
    # pdb.set_trace()
    dp_doc.save()
    frappe.msgprint(_("Store Purchase Items updated in Daily Production."))