import math
import pdb
from erpnext.stock.doctype.material_request.material_request import MaterialRequest
# from erpnext.manufacturing.doctype.production_plan.production_plan import ProductionPlan
from caf.caf.overrides.production_plan import CustomProductionPlan
from frappe.model.document import flt

from caf.caf.overrides.pp import create_production_plans
import frappe

from frappe.model.naming import make_autoname


# from erpnext.stock.doctype.material_request.pp import validate_custom_recipe_table
class CustomMaterialRequest(MaterialRequest):
    def validate(self):
        super().validate()
        # frappe.msgprint("from override")
        # Call the new functions
        if self.custom_batch_size:
            self.set_latest_record()
            self.validate_cook_items()
            self.update_cook_items_quantities()
            self.update_pack_items_quantities()

    def run_chic_item(self):
        def chic_item(item):
            chic_item_group = frappe.db.get_value(
                "Item",
                filters={"item_code": item},
                fieldname=[
                    "item_group",
                ],
            )
            if chic_item_group == "CHIC WIP":
                return True
            else:
                return False

        first_item_code = (
            self.items[0].get("item_code")
            if isinstance(self.items[0], dict)
            else self.items[0].item_code
        )
        cheic = chic_item(first_item_code)
        return cheic

    def before_submit(self):
        super().before_submit()
        chic = self.run_chic_item()
        # if self.custom_batch_size or chic == True:
        should_run = self.flags.run_chic_flow or False
        if self.custom_batch_size or should_run or self.custom_daily_production_id:
            self.validate_id()

    def on_submit(self):
        super().on_submit()
        chic = self.run_chic_item()
        should_run = self.flags.run_chic_flow or False
        if self.custom_batch_size or should_run or self.custom_daily_production_id:
            DP = frappe.get_doc("Daily Production", self.custom_daily_production_id) if self.custom_daily_production_id else None
            PPlanPointer = create_production_plans(self.name,DP)
            self.p_name = PPlanPointer.name
            # frappe.msgprint(f"PPlanPointer: {PPlanPointer}")
            if not PPlanPointer:
                return
            make_work_order = CustomProductionPlan.make_work_order

            self.wo_list = make_work_order(PPlanPointer)
            # ✅ Add here — right after wo_list is populated
            if self.wo_list:
                wo_details = frappe.get_all(
                    "Work Order",
                    filters={"name": ["in", self.wo_list]},
                    fields=["name", "custom_item_type"]
                )
                self.wo_type_map = {row.name: row.custom_item_type for row in wo_details}

                # ✅ All WOs with type — "(wo-1123,Pack),(wo-87623,Cook)"
                self.wo_list_with_type = ",".join(
                    f"({wo},{item_type})" for wo, item_type in self.wo_type_map.items()
                )
            return self.wo_list

    # function to check the recipe in cook item table that planner inpout it
    # function to check if the Recipe Item that the planner key in Planner Excel is within the first Pack Item' BOM
    def validate_cook_items(self):
        try:
            if not self.custom_recipe_table or not self.items:
                return

            if len(self.custom_recipe_table) > 1:
                frappe.throw("There should only be one item in the Cook Items table.")

            first_item_code = self.items[0].item_code

            bom = frappe.db.get_value(
                "BOM", {"item": first_item_code, "is_default": 1}, "name"
            )
            if not bom:
                frappe.throw(
                    f"No default BOM found for the first item: {first_item_code}"
                )

            bom_items = frappe.get_all(
                "BOM Item", filters={"parent": bom}, fields=["item_code"]
            )
            bom_item_codes = [bom_item.item_code for bom_item in bom_items]

            unmatched_cook_items = [
                cook_item.item_code
                for cook_item in self.custom_recipe_table
                if cook_item.item_code not in bom_item_codes
            ]
            if unmatched_cook_items:
                unmatched_items_str = ", ".join(unmatched_cook_items)
                frappe.throw(
                    f'The following Recipe Cook Items "{unmatched_items_str}" dose not match any items in the BOM for "{first_item_code}" . '
                )

        except frappe.ValidationError:
            raise

        except Exception as e:
            frappe.log_error(message=str(e), title="Cook Items Validation Error")
            frappe.throw(
                "An unexpected error occurred during Cook Items validation. Please check the error log for details."
            )

    # GLOBAL VARIABLE in CustomMaterialRequest
    yell_value = 0

    # update the cook QTY in cook item table ( Total Inoutp )
    def update_cook_items_quantities(self):
        """
        Calculate and set qty for each item in the recipe table
        based on BOM items, batch size, and UOM conversion.
        """
        # ── 1. Guard Conditions ───────────────────────────────────────────
        if not self.custom_recipe_table or self.material_request_type != "Manufacture":
            return

        if not self.custom_batch_size:
            frappe.throw(
                "Batch Size is not specified in the Material Request or Size = 0."
            )

        batch_size = self.custom_batch_size

        # ── 2. Process Each Cook Item ─────────────────────────────────────
        for cook_item in self.custom_recipe_table:
            cook_item.qty = self._calculate_cook_item_qty(
                cook_item.item_code, batch_size
            )


    def _calculate_cook_item_qty(self, item_code, batch_size):
        """
        Calculate total raw material qty for a cook item
        based on its default BOM and batch size.
        """
        # ── Fetch BOM in single query ─────────────────────────────────────
        bom_data = frappe.db.get_value(
            "BOM",
            {"item": item_code, "is_default": 1},
            ["name", "custom_yield"],
            as_dict=True,
        )

        if not bom_data:
            frappe.throw(f"No default BOM found for Cook Item: '{item_code}'")

        if not bom_data.custom_yield or bom_data.custom_yield == 0:
            frappe.throw(
                f"Yield value is missing or zero in BOM '{bom_data.name}' "
                f"for Cook Item: '{item_code}'"
            )

        # ── Fetch BOM Items ───────────────────────────────────────────────
        bom_items = frappe.get_all(
            "BOM Item",
            filters={"parent": bom_data.name},
            fields=["item_code", "qty", "uom", "stock_uom"],
        )

        if not bom_items:
            frappe.throw(f"No items found in BOM '{bom_data.name}' for item '{item_code}'")

        # ── Calculate Total Input Qty ─────────────────────────────────────
        total_input_qty = 0
        for bom_item in bom_items:
            qty_in_kg = self._convert_qty_to_kg(
                qty      = float(bom_item.qty),
                uom      = bom_item.stock_uom or bom_item.uom,
                item_code= bom_item.item_code,
            )
            total_input_qty += float(qty_in_kg) * float(batch_size)

        return round(total_input_qty, 9)


    def _convert_qty_to_kg(self, qty, uom, item_code):
        """
        Convert item qty to kilograms based on UOM.
        Extend this method as more UOMs are needed.
        """
        uom_lower = uom.lower()

        conversion_map = {
            "kg"       : 1,
            "kilogram" : 1,
            "g"        : 0.001,
            "gram"     : 0.001,
            "mg"       : 0.000001,
            "milligram": 0.000001,
            "lb"       : 0.453592,
            "pound"    : 0.453592,
            "oz"       : 0.028349,
            "ounce"    : 0.028349,
        }

        factor = conversion_map.get(uom_lower)

        if factor is None:
            frappe.throw(
                f"Unsupported UOM '{uom}' for item '{item_code}'. "
                f"Supported UOMs: {', '.join(conversion_map.keys())}"
            )

        return qty * factor

    def update_pack_items_quantities(self):
        """
        Calculate total output using yield formula from BOM,
        then distribute quantities across pack items by weight.
        """
        if not self.items or self.material_request_type != "Manufacture":
            return

        if not self.custom_recipe_table:
            frappe.throw("No items found in the Recipe Table.")

        # ── 1. Gather inputs ─────────────────────────────────────────────
        first_recipe_row  = self.custom_recipe_table[0]
        first_item_code   = first_recipe_row.item_code
        first_item_qty    = first_recipe_row.qty
        custom_batch_size = self.custom_batch_size

        # ── 2. Fetch BOM data (single query) ─────────────────────────────
        bom_data = frappe.db.get_value(
            "BOM",
            {"item": first_item_code, "is_default": 1},
            ["name", "custom_yield", "custom_yield_formula"],
            as_dict=True,
        )

        if not bom_data:
            frappe.throw(f"No default BOM found for item: {first_item_code}")

        if not bom_data.custom_yield:
            frappe.throw(f"Yield value is missing or zero in BOM for item: {first_item_code}")

        if not bom_data.custom_yield_formula:
            frappe.throw(f"No yield formula defined in BOM for item: {first_item_code}")

        yield_value = bom_data.custom_yield
        formula     = bom_data.custom_yield_formula

        # ── 3. Calculate total output via formula ─────────────────────────
        total_output = self._evaluate_yield_formula(
            formula       = formula,
            item_code     = first_item_code,
            batch_size    = custom_batch_size,
            yield_value   = yield_value,
            raw_mat_qty   = first_item_qty,
        )
        self.custom_total_output = total_output

        # ── 4. Distribute quantities by weight ────────────────────────────
        self._distribute_qty_by_weight(total_output)


    def _evaluate_yield_formula(self, formula, item_code, batch_size, yield_value, raw_mat_qty):
        """
        Safely evaluate the yield formula stored in BOM.
        Available variables: size, custom_yield, total_raw_mat
        """
        context = {
            "size"         : batch_size,
            "custom_yield" : yield_value,
            "total_raw_mat": raw_mat_qty,
        }

        try:
            result = eval(formula, {}, context)
        except Exception as e:
            frappe.throw(
                f"Error evaluating yield formula for item '{item_code}': {str(e)}"
                f"<br>Formula: <b>{formula}</b>"
                f"<br>Values: {context}"
            )

        return result


    def _get_item_weight(self, item_code):
        """
        Fetch item weight — first from Item Variant Attribute,
        fallback to Item.weight_per_unit.
        """
        weight = frappe.db.get_value(
            "Item Variant Attribute",
            {"parent": item_code, "attribute": "Weight"},
            "attribute_value",
        )

        if weight is None:
            weight = frappe.db.get_value(
                "Item", item_code, "weight_per_unit"
            )

        if weight is None:
            frappe.throw(f"Weight not found for item: {item_code}")

        return float(weight)

    def _distribute_qty_by_weight(self, total_output):
        """
        Distribute total output across pack items based on weight.
        Last item absorbs remaining quantity after all others are accounted for.
        """
        last_item        = self.items[-1]
        last_item_weight = self._get_item_weight(last_item.item_code)
    
        # ── Single item: entire output goes to it ─────────────────────────
        if len(self.items) == 1:
            last_item.qty = total_output / last_item_weight
            last_item.qty = truncate_float(last_item.qty)
            # trunc_no_9  = truncate_float(last_item.qty)
            # trunc_no_5  = truncate_float(last_item.qty,5)
            # print(f"Single item '{last_item.item_code}' assigned full output: {last_item.qty} units")
            # print(f"Truncated Qty for single item: {trunc_no_9}")
            # print(f"Truncated Qty (5 decimals) for single item: {trunc_no_5}")
            return

        # ── Multiple items: sum weighted qty of all except last ───────────
        weighted_sum = 0
        for item in self.items[:-1]: 
            weight        = self._get_item_weight(item.item_code)
            weighted_sum += item.qty * weight

        # Remaining output absorbed by last item
        remaining_qty  = (total_output - weighted_sum) / last_item_weight
        last_item.qty = remaining_qty
        last_item.qty = truncate_float(last_item.qty)
        # trunc_no_9_last  = truncate_float(last_item.qty)
        # trunc_no_5_last  = truncate_float(last_item.qty,5)
        # print(f"Last item '{last_item.item_code}' assigned remaining output: {last_item.qty} units")
        # print(f"Truncated Qty for last item: {trunc_no_9_last}")
        # print(f"Truncated Qty (5 decimals) for last item: {trunc_no_5_last}")

        # ── Validate last item has minimum packable quantity ──────────────
        if last_item.qty < last_item_weight:
            frappe.throw(
                f"Quantity {last_item.qty} is not enough "
                f"to pack item '{last_item.item_code}' "
                f"(minimum weight: {last_item_weight})"
            )

        # ── Validate no item exceeds total output ─────────────────────────
        for item in self.items:
            weight      = self._get_item_weight(item.item_code)
            item_output = 0.0
            item_output += item.qty * weight
            if item_output > self.custom_total_output:
                frappe.throw(
                    f"Item '{item.item_code}' output ({item_output}) "
                    f"exceeds total available output ({total_output}). "
                    f"Check recipe output or item quantity."
                )
    def validate_id(self):
        """Automatically generate a sequential custom_id using a naming series (with debug logs)."""
        if not self.custom_link_id:
            self.custom_link_id = None
            new_id = make_autoname("R-.YYYY.-.#####")
            # print(f"Generated Custom ID: {new_id}")  # Debugging output
            self.custom_link_id = new_id

    def set_latest_record(self):
        """
        Fetches the latest record of the linked Doctype. If the latest record is not submitted,
        throws an error prompting the user to submit it first.
        Triggered on the validate event.
        """
        try:
            # Fetch the latest record from the target Doctype
            latest_record = frappe.db.get_value(
                "start and delete items",
                filters={},
                fieldname=["name", "docstatus"],
                order_by="creation desc",
            )
            if latest_record:
                record_name, record_docstatus = latest_record
                # Check if the latest record is submitted
                if record_docstatus != 1:
                    frappe.throw(
                        f"The latest record '{record_name}' in start and delete items is not submitted. "
                        "Please submit it before proceeding."
                    )
                # Update the link field in Material Request with the latest submitted record
                self.new_doc = (
                    record_name  # Replace 'link_fieldname' with your actual fieldname
                )
            else:
                frappe.throw("No records found in the start and delete item Doctype.")

        except frappe.DoesNotExistError:
            frappe.throw("The start and delete item Doctype does not exist.")

    # --------------------------------------------------------------------------------------------


@frappe.whitelist()
def submit_chic_flow_action(doc_name):
    """
    This function is ONLY called by your Custom Button.
    It sets the flag, then submits.
    """
    doc = frappe.get_doc("Material Request", doc_name)
    
    if doc.docstatus == 1:
        frappe.throw("Document is already submitted")
        
    # Set the flag so on_submit knows to run the extra code
    doc.flags.run_chic_flow = True
    
    # This triggers on_submit
    doc.submit()
    
    return True



def truncate_float(value, decimals=9):
    factor = 10 ** decimals
    return math.trunc(value * factor) / factor