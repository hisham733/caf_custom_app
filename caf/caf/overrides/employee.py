"""
CAF Appraisal - Employee validation
====================================
Purpose : Enforces that every employee has a supervisor, which is what the
          whole appraisal permission layer rests on - with a per-employee
          exemption for the org roots.
Doctype : Employee (stock)  |  Hook: doc_events -> Employee.validate
Reads   : Employee.reports_to, Employee.caf_reports_to_nobody
Plan ref: CAF_appraisal_implementation_plan.md D15/D51/D53, Appendix D;
          build_brief_chunk2.md 4.3

Why the exemption exists (Appendix D, short version)
----------------------------------------------------
Employee is a NestedSet keyed on reports_to, so the org root MUST have it
empty: self-reference is blocked by stock validate_reports_to(), and pointing
the root downward raises NestedSetRecursionError. D15's original "no fallback,
everyone must have reports_to" was therefore unimplementable. An empty
reports_to already IS "reports to nobody" in Frappe - the only thing forbidding
it was CAF's own rule, so the fix is to scope our rule, not to override the
framework.

CAF has TWO org roots (two Managing Directors, D53), which means two
disconnected trees. That is intended, not a bug.

Changelog
---------
1.0  2026-08-05  Initial - Chunk 2
"""

import frappe
from frappe import _


def ensure_reports_to(doc, method=None):
    """Throw when reports_to is empty unless the org-root checkbox is ticked."""
    if doc.get("reports_to"):
        return

    if doc.get("caf_reports_to_nobody"):
        return

    frappe.throw(
        _(
            "{0} must have a value in <b>Reports To</b>. Every employee is appraised by their "
            "supervisor, and that link is what decides who may appraise whom.<br><br>"
            "If this person genuinely reports to nobody (a company director), tick "
            "<b>Reports To Nobody (Org Root)</b> instead."
        ).format(frappe.bold(doc.get("employee_name") or doc.get("name") or _("This employee"))),
        title=_("Supervisor required"),
    )
