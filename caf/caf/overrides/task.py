import frappe
from frappe import _


@frappe.whitelist()
def get_maintenance_items(workstation):
    """Get items where the given workstation exists in custom_maintenance child table."""
    items = frappe.db.sql(
        """
        SELECT DISTINCT parent AS name
        FROM `tabmaintenance_table`
        WHERE workstation = %s
        """,
        (workstation,),
        as_dict=True,
    )

    if not items:
        return []

    item_names = [d.name for d in items]

    result = frappe.db.sql(
        """
        SELECT i.name, i.item_name, i.image, id.default_warehouse
        FROM `tabItem` i
        LEFT JOIN `tabItem Default` id ON id.parent = i.name
        WHERE i.name IN %s
        """,
        (tuple(item_names),),
        as_dict=True,
    )

    return result


@frappe.whitelist()
def create_material_issue_stock_entry(task_name, items):
    """Create a Material Issue Stock Entry for the given task and items.

    items: JSON string of list of dicts with keys:
        item_code, qty, s_warehouse, description, location, file_url
    """
    import json

    if isinstance(items, str):
        items = json.loads(items)

    if not items:
        frappe.throw(_("No items provided"))

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Issue"
    se.company = frappe.db.get_default("company")
    se.posting_date = frappe.utils.nowdate()
    se.posting_time = frappe.utils.nowtime()
    se.custom_task = task_name

    for item in items:
        se.append(
            "items",
            {
                "item_code": item.get("item_code"),
                "qty": item.get("qty"),
                "s_warehouse": item.get("warehouse"),
                "custom_disposal_description": item.get("description", ""),
                "custom_disposal_photo": item.get("file_url", ""),
                "custom_disposal_location_": item.get("location", ""),
            },
        )

    se.insert(ignore_permissions=True)
    return se.as_dict()
