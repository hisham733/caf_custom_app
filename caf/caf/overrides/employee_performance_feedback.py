"""
CAF Appraisal - Employee Performance Feedback override
=======================================================
Purpose : Turns stock EPF into a STANDING feedback log - an ongoing record
          about a person that anyone may file at any time - and stops feedback
          changing an appraisal HR has already approved.
Doctype : Employee Performance Feedback (stock, extended)
          Hook: override_doctype_class
Reads   : Appraisal.workflow_state
Plan ref: CAF_appraisal_implementation_plan.md D60/D64/D65;
          build_brief_chunk2.md 4.5

Two changes, both required for reasons verified in source
----------------------------------------------------------
1. D60 - skip validate_appraisal() when the link is empty.
   Stock (employee_performance_feedback.py:40-46) has NO empty-link guard:

       employee = frappe.db.get_value("Appraisal", self.appraisal, "employee")
       if employee != self.employee: frappe.throw(...)

   With `appraisal` empty that reads None, which never equals self.employee, so
   it throws "Appraisal None does not belong to Employee X". Confirmed live
   during the chunk 1 build: making the field optional by Property Setter alone
   leaves EPF completely unsaveable. Its sibling methods
   update_avg_feedback_score_in_appraisal() and set_feedback_criteria() DO guard
   correctly (lines 57 and 65) - only this one is missing it.

2. D64 - refuse to submit against an appraisal already Completed.
   EPF.on_submit -> update_avg_feedback_score_in_appraisal() ->
   calculate_avg_feedback_score(update=True) -> db_update(), a raw UPDATE that
   bypasses permission checks, the docstatus lock, validate(), on_update hooks
   AND version history. Net effect without this: an HR-approved appraisal's
   score can change afterwards, silently, with nothing on the timeline.
   This is a CAF policy choice - "Completed means final" - not a workaround for
   an upstream bug; post-submit rollups are the normal ERPNext convention.

Note (D65, verified stock behaviour - nothing to build): an unlinked EPF gets no
rating criteria, an empty feedback_ratings table and total_score = 0, and never
enters avg_feedback_score. So standing feedback cannot move anyone's score by
design - which is also why anonymous comments carry no governance risk here.

Changelog
---------
1.0  2026-08-05  Initial - Chunk 2
"""

import frappe
from frappe import _

from hrms.hr.doctype.employee_performance_feedback.employee_performance_feedback import (
    EmployeePerformanceFeedback,
)

COMPLETED_STATE = "Completed"


class CustomEmployeePerformanceFeedback(EmployeePerformanceFeedback):
    def validate_appraisal(self):
        """D60 - an EPF with no appraisal link is a standing note about a
        person, not a comment on one appraisal. Nothing to validate."""
        if not self.appraisal:
            return
        return super().validate_appraisal()

    def validate(self):
        super().validate()
        self.validate_appraisal_not_completed()

    def validate_appraisal_not_completed(self):
        """D64 - Completed means final."""
        if not self.appraisal:
            return

        state = frappe.db.get_value("Appraisal", self.appraisal, "workflow_state")
        if state != COMPLETED_STATE:
            return

        frappe.throw(
            _(
                "Appraisal {0} has already been completed by HR. Feedback linked to it would "
                "change its score after approval, so it cannot be added or submitted now.<br><br>"
                "File this as standing feedback instead - leave the Appraisal field empty and it "
                "will surface on the next appraisal."
            ).format(frappe.bold(self.appraisal)),
            title=_("Appraisal already completed"),
        )
