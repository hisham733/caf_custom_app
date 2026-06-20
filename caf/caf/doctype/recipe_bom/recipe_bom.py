# Copyright (c) 2025, hisham and contributors
# For license information, please see license.txt

# import frappe
import pprint
import frappe
from frappe.model.document import Document


class RecipeBOM(Document):
    def before_save(self):
        get_pack_boms_and_weights_for_client(self.bom_name)

        self.get_size_or_qty()

    def get_size_or_qty(self):
        has_item = bool(self.recipe__wip)
        has_size = bool(self.size2)
        has_qty = bool(self.qty)

        if not has_item:
                return

        # Case 1: size entered -> calculate qty
        if has_size and not has_qty:
                # print("🟢 Mode: Size -> Qty")
                self.calculate_qty_from_size()

        # Case 2: qty entered -> calculate size
        elif has_qty and not has_size:
                # print("🔵 Mode: Qty -> Size")
                self.calculate_size_from_qty()

        # If both provided, respect size (or throw error if you prefer)
        elif has_size and has_qty:
                # print("⚠️ Both Size & Qty entered. Using Size to recalc Qty.")
                self.calculate_qty_from_size()

    def fetch_yell_value(self, item_code):
        bom = frappe.db.get_value("BOM", {"item": item_code, "is_default": 1}, "name")
        if not bom:
                frappe.throw(f"No BOM found for item: {item_code}")

        yell_value = frappe.db.get_value("BOM", bom, "custom_yield")
        if not yell_value or yell_value == 0:
                frappe.throw(f"No Yield value found or Yield = 0 in BOM for item: {item_code}")

        return yell_value

    def get_bom_total(self, item_code):
        bom = frappe.db.get_value("BOM", {"item": item_code, "is_default": 1}, "name")
        if not bom:
                frappe.throw(f"No Default BOM found for Cook Item: {item_code}")
        # bom_yell = bom.custom_yield
        # if not bom_yell:
        # 	frappe.throw(f"No Yield value found or Yield = 0 in BOM for item: {item_code}")	
        bom_items = frappe.get_all(
                "BOM Item",
                filters={"parent": bom},
                fields=["item_code", "qty"]
        )

        total = 0
        for bi in bom_items:
                # print(f"bi: {bi}")
                uom = frappe.get_cached_value("Item", bi["item_code"], "stock_uom")
                qty = bi["qty"] / 1000 if uom.lower() == "gram" else bi["qty"]
                total += qty
                # print(f"total: {total}")
        return total

    def calculate_qty_from_size(self):
        item = self.recipe__wip
        size = self.size2

        bom_total = self.get_bom_total(item)
        bom_yell = self.fetch_yell_value(item)

        total_qty = round(bom_total * size ,9)

        # print(f"✅ calculate_qty_from_size Qty {total_qty} -> Size {size} (Yield={self.yeiled})")
        self.qty = total_qty * bom_yell
        self.yeiled = bom_yell
        
    def calculate_size_from_qty(self):
        item = self.recipe__wip
        qty = self.qty
        
        bom_total = self.get_bom_total(item)
        bom_yell = self.fetch_yell_value(item)
        # print(f"bom_yell: {bom_yell}")
        size = round(qty / (bom_total * bom_yell),9)

        self.size2 = size
        self.yeiled = bom_yell
        # print(f"✅calculate_size_from_qty Qty {qty} -> Size {size} (Yield={self.yeiled})")

    def calculate_parent_qty_from_raw(self):
        parent_item = self.recipe__wip
        raw_item = self.raw_mat
        raw_qty = self.raw_qty

        frappe.logger().info(f"Parent Item = {parent_item}, Raw Material = {raw_item}, Raw Qty = {raw_qty}")

        # Fetch default BOM of parent
        bom = frappe.db.get_value("BOM", {"item": parent_item, "is_default": 1}, "name")
        if not bom:
                frappe.throw(f"No default BOM found for item {parent_item}")

        # Get raw material qty inside BOM
        bom_item = frappe.db.get_value(
                "BOM Item",
                {"parent": bom, "item_code": raw_item},
                ["qty"],
                as_dict=True
        )

        if not bom_item:
                frappe.throw(f"{raw_item} is not a component in BOM of {parent_item}")

        bom_raw_qty_per_unit = bom_item["qty"]

        # Convert to KG if item UOM is gram
        raw_uom = frappe.get_cached_value("Item", raw_item, "stock_uom")
        if raw_uom and raw_uom.lower() == "gram":
                bom_raw_qty_per_unit = bom_raw_qty_per_unit / 1000

        frappe.logger().info(f"BOM child quantity per 1 {parent_item}: {bom_raw_qty_per_unit}")

        if bom_raw_qty_per_unit == 0:
                frappe.throw("Invalid BOM quantity")

        # Calculate how many parent units can be produced
        estimated_parent_qty = raw_qty / bom_raw_qty_per_unit

        self.estimated_production_qty = estimated_parent_qty

        frappe.msgprint(f"Estimated {parent_item} producible: {estimated_parent_qty}")

        frappe.logger().info(f"Estimated parent qty = {estimated_parent_qty}")


