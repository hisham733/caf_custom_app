"""Every day still waiting on a human — in one place, always current.

MG's proposal, 2026-09-02: *"currently only visible at the respective Ingress
Import Batch manifest… propose a report for HR Manager that collates all these
blocks."*

🔴 WHY THE MANIFEST CANNOT ANSWER THIS
--------------------------------------
An `Ingress Import Batch` manifest is a **historical record of one run**. Its rows
never change — submit the log a week later and the row still says `Held`. So the
manifest answers *"what happened during that import"* and can never answer
*"what is still outstanding"*, which is the question HR actually has. Verified for
MG on 2026-09-02.

Before this there were **three** partial views and no whole one:

    each batch's manifest      that run's held rows, frozen, found only by opening it
    Finger Log list            filter caf_not_full_day = 1 — no reason, no document
    HR Appraisal Dashboard     caf_hr_review = 1 — collated, but a DIFFERENT set

WHAT THIS COLLECTS, AND WHY BOTH KINDS
--------------------------------------
Two populations, both of which need a person and neither of which the other view
shows:

    HELD     docstatus = 0 — never became a verdict. Incomplete punches, OT with
             no approval, a leave clash. The day is not decided.
    FLAGGED  caf_hr_review = 1 — already SUBMITTED, then a re-resolve found its OT
             no longer matches its approval. The day is decided and now disputed.

They are one question to HR — *"what do I still have to deal with?"* — so they are
one report. The dashboard panel keeps the flagged half as a summary; this is the
worklist.

⚠️ **The reason is derived LIVE, not read from a stored field.** `_missing` is
recomputed from the punches and the shift's `caf_required_punches`, so a day that
stopped being blocked (because HR fixed a punch, or the shift's rule changed —
FBR55) simply leaves the report. A stored reason would go stale exactly when it
mattered.

HR Manager only: Finger Log is restricted to HR Manager and System Manager (D40),
and these rows carry OT figures.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, nowdate

from caf.caf import work_hours
from caf.caf.shift_resolution import get_shift_params


def execute(filters=None):
    frappe.only_for(["HR Manager", "System Manager"])
    filters = frappe._dict(filters or {})
    return _columns(), _rows(filters)


def _columns():
    return [
        # 🔴 The first column, because it splits the list into two different jobs.
        # Without it the report says "566 outstanding" when only ~400 need a
        # decision and the rest need a click — and a worklist that overstates
        # itself is one people stop opening.
        {"label": _("Status"), "fieldname": "status",
         "fieldtype": "Data", "width": 95},
        {"label": _("Work Date"), "fieldname": "work_date",
         "fieldtype": "Date", "width": 95},
        {"label": _("Employee"), "fieldname": "employee_name",
         "fieldtype": "Data", "width": 190},
        {"label": _("Waiting"), "fieldname": "age",
         "fieldtype": "Data", "width": 80},
        {"label": _("Why"), "fieldname": "why",
         "fieldtype": "Data", "width": 260},
        # 🔴 The column the manifest cannot give: the document that has to change
        # before this day can move. A Dynamic Link so one column can point at an
        # OT Approval or a Leave Application, whichever is blocking.
        {"label": _("Blocked by"), "fieldname": "blocker",
         "fieldtype": "Dynamic Link", "options": "blocker_type", "width": 175},
        {"label": _("Type"), "fieldname": "blocker_type",
         "fieldtype": "Data", "width": 1, "hidden": 1},
        {"label": _("Finger Log"), "fieldname": "finger_log",
         "fieldtype": "Link", "options": "Finger Log", "width": 150},
        {"label": _("Shift"), "fieldname": "shift_type",
         "fieldtype": "Link", "options": "Shift Type", "width": 150},
        {"label": _("OT (h)"), "fieldname": "ot_in_hour",
         "fieldtype": "Float", "width": 70, "precision": 2},
    ]


def _leave_on(employee, day):
    rows = frappe.get_all(
        "Leave Application",
        filters={"employee": employee, "docstatus": 1,
                 "from_date": ("<=", day), "to_date": (">=", day)},
        fields=["name", "leave_type"], limit=1)
    return rows[0] if rows else None


BLOCKED = "🔴 Blocked"
FLAGGED = "🟠 Flagged"
READY = "✅ Ready"


def _why(log):
    """(status, reason, blocking doctype, blocking name) — computed, never stored.

    The order matters: it reports the FIRST thing that must change, because that
    is what HR would act on. A day with both a missing punch and unapproved OT
    cannot be submitted until the punch is fixed, so saying "OT not approved"
    would send them to the wrong document.

    🔴 The three statuses are three different jobs, and conflating them was the
    first version's mistake:

      Blocked  something must CHANGE before this day can become a verdict
      Flagged  already submitted, and a re-resolve since found its OT disputed
      Ready    nothing is blocking it — it only needs submitting

    `Ready` is not noise: 157 days became submittable the moment the punch-rule
    shifts went in (FBR55), and every one of them is still a draft because
    nothing submits a draft automatically.
    """
    params = get_shift_params(log.shift_type)
    missing = work_hours.missing_punches(log, params)
    if missing:
        return BLOCKED, _("missing {0}").format(", ".join(missing)), None, None

    leave = _leave_on(log.employee, log.work_date)
    if leave:
        return (BLOCKED,
                _("approved leave that day ({0})").format(leave.leave_type),
                "Leave Application", leave.name)

    if log.ot_in_hour:
        row = frappe.get_all(
            "OT Approval Table",
            filters={"emp_id": log.employee, "work_date": log.work_date,
                     "docstatus": 1},
            fields=["parent", "ot_duration"], order_by="creation desc", limit=1)
        if not row:
            return (BLOCKED,
                    _("{0} h of OT with no approval").format(log.ot_in_hour),
                    None, None)
        approved = row[0].ot_duration
        parent = row[0].parent
        if log.ot_in_hour > approved:
            return (BLOCKED, _("{0} h of OT, only {1} h approved").format(
                log.ot_in_hour, approved), "OT Approval", parent)
        if frappe.db.get_value("OT Approval", parent, "docstatus") != 1:
            return BLOCKED, _("OT approval not submitted"), "OT Approval", parent

    if log.caf_hr_review:
        return (FLAGGED, log.caf_hr_review_note or _("flagged for review"),
                "OT Approval", log.ot_approval_id or None)

    return READY, _("nothing blocking — needs submitting"), None, None


def _rows(filters):
    conditions = {"docstatus": ("<", 2)}
    if filters.get("employee"):
        conditions["employee"] = filters.employee

    logs = frappe.get_all(
        "Finger Log",
        filters=conditions,
        or_filters=[["caf_not_full_day", "=", 1], ["caf_hr_review", "=", 1],
                    ["docstatus", "=", 0]],
        fields=["name", "employee", "employee_name", "work_date", "shift_type",
                "day_type", "ot_in_hour", "caf_hr_review", "caf_hr_review_note",
                "caf_not_full_day", "docstatus",
                "time_in", "`break`", "resume", "`out`"],
        order_by="work_date asc",
        limit_page_length=0)

    today = getdate(nowdate())
    out = []
    for log in logs:
        status, why, blocker_type, blocker = _why(log)
        if filters.get("status") and status != filters.status:
            continue
        days = date_diff(today, getdate(log.work_date))
        out.append({
            "status": status,
            "work_date": log.work_date,
            "employee_name": log.employee_name,
            "age": _("{0} days").format(days) if days else _("today"),
            "why": why,
            "blocker": blocker,
            "blocker_type": blocker_type,
            "finger_log": log.name,
            "shift_type": log.shift_type,
            "ot_in_hour": log.ot_in_hour,
        })
    return out
