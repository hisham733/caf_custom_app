import math
import frappe
import json
from erpnext.manufacturing.doctype.bom.bom import BOM

class CustomBOM(BOM):
	def before_save(self):
		check_qty(self)




# @frappe.whitelist()
# def update_total_input_for_bom(bom_name):
#     try:
#         bom_doc = frappe.get_doc("BOM", bom_name)
#         if not hasattr(bom_doc, "items") or not bom_doc.items:
#             return f"❌ BOM {bom_name} has no items."

#         total_input = sum(
#             (item.qty / 1000 if item.uom == "Gram" else item.qty)
#             for item in bom_doc.items if item.uom in ["Gram", "Kg"]
#         )

#         if total_input == 0:
#             return "⚠️ Skipping percentage calculation: Total input is 0"

#         updated = False
#         total_percentage = 0

#         for item in bom_doc.items:
#             if item.uom in ["Gram", "Kg"]:
#                 item_qty_kg = item.qty / 1000 if item.uom == "Gram" else item.qty
#                 percentage = round((item_qty_kg / total_input) * 100, 2)

#                 item.custom_qty_percentage = percentage
#                 item.db_update()

#                 total_percentage += percentage
#                 updated = True

#         total_per = round(total_percentage, 2)
#         # if total_per != 100.00:
#         #     frappe.msgprint(f"Error: Total Raw mat is {total_per}% (must be 100%)")

#         bom_doc.custom_raw_materails = total_input
#         bom_doc.db_update()

#         if updated:
#             frappe.db.commit()
#             bom_doc.reload()

#         return f"✅ BOM {bom_name} updated successfully."

#     except frappe.DoesNotExistError:
#         return f"❌ BOM {bom_name} not found."
#     except Exception as e:
#         return f"❌ Error: {str(e)}"








# @frappe.whitelist()
# def check_qty(doc):

#     # Convert string to dict if needed
#     if isinstance(doc, str):
#         doc = frappe._dict(json.loads(doc))  # Converts string to frappe-style dict

#     name = doc.get("item")

#     # Convert to uppercase first
#     if name:
#         name = name.upper()

#         # Check if name starts with "REC"
#         if name.startswith("REC"):

#             custom_yield = doc.get("custom_yield")
#             custom_raw = doc.get("custom_raw_materails")
#             quantity = doc.get("quantity")
#             formula = doc.get("custom_yield_formula")


#             # Validate required values
#             # if not custom_yield or not custom_raw:
#             #     frappe.throw("⚠️ Check 'Yield' or 'Total Raw Materials' fields — they must not be 0 or empty.")
            
#             if not formula:
#                 frappe.throw("⚠️ The Formula Not Found")

#             # Show locals before eval
#             locals_for_eval = {
#                 "custom_yield": custom_yield,
#                 "total_raw_mat": custom_raw,  # match expected var name
#             }

#             try:
#                 custom_quantity = round(eval(formula, {}, locals_for_eval), 9)
#             except Exception as e:
#                 frappe.throw(f"Error evaluating formula: {str(e)}")

#             # Compare with given quantity
#             if quantity != custom_quantity:

#                 frappe.msgprint(f"NOTE: Quantity changed to {custom_quantity}")
#                 frappe.set_value(doc.doctype, doc.name, "quantity", custom_quantity)
#     return {"status": "success"}



from frappe.utils import flt
@frappe.whitelist()
def check_qty(doc):
    # 1. Handle JS frappe.call (which sends a string or a name)
    if isinstance(doc, str):
        try:
            # If it's a JSON string of the doc
            doc = frappe._dict(json.loads(doc))
        except (ValueError, json.JSONDecodeError):
            # If it's just the docname (string), fetch the doc
            doc = frappe.get_doc("BOM", doc)
    
    # 2. Safety: Skip if document isn't saved yet (for JS calls)
    if not doc.get("name") or doc.get("name").startswith("New "):
        return {"status": "skipped"}

    item_name = (doc.get("item") or "").upper()

    if item_name.startswith("REC"):
        custom_yield = flt(doc.get("custom_yield"))
        custom_raw = flt(doc.get("custom_raw_materails"))
        quantity = flt(doc.get("quantity"))
        formula = doc.get("custom_yield_formula")

        if not formula:
            return {"status": "error", "message": "Formula Not Found"}

        # Logic for formula evaluation
        locals_for_eval = {
            "custom_yield": custom_yield,
            "total_raw_mat": custom_raw,
        }

        try:
            # Safer eval
            computed_quantity = round(eval(formula, {"__builtins__": None}, locals_for_eval), 9)
        except Exception as e:
            frappe.throw(f"Error evaluating formula: {str(e)}")

        # 3. Apply changes
        if abs(quantity - computed_quantity) > 0.000001:
            if hasattr(doc, "set_value") and not isinstance(doc, frappe._dict):
                # If it's a real Document object (before_save)
                doc.quantity = computed_quantity
            else:
                # If it's a dictionary from a JS call
                frappe.db.set_value("BOM", doc.name, "quantity", computed_quantity)
            
            return {"status": "updated", "new_qty": computed_quantity}

    return {"status": "success"}