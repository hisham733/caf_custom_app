from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def add_manufacturing_fields():
    create_custom_fields(
        {
            "Manufacturing Settings": [
                {
                    "fieldname": "material_warehouse",
                    "fieldtype": "Link",
                    "label": "Material Warehouse",
                    "options": "Warehouse",
                    "insert_after": "default_scrap_warehouse",
                }
            ]
        }
    )
