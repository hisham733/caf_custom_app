"""Who Is Off — the leave board every employee can read. Chunk 7.4, OD-30 / OD-12.

    Desk: /app/query-report/Who Is Off

WHAT IT IS FOR
--------------
Two questions, and they have different audiences:

  • *Who is out, and until when?* — everybody needs this to plan a shift or a
    hand-over. That is why MG made the board visible to **every employee**.
  • *Where is my application stuck?* — spec §5 settled this one: it needs
    **`workflow_state`**, because all four pending states share `status = "Open"`
    and a status board therefore cannot say where an application is sitting.

🔴 `leave_type` IS NOT ON THE ALL-EMPLOYEE VIEW — MG's decision, 2026-08-11
--------------------------------------------------------------------------
`leave_type` names the illness: it discloses **MC**, which is health information.
A who-is-off board needs *who* and *until when*, never *why*. It is added only for
**HR Manager**, and — this is the part that matters — it is **absent from the row
dict itself**, not merely dropped from the column list. A column the front end
does not render is not a permission (PROTOCOL §C4), and a Script Report runs its
own SQL, so `permission_query_conditions` never fires either: **`execute()` is the
whole of the enforcement.** Test `C74-MC` asserts the value cannot be found
anywhere in an Employee-role caller's result, by string search over the payload
rather than by checking for a missing key.

Same rule as `My Attendance` (7.1), reached from the opposite direction: there the
sensitive thing was *whose* rows; here everyone may see every row, and the
sensitive thing is one column.

🔴 THE STAGE COLUMN, AND WHY IT IS NOT CALLED `workflow_state`
--------------------------------------------------------------
Measured on this site, 2026-08-11: **no Workflow is attached to Leave Application,
and `workflow_state` is empty on all 775 rows.** The leave workflow is Chunk 6
(spec §4, OD-27), which is blocked on HR.

Building OD-30 literally would therefore put the board's single most important
column on screen **blank on every row** — precisely the failure 7.1 hit when
`status` was left out and 380 July rows rendered as a bare date with nothing to
explain them. So `stage` reads `workflow_state` **and falls back to `status`**
while none exists. The fallback is deliberate, visible (the `.js` marks a
fallback value and says so on hover) and self-cancelling: the day Chunk 6 attaches
the workflow, every row starts showing the real state with no change here.

⚠️ It is a fallback, not an equivalence. `status = "Open"` is exactly the
undifferentiated value OD-30 exists to replace — the board cannot distinguish the
four pending states until the workflow exists, and it should not pretend to.
"""

import frappe
from frappe import _

from caf.caf.overrides.appraisal import is_hr_manager

# MG's proposed list (roadmap §9d.4), in MG's order. `leave_approver` is the email:
# `leave_approver_name` is populated on 0 of 775 rows, so showing it would have put
# a second blank column on the board.
BASE_COLUMNS = [
    ("employee_name", _("Employee"), "Data", 200),
    ("department", _("Department"), "Data", 170),
    ("from_date", _("From"), "Date", 100),
    ("to_date", _("To"), "Date", 100),
    ("total_leave_days", _("Days"), "Float", 80),
    ("stage", _("Stage"), "Data", 150),
    ("leave_approver", _("Approver"), "Data", 200),
    ("posting_date", _("Filed On"), "Date", 100),
]

# 🔴 HR Manager only. See the module docstring — this is health information.
HR_ONLY_COLUMNS = [
    ("leave_type", _("Leave Type"), "Data", 140),
]


def get_columns(hr):
    cols = list(BASE_COLUMNS) + (list(HR_ONLY_COLUMNS) if hr else [])
    return [{"fieldname": f, "label": lbl, "fieldtype": ft, "width": w}
            for f, lbl, ft, w in cols]


def execute(filters=None):
    filters = frappe._dict(filters or {})
    hr = is_hr_manager()

    # `docstatus < 2` keeps DRAFTS, and on this site that is most of the board:
    # 17 rows fall in the next 30 days and only 5 of them are submitted. A pending
    # application is the whole reason the Stage column exists — filtering to
    # `docstatus = 1` would show the answers and hide the questions.
    #
    # `status != 'Cancelled'` is a separate exclusion and cannot be folded into the
    # docstatus test: 57 rows carry `Cancelled` while still sitting at
    # `docstatus = 0`. A cancelled application is not somebody being off.
    conditions = ["la.docstatus < 2", "la.status != 'Cancelled'"]
    values = {}

    # Overlap, not containment: a leave that started in June and runs to today is
    # somebody who IS OFF, and a board that missed it would be wrong in the one way
    # that matters. Two such rows exist right now (52-day LWP spans).
    if filters.get("from_date"):
        conditions.append("la.to_date >= %(from_date)s")
        values["from_date"] = filters.from_date
    if filters.get("to_date"):
        conditions.append("la.from_date <= %(to_date)s")
        values["to_date"] = filters.to_date

    if filters.get("department"):
        conditions.append("la.department = %(department)s")
        values["department"] = filters.department

    # "Where is it stuck" — the second of the board's two questions. Once Chunk 6
    # lands the workflow this should filter on workflow_state instead; until then
    # `Open` is the only marker of "not yet decided" there is.
    if filters.get("pending_only"):
        conditions.append("la.status = 'Open'")

    rows = frappe.db.sql("""
        SELECT la.employee, la.employee_name, la.department, la.from_date, la.to_date,
               la.total_leave_days, la.workflow_state, la.status, la.leave_approver,
               la.posting_date, la.leave_type, la.docstatus
          FROM `tabLeave Application` la
         WHERE {conditions}
      ORDER BY la.from_date, la.employee_name
    """.format(conditions=" AND ".join(conditions)), values, as_dict=True)

    data = []
    for r in rows:
        # The fallback, in one place. `stage_from_status` is NOT a column — it is
        # carried on the row so the formatter can mark the value as provisional,
        # and it disappears by itself when the workflow arrives.
        workflow_state = (r.workflow_state or "").strip()
        row = {
            "employee_name": r.employee_name,
            "department": r.department,
            "from_date": r.from_date,
            "to_date": r.to_date,
            "total_leave_days": r.total_leave_days,
            "stage": workflow_state or (r.status or ""),
            "stage_from_status": 0 if workflow_state else 1,
            "leave_approver": r.leave_approver,
            "posting_date": r.posting_date,
        }
        if hr:
            row["leave_type"] = r.leave_type or ""
        data.append(row)

    return get_columns(hr), data
