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

import json

import frappe


def add_training_workspace_card():
    ws_name = "HR"
    if not frappe.db.exists("Workspace", ws_name):
        return

    ws = frappe.get_doc("Workspace", ws_name)

    content = json.loads(ws.content or "[]")
    if any(
        block.get("type") == "card" and block.get("data", {}).get("card_name") == "Training"
        for block in content
    ):
        return

    content.append({"type": "card", "data": {"card_name": "Training", "col": "4"}})
    ws.content = json.dumps(content)

    if not any(r.label == "Training" and r.type == "Card Break" for r in ws.links):
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
