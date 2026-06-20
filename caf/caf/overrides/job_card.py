import frappe
from frappe.model.document import Document
from erpnext.manufacturing.doctype.job_card.job_card import JobCard
from frappe.utils import flt
from frappe import _
class CustomJobCard(JobCard):
    def validate(self):
        super().validate()
        self.custom_set_status()
    def custom_set_status(self, update_status=False):
        print("custom_set_status start")
        if self.status == "On Hold" and self.docstatus == 0:
            return

        self.status = {0: "Open", 1: "Submitted", 2: "Cancelled"}[self.docstatus or 0]

        if self.docstatus < 2:
            if flt(self.for_quantity) <= flt(self.transferred_qty):
                self.status = "Material Transferred"

            if self.time_logs:
                self.status = "Work In Progress"

            if self.docstatus == 1 and (
                self.for_quantity <= (self.total_completed_qty + self.process_loss_qty) or not self.items
            ):
                self.status = "Completed"

        if update_status:
            self.db_set("status", self.status)

        if self.status in ["Completed", "Work In Progress"]:
            status = {
                "Completed": "Idle",
                "Work In Progress": "Production",
            }.get(self.status)

            self.update_status_in_workstation(status)



@frappe.whitelist()
def create_qi_from_job_card(job_card_name):
    # Get the Job Card document
    job_card = frappe.get_doc("Job Card", job_card_name)

    # Ensure the Job Card has a work order
    if not job_card.work_order:
        frappe.throw(_("Work Order is missing from this Job Card."))

    custom_qi_items = []
    # Add the production_item of the job card to the custom_qi_items child table
    custom_qi_items.append(
        {
            "item_code": job_card.production_item,
            "stock_qty": 1,  # Assuming 1 qty for the production item; you can modify this
            # "description": job_card.description or "No Description",
        }
    )

    if not custom_qi_items:
        frappe.throw(("No items requiring inspection found on this Job Card."))

    # Create a new Quality Inspection (QI) document
    qi_doc = frappe.new_doc("Quality Inspection")
    qi_doc.work_order = job_card.work_order
    #     qi_doc.custom_qi_items = (
    #         custom_qi_items  # Add the list of items requiring inspection
    #     )
    qi_doc.inspection_type = "In Process"
    qi_doc.reference_type = "Job Card"
    qi_doc.reference_name = job_card.name
    qi_doc.item_code = job_card.production_item
    qi_doc.inspected_by = frappe.session.user
    qi_doc.sample_size = "1"
    qi_doc.custom_work_order = job_card.work_order
    for qi_item in custom_qi_items:
        qi_doc.append("custom_qi_items", qi_item)
    qi_doc.insert()

    # Return the created document's name
    return qi_doc.name
