from __future__ import unicode_literals
import pdb
import frappe
from frappe.model.document import Document

@frappe.whitelist()
def create_production_plans(material_request,DP):
    try:
        material_request_doc = frappe.get_doc("Material Request", material_request)

        if not material_request_doc:
            frappe.throw("Material Request not found")
        print(f"DP.required_by: {DP.required_by if DP else 'No DP provided'}")
        # Prepare data for Production Plan
        production_plan_data = {
            "doctype": "Production Plan",
            "naming_series": "MFG-PP-.YYYY.-",
            "company": material_request_doc.company,
            "get_items_from": "Material Request",
            "material_request": material_request_doc.name,
            # "custom_start_and_delete_items": material_request_doc.custom_start_and_delete_items,
            "custom_required_by": DP.required_by if DP else material_request_doc.schedule_date,

            # "custom_batch_size": material_request_doc.custom_batch_size,
            "custom_size": material_request_doc.custom_batch_size,
            "custom_operation_type": material_request_doc.custom_operation_type,
            "custom_link_id": material_request_doc.custom_link_id,
            "posting_date": frappe.utils.nowdate(),
            "material_requests": [{
                "material_request": material_request_doc.name,
                "custom_link_id": material_request_doc.custom_link_id,
                "material_request_date": material_request_doc.schedule_date
            }],
            "po_items": [
                {
                    "item_code": item.item_code,
                    "bom_no": item.bom_no,
                    "pending_qty": item.qty,
                    "planned_qty": item.qty,
                    "description": item.description,
                    "stock_uom": item.uom,
                    "warehouse": item.warehouse,
                    "planned_start_date": item.schedule_date,
                    # "make_work_order_for_sub_assembly_items": item.custom_make_work_order_for_sub_assembly_items,
                    "custom_wip_warehouse": item.custom_wip_warehouse,
                    "custom_workstation": item.custom_workstation,
                    "custom_round": item.custom_round,
                    "custom_start_time": item.custom_start_time,
                    "custom_item_type": item.custom_item_type
                }
                for item in material_request_doc.items
                if item.item_code and item.qty
            ],
            "custom_recipe_table": [
                {
                    "item_code": cook_item.item_code,
                    "bom_no": cook_item.bom_no,
                    "qty": cook_item.qty,
                    "conversion_factor": cook_item.conversion_factor,
                    "uom": cook_item.uom,
                    "workstation": cook_item.workstation,
                    "round": cook_item.round,
                    "start_time": cook_item.start_time,
                    "item_type": cook_item.item_type,
                    "schedule_date": cook_item.schedule_date
                }
                for cook_item in material_request_doc.custom_recipe_table
            ]
        }
        if material_request_doc.custom_single_wo:
            remove_items = False
        else:
            remove_items = True
        # Create and submit Production Plan
        production_plan = frappe.get_doc(production_plan_data)
        if remove_items:
            production_plan.custom_remove_items_that_in_delete_table_custom_code = True
        else:
            production_plan.custom_remove_items_that_in_delete_table_custom_code = False
        production_plan.save()
        production_plan.submit()

        return production_plan

    except Exception as e:
        frappe.throw(f"Error in create_production_plans: {str(e)}")
