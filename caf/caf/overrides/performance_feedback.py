"""
CAF Appraisal - the standing-feedback query behind the form widget
==================================================================
Purpose : Replaces stock get_feedback_history(), which is scoped to ONE
          appraisal, with a query by employee + date window - because under
          D60 an EPF is a standing note about a person, not a comment on a
          single appraisal.
Doctype : Employee Performance Feedback (read only)  |  called from appraisal.js
Reads   : HR Settings (caf_feedback_window_months, caf_show_feedback_author)
Plan ref: CAF_appraisal_implementation_plan.md 4.10, D60/D61/D62/D65;
          build_brief_chunk3.md 4.3

Why not the stock method
------------------------
hrms.hr.doctype.appraisal.appraisal.get_feedback_history(employee, appraisal)
filters on `appraisal`, so it can only ever show feedback someone deliberately
attached to that one document. D60 made the link optional precisely so a
colleague can record something about Ali today without waiting for Ali's next
appraisal to exist. Those unlinked notes are invisible to the stock widget.

D61 - the window. Without one, feedback written in 2026 would still surface on a
2028 appraisal. The window ends at the CYCLE's end date, not today, so reopening
an old appraisal shows what was visible when it was written rather than
everything since.

D62 - the author is shown, behind a single flag so masking later is a config
change rather than a rewrite. HR Manager always sees the author.
⚠️ This is not anonymity and must never be described as such: `reviewer` is
reqd=1 and `owner` is always stored, so System Manager or DB access reveals it.

D65 - an unlinked EPF has no rating criteria and total_score 0 by stock design,
so the widget hides the ratings block for those rather than rendering an empty
grid.

Changelog
---------
1.0  2026-08-05  Initial - Chunk 3
"""

import frappe
from frappe.utils import add_months, cint, getdate, nowdate

DEFAULT_WINDOW_MONTHS = 12


def _window_months():
    value = cint(frappe.db.get_single_value("HR Settings", "caf_feedback_window_months"))
    return value if value > 0 else DEFAULT_WINDOW_MONTHS


def _show_author():
    value = frappe.db.get_single_value("HR Settings", "caf_show_feedback_author")
    # unset on a fresh site means "not configured yet" - default to showing,
    # which is the D62 position
    return True if value is None else bool(cint(value))


def _may_see_author():
    return _show_author() or "HR Manager" in frappe.get_roles()


@frappe.whitelist()
def get_caf_feedback_history(employee, appraisal=None, end_date=None, window_months=None):
    """Standing feedback for `employee` within the window ending at `end_date`.

    `appraisal` is optional and used only to mark which entries are linked to
    THIS appraisal, so the form can distinguish "feedback about Ali" from
    "feedback filed against this appraisal" (the two flavours of D65).
    """
    if not employee:
        return {"feedback": [], "window": None, "show_author": _may_see_author()}

    # a supervisor may only look at people inside their own subtree - the same
    # rule the Appraisal list uses, so the widget cannot become a side channel
    from caf.caf.overrides.appraisal import get_visible_employees, is_hr_manager

    if not is_hr_manager() and employee not in (get_visible_employees() or []):
        frappe.throw(
            frappe._("You are not permitted to view feedback for this employee."),
            frappe.PermissionError,
        )

    months = cint(window_months) or _window_months()
    window_end = getdate(end_date or nowdate())
    window_start = getdate(add_months(window_end, -months))

    rows = frappe.get_all(
        "Employee Performance Feedback",
        filters={
            "employee": employee,
            "docstatus": 1,
            "added_on": ["between", [window_start, window_end]],
        },
        fields=[
            "name",
            "feedback",
            "reviewer",
            "reviewer_name",
            "reviewer_designation",
            "added_on",
            "total_score",
            "appraisal",
            "owner",
        ],
        order_by="added_on desc",
    )

    show_author = _may_see_author()
    for row in rows:
        # an EPF with no appraisal link carries no rating criteria and scores 0
        # by stock design (D65) - the form uses this to hide the ratings block
        row["is_standing"] = not row.get("appraisal")
        row["linked_to_this"] = bool(appraisal) and row.get("appraisal") == appraisal
        if not show_author:
            row["reviewer"] = None
            row["reviewer_name"] = frappe._("Hidden")
            row["reviewer_designation"] = None
            row["owner"] = None

    return {
        "feedback": rows,
        "count": len(rows),
        "window": {
            "from": str(window_start),
            "to": str(window_end),
            "months": months,
        },
        "show_author": show_author,
    }
