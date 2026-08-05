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
        self.validate_reviewer_is_an_employee()
        super().validate()
        self.validate_appraisal_not_completed()

    def validate_reviewer_is_an_employee(self):
        """Frappe does NOT validate this Link. CAF must.

        `reviewer` is a Link to Employee, but frappe silently accepts any string
        in it - verified live: inserting reviewer="NOT-AN-EMPLOYEE-AT-ALL"
        succeeds.

        Cause, in base_document.py get_invalid_links (line 845): when a Link
        field has `fetch_from` companions - and `reviewer` has two,
        reviewer_name and reviewer_designation - the code fetches them with
            frappe.db.get_value(doctype, docname, values_to_fetch, as_dict=True)
        which returns **None** when no row matches. The very next line is
        `if values:`, so for a missing target the entire validation block is
        skipped and nothing is ever appended to invalid_links. A Link WITHOUT
        fetch_from companions takes the branch above it, which builds a truthy
        _dict(name=None) and IS caught. (Same session, opposite result:
        OT Approval.ot_department, which has no fetch_from, correctly threw
        "Could not find OT Department: Packing - CAF".)

        Why CAF cares rather than shrugging:
          * D62 displays the author on every appraisal form. Attribution that
            the framework never checked is not attribution.
          * stock validate_employee() blocks self-feedback by comparing
            `employee` to `reviewer`. With a junk reviewer that comparison can
            never match, so the self-feedback guard silently stops working.
          * reviewer_name/reviewer_designation come back empty, so the widget
            falls back to printing the raw value.
        """
        if not self.reviewer:
            return
        if frappe.db.exists("Employee", self.reviewer):
            return

        frappe.throw(
            _(
                "Reviewer {0} is not an Employee. Feedback must be attributed to an employee "
                "record, not a user or an email address."
            ).format(frappe.bold(self.reviewer)),
            title=_("Invalid reviewer"),
        )

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
