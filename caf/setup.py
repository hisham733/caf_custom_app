# from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# def add_manufacturing_fields():
#     create_custom_fields(
#         {
#             "Manufacturing Settings": [
#                 {
#                     "fieldname": "material_warehouse",
#                     "fieldtype": "Link",
#                     "label": "Material Warehouse",
#                     "options": "Warehouse",
#                     "insert_after": "default_scrap_warehouse",
#                 }
#             ]
#         }
#     )

import frappe


def add_training_workspace_card():
    ws_name = "HR"
    if not frappe.db.exists("Workspace", ws_name):
        return

    ws = frappe.get_doc("Workspace", ws_name)
    if any(r.label == "Training" and r.type == "Card Break" for r in ws.links):
        return

    idx = max((r.idx or 0) for r in ws.links) or 0
    idx += 1
    ws.append(
        "links",
        {"idx": idx, "label": "Training", "type": "Card Break", "onboard": 0, "hidden": 0},
    )

    for link in [
        ("Training Program", "Training Program"),
        ("Training Event", "Training Event"),
        ("Training Result", "Training Result"),
        ("Training Feedback", "Training Feedback"),
    ]:
        idx += 1
        ws.append(
            "links",
            {
                "idx": idx,
                "label": link[0],
                "type": "Link",
                "link_type": "DocType",
                "link_to": link[1],
                "onboard": 0,
                "hidden": 0,
            },
        )

    ws.db_update_all()
