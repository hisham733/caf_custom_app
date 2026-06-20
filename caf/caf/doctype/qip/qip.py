# Copyright (c) 2025, hisham and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class QIP(Document):
    pass


#     def before_validate(self):
#         self.get_qip_goal()

#     def get_qip_goal(self):
#         section_name = self.incoming_material_inspection_checklist_section
#         if section_name:
#             # Get the latest QIP Goal for the given section
#             qip_goal_list = frappe.get_list(
#                 "QIP Goal",
#                 filters={
#                     "incoming_material_inspection_checklist_section": section_name
#                 },
#                 fields=["name", "qc_name"],
#                 order_by="creation desc",
#                 limit=1,
#             )

#             if qip_goal_list:
#                 qip_goal_doc = frappe.get_doc("QIP Goal", qip_goal_list[0].name)
#                 # Do something with the qip_goal_doc or qc_name
#                 frappe.msgprint(f"Latest QIP Goal: {qip_goal_doc.qc_name}")
#             if qip_goal_doc:
#                 self.qc_table = qip_goal_doc.get("section_a")