from frappe.utils import flt
def fetch_weight(item_code):
    # 1. Try to get weight from Variant Attributes
    weight = frappe.db.get_value(
        "Item Variant Attribute",
        {"parent": item_code, "attribute": "Weight"},
        "attribute_value",
    )

    # Convert to float safely; handle None or empty strings
    weight_val = flt(weight)

    # 2. Fallback to Item Master weight if Variant weight is 0 or missing
    if not weight_val:
        weight_val = frappe.db.get_value("Item", item_code, "weight_per_unit")
    
    # Optional: Ensure we return a float and not None
    return flt(weight_val)

@frappe.whitelist()
def get_pack_boms_and_weights_for_client(recipe_bom_name):
    result = []

    # Get the main Recipe BOM document
    recipe_bom = frappe.get_doc("BOM", recipe_bom_name)
    recipe_qty = recipe_bom.quantity
    recipe_item_code = recipe_bom.item

    # Find related BOMs that include the same item as this Recipe BOM
    pack_boms = frappe.db.sql(
        """
        SELECT DISTINCT bi.parent AS name
        FROM `tabBOM Item` bi
        JOIN `tabBOM` b ON b.name = bi.parent
        WHERE bi.item_code = %s
          AND b.is_default = 1
          AND b.docstatus = 1
          AND b.name != %s
        """,
        (recipe_item_code, recipe_bom_name),
        as_dict=True,
    )

    total_quantity = 0  # <-- Initialize the sum

    for bom in pack_boms:
        bom_name = bom["name"]
        bom_doc = frappe.get_doc("BOM", bom_name)
        main_item_code = bom_doc.item

        # Get weight per unit from Item master
        weight_kg = fetch_weight(main_item_code)
        # frappe.msgprint(f"weight_kg: {weight_kg}")
      

        if not weight_kg:
            frappe.throw(
                f"Missing weight_per_unit {weight_kg} for item {main_item_code} in BOM {bom_name}"
            )

        # Get quantity of the recipe item in this B

        result.append(
            {
                "item_name": main_item_code,
                "weight_kg": weight_kg,
                #     "total_qty": total_qty,
            }
        )

    # Optionally return total_quantity as well
    return {
        "items": result,
        "recipe_qty": recipe_qty,
    }



@frappe.whitelist()
def get_bom_items_for_item(item_code):
      bom = frappe.db.get_value("BOM", {"item": item_code, "is_default": 1}, "name")
      if not bom:
            return []

      items = frappe.get_all(
            "BOM Item",
            filters={"parent": bom},
            fields=["item_code"]
      )
      return [i["item_code"] for i in items]


@frappe.whitelist()
def calculate_qty_from_size_api(item, size):
    doc = frappe.new_doc("Recipe BOM")
    doc.recipe__wip = item
    doc.size2 = float(size)
    doc.calculate_qty_from_size()
    return {"qty": doc.qty, "yeiled": doc.yeiled}


