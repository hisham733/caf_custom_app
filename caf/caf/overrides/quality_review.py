import frappe
from erpnext.quality_management.doctype.quality_review.quality_review import QualityReview

class CustomQualityReview(QualityReview):
    def validate(self):
        super().validate()

    @frappe.whitelist()
    # Accept `self` as the first argument. `docname` is no longer needed.
    def update_pre_post_operation_cleaning(self, updates):
        # No need for pdb or frappe.get_doc. `self` is the document!
        updates = frappe.parse_json(updates) if isinstance(updates, str) else updates
        
        updated = False
        for row in self.reviews:
            if row.objective in updates:
                row.custom_data = updates[row.objective]
                updated = True

        if updated:
            self.save(ignore_permissions=True) # Use self.save()
            return "Updated successfully!"
        else:
            frappe.throw("No matching objective found.")

    @frappe.whitelist()
    # Do the same for your other method
    def custom_verification(self, updates):
        updates = frappe.parse_json(updates) if isinstance(updates, str) else updates
        updated = False

        for row in self.reviews:
            if row.objective in updates:
                row.custom_data = updates[row.objective]
                updated = True

        if updated:
            self.save(ignore_permissions=True)
            return "Updated successfully!"
        else:
            frappe.throw("No matching objective found.")

            
    # def set_status(self):
    #   # if any child item is failed, fail the parent
    #   if not len(self.reviews or []) or any([d.status == "Open" for d in self.reviews]):
    #         self.status = "Open"
    #   elif any([d.status == "Failed" for d in self.reviews]):
    #         self.status = "Failed"
    #   else:
    #         self.status = "Open"