@frappe.whitelist()
def calculate_size_from_qty_api(item, qty):
    doc = frappe.new_doc("Recipe BOM")
    doc.recipe__wip = item
    doc.qty = float(qty)
    doc.calculate_size_from_qty()
    return {"size2": doc.size2, "yeiled": doc.yeiled}




@frappe.whitelist()
def calculate_parent_output(parent_item, bom_item_code, available_qty):
    available_qty = float(available_qty)

    bom_name = frappe.get_value("BOM", {"item": parent_item, "is_active": 1, "is_default": 1}, "name")
    if not bom_name:
        frappe.throw(f"No BOM found for parent item {parent_item}")

    bom_doc = frappe.get_doc("BOM", bom_name)

    # find the BOM item
    bom_item = next((i for i in bom_doc.items if i.item_code == bom_item_code), None)
    if not bom_item:
        frappe.throw(f"{bom_item_code} not found in BOM for {parent_item}")

    # ratio: how much raw material needed per 1 unit of parent
    bom_ratio = bom_item.qty / bom_doc.quantity

    # calculate possible parent output
    possible_output = available_qty / bom_ratio

    return {
        "parent_item": parent_item,
        "bom_item": bom_item_code,
        "available_bom_item_qty": available_qty,
        "possible_parent_qty": round(possible_output, 9)
    }

@frappe.whitelist()
def calculate_raw_needed(parent_item, bom_item_code, parent_qty):
    """
    Calculate the required quantity of a raw material (BOM item) 
    needed to produce a given quantity of parent item, respecting the BOM.
    """
    try:
        # Ensure parent_qty is float
        parent_qty = float(parent_qty)
        print(f"Parent Qty entered: {parent_qty}")

        # Get default BOM for the parent item
        bom = frappe.db.get_value("BOM", {"item": parent_item, "is_default": 1}, "name")
        if not bom:
            frappe.throw(f"No default BOM found for {parent_item}")
        print(f"BOM found: {bom}")

        # Get quantity of parent in BOM
        parent_qty_in_bom = frappe.db.get_value("BOM", bom, "quantity") or 1
        print(f"Parent quantity in BOM: {parent_qty_in_bom}")

        # Get BOM item quantity
        bom_item = frappe.db.get_value(
            "BOM Item",
            {"parent": bom, "item_code": bom_item_code},
            ["qty"],
            as_dict=True
        )
        if not bom_item:
            frappe.throw(f"{bom_item_code} not found in BOM of {parent_item}")

        bom_item_qty = float(bom_item["qty"])
        print(f"BOM Item qty per parent in BOM: {bom_item_qty}")

        # Convert UOM if needed (grams -> kg)
        raw_uom = frappe.get_cached_value("Item", bom_item_code, "stock_uom")
        if raw_uom and raw_uom.lower() == "gram":
            bom_item_qty = bom_item_qty / 1000
            print(f"Converted BOM item qty to KG: {bom_item_qty}")

        # Calculate required raw quantity using BOM ratio
        required_raw_qty = parent_qty * (bom_item_qty / parent_qty_in_bom)
        # print(f"Required raw qty: {required_raw_qty}")

        return {"required_raw_qty": required_raw_qty}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in calculate_raw_needed")
        frappe.throw(f"Error calculating raw quantity: {str(e)}")






@frappe.whitelist()
def get_single_bom_items(*args, **kwargs):
    """
    Return Item names that have a default BOM with exactly one BOM Item.
    """
    items = []

    boms = frappe.get_all("BOM", filters={"is_default": 1}, fields=["name", "item"])

    for bom in boms:
        bom_items = frappe.get_all("BOM Item", filters={"parent": bom.name}, fields=["item_code"])
        if len(bom_items) == 1 and bom.item and not bom.item.startswith("TIM"):
            items.append([bom.item])  # <- return as list inside a list
    
    # print(f"items: {[i[0] for i in items]}")  # debug
    return items
