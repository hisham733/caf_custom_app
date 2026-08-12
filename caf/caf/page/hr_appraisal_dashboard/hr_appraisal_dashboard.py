"""
CAF Appraisal - HR dashboard backend
=====================================
Purpose : Server-side statistics for the appraisal dashboard Page. Three
          panels: data health (T38), monthly progress, and the action queue.
Doctype : Page hr_appraisal_dashboard  |  reads Appraisal, Appraisal Cycle,
          Appraisee, Employee
Plan ref: CAF_appraisal_implementation_plan.md 6, D6/D13/D52/D73;
          build_brief_chunk3.md 4.2

Design notes
------------
* All aggregation is SQL GROUP BY, never client-side (protocol section 9).
* Every figure is scoped through the SAME rule as the rest of the product:
  HR Manager sees everything, anyone else sees only their own subtree
  (D18, via get_visible_employees). A supervisor's dashboard numbers therefore
  match exactly what their Appraisal list shows them.
* Org roots are excluded from every denominator (D52). Without that, the two
  Managing Directors sit in every cycle's appraisee list, nobody can appraise
  them, and completion can never reach 100% - failing quietly, because
  complete_cycle() counts only draft Appraisals and there would be none.
* The Supervisor Performance panel is DEFERRED (D73) and deliberately absent.

Changelog
---------
1.0  2026-08-05  Initial - Chunk 3
"""

import frappe
from frappe import _
from frappe.utils import cint, strip_html

from caf.caf.overrides.appraisal import (
    get_employee_for_user,
    get_visible_employees,
    is_hr_manager,
)

STATE_DRAFT = "Draft"
STATE_PENDING = "Pending HR Review"
STATE_COMPLETED = "Completed"


def _scope():
    """Return (is_hr, employees) - the employee names this user may count.

    `employees` is None for HR Manager, meaning "no filter". For anyone else it
    is their subtree, which may legitimately be empty for a leaf employee.
    """
    if is_hr_manager():
        return True, None
    return False, get_visible_employees() or []


@frappe.whitelist()
def get_data_health():
    """Panel 0 - what the stock org chart cannot tell you (T38).

    The org chart itself is a deep link to /app/organizational-chart: HRMS
    already renders the reports_to tree and shows both CAF roots side by side,
    so CAF does not build a tree renderer (DR11).
    """
    frappe.only_for(["HR Manager", "System Manager"])

    roots = frappe.get_all(
        "Employee",
        filters={"status": "Active", "reports_to": ["in", ["", None]]},
        fields=["name", "employee_name", "caf_reports_to_nobody"],
        order_by="name",
    )

    # the rule ensure_reports_to enforces on save - but data predating it, or
    # written by a script with ignore_permissions, can still violate it
    unflagged = [r for r in roots if not r.caf_reports_to_nobody]

    # has_permission resolves session user -> Employee through user_id. A blank
    # one makes every permission check fail CLOSED, so the person silently sees
    # nothing rather than getting an error.
    no_user_id = frappe.get_all(
        "Employee",
        filters={"status": "Active", "user_id": ["in", ["", None]]},
        fields=["name", "employee_name"],
        order_by="name",
    )

    # A missing user_id only bites people who SUPERVISE someone - they cannot be
    # resolved as the acting user, so their direct reports can be appraised by
    # nobody but HR Manager.
    #
    # Two cases, and conflating them cries wolf:
    #  * an ORG ROOT without a login may be deliberate (CAF's Directors have no
    #    ERP account by design) - but their reports still need appraising, so it
    #    is worth surfacing as information rather than as a fault
    #  * an ordinary supervisor without a login is always a defect
    report_counts = {}
    for r in frappe.get_all(
        "Employee", filters={"status": "Active"}, fields=["reports_to"]
    ):
        if r.reports_to:
            report_counts[r.reports_to] = report_counts.get(r.reports_to, 0) + 1

    root_names = {r.name for r in roots}
    blocked_supervisors, roots_without_login = [], []
    for e in no_user_id:
        count = report_counts.get(e.name, 0)
        if not count:
            continue
        entry = dict(e, direct_reports=count)
        (roots_without_login if e.name in root_names else blocked_supervisors).append(entry)

    no_shift = frappe.get_all(
        "Employee",
        filters={"status": "Active", "caf_reports_to_nobody": 0},
        or_filters=[["default_shift", "is", "not set"]],
        fields=["name", "employee_name"],
        order_by="name",
    )

    return {
        "root_count": len(roots),
        "root_expected": 2,
        "roots": roots,
        "roots_unflagged": unflagged,
        "no_user_id": no_user_id,
        "blocked_supervisors": blocked_supervisors,
        "roots_without_login": roots_without_login,
        "no_default_shift": no_shift,
        "org_chart_route": "/app/organizational-chart",
    }


@frappe.whitelist()
def get_monthly_progress(year=None):
    """Panel 1 - per cycle: appraisees, created, pending review, completed, %."""
    year = cint(year) or frappe.utils.nowdate()[:4]
    is_hr, employees = _scope()

    cycles = frappe.get_all(
        "Appraisal Cycle",
        filters={"cycle_name": ["like", "%s-%%" % year]},
        fields=["name", "cycle_name", "start_date", "end_date", "status"],
        order_by="cycle_name",
    )
    if not cycles:
        return {"year": year, "cycles": [], "scope": "all" if is_hr else "subtree"}

    names = [c.name for c in cycles]

    # --- denominator: appraisees, minus org roots (D52) -------------------
    appraisee_rows = frappe.db.sql(
        """
        SELECT a.parent AS cycle, a.employee
        FROM `tabAppraisee` a
        INNER JOIN `tabEmployee` e ON e.name = a.employee
        WHERE a.parent IN %(cycles)s
          AND IFNULL(e.caf_reports_to_nobody, 0) = 0
        """,
        {"cycles": names},
        as_dict=True,
    )

    # --- numerators: appraisals grouped by cycle and state ----------------
    appraisal_rows = frappe.db.sql(
        """
        SELECT appraisal_cycle AS cycle, workflow_state AS state,
               COUNT(*) AS n, employee
        FROM `tabAppraisal`
        WHERE appraisal_cycle IN %(cycles)s AND docstatus != 2
        GROUP BY appraisal_cycle, workflow_state, employee
        """,
        {"cycles": names},
        as_dict=True,
    )

    def visible(employee):
        return is_hr or employee in employees

    out = []
    for cycle in cycles:
        appraisees = {r.employee for r in appraisee_rows if r.cycle == cycle.name and visible(r.employee)}
        rows = [r for r in appraisal_rows if r.cycle == cycle.name and visible(r.employee)]

        created = sum(r.n for r in rows)
        pending = sum(r.n for r in rows if r.state == STATE_PENDING)
        completed = sum(r.n for r in rows if r.state == STATE_COMPLETED)
        draft = sum(r.n for r in rows if r.state == STATE_DRAFT)

        total = len(appraisees)
        out.append(
            {
                "cycle": cycle.name,
                "start_date": cycle.start_date,
                "end_date": cycle.end_date,
                "status": cycle.status,
                "appraisees": total,
                "created": created,
                "draft": draft,
                "pending_review": pending,
                "completed": completed,
                "completion_pct": round(completed * 100.0 / total, 1) if total else 0.0,
            }
        )

    return {"year": year, "cycles": out, "scope": "all" if is_hr else "subtree"}


@frappe.whitelist()
def get_action_queue():
    """Panel 2 - what needs someone's attention right now.

    HR Manager: everything sitting in Pending HR Review.
    Supervisor: their own appraisees - both what HR sent back (Draft) and what
    is still awaiting review, so they can see where each one stands.
    """
    is_hr, employees = _scope()

    conditions = ["a.docstatus != 2"]
    params = {}

    if is_hr:
        conditions.append("a.workflow_state = %(pending)s")
        params["pending"] = STATE_PENDING
    else:
        if not employees:
            return {"rows": [], "scope": "subtree"}
        conditions.append("a.employee IN %(employees)s")
        conditions.append("a.workflow_state IN %(states)s")
        params["employees"] = employees
        params["states"] = (STATE_DRAFT, STATE_PENDING)

    rows = frappe.db.sql(
        """
        SELECT a.name, a.employee, a.employee_name, a.appraisal_cycle,
               a.workflow_state, a.reported_by, a.creation, a.modified,
               sup.employee_name AS supervisor_name,
               (SELECT COUNT(*) FROM `tabComment` c
                 WHERE c.reference_doctype = 'Appraisal'
                   AND c.reference_name = a.name
                   AND c.comment_type = 'Comment') AS comment_count
        FROM `tabAppraisal` a
        LEFT JOIN `tabEmployee` sup ON sup.name = a.reported_by
        WHERE {conditions}
        ORDER BY a.appraisal_cycle DESC, a.modified ASC
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )

    return {"rows": rows, "scope": "all" if is_hr else "subtree"}


@frappe.whitelist()
def get_refreshed_after_submit(limit=25):
    """Panel 3 — appraisals whose numbers MOVED after they were submitted. OD-64.

    🔴 WHY THIS PANEL EXISTS
    ------------------------
    The monthly-progress panel counts a submitted appraisal as **done**, and since
    OD-44 and OD-60 that is no longer true: a late Leave Application or a late
    Shift Assignment rewrites the auto-filled cells of a SUBMITTED appraisal, in
    either direction. So a number can move on a document HR considers closed, and
    without this nobody is told.

    The data already exists — `refresh_submitted_appraisal()` writes an
    `add_comment` trail on every change (OD-26), because `db_set` writes no
    Version and a silent edit to a document that feeds pay is an audit hole. This
    panel reads that trail rather than adding a field.

    ⚠️ It keys on the string `OD-44`, which sits inside a translatable message. On
    a translated site the marker could move; the code reference is the most stable
    part of it, and `Version` rows are the fallback if that ever bites.
    """
    is_hr, employees = _scope()

    conditions = ["a.docstatus = 1", "c.reference_doctype = 'Appraisal'",
                  "c.comment_type = 'Comment'", "c.content LIKE '%%OD-44%%'"]
    params = {"limit": cint(limit) or 25}

    if not is_hr:
        if not employees:
            return {"rows": [], "scope": "subtree"}
        conditions.append("a.employee IN %(employees)s")
        params["employees"] = employees

    rows = frappe.db.sql(
        """
        SELECT a.name, a.employee, a.employee_name, a.appraisal_cycle,
               a.workflow_state,
               COUNT(c.name) AS refresh_count,
               MAX(c.creation) AS last_refreshed
        FROM `tabAppraisal` a
        INNER JOIN `tabComment` c ON c.reference_name = a.name
        WHERE {conditions}
        GROUP BY a.name, a.employee, a.employee_name, a.appraisal_cycle,
                 a.workflow_state
        ORDER BY last_refreshed DESC
        LIMIT %(limit)s
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )

    # The newest comment for each, so the panel can say WHAT moved and WHY without
    # a second round trip. Read per row rather than joined — one appraisal may
    # carry many, and picking the latest in SQL costs more than it saves at this
    # size.
    for r in rows:
        latest = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Appraisal", "reference_name": r.name,
                     "comment_type": "Comment", "content": ("like", "%OD-44%")},
            fields=["content", "creation", "owner"],
            order_by="creation desc", limit=1,
        )
        r["detail"] = strip_html(latest[0].content or "").strip() if latest else ""
        r["last_by"] = latest[0].owner if latest else None

    return {"rows": rows, "scope": "all" if is_hr else "subtree"}


@frappe.whitelist()
def get_hr_review_flags(limit=50):
    """Panel 4 — Finger Logs Chunk 4 flagged for a human. OD-64.

    `caf_hr_review` is raised when a re-resolve leaves OT that its approval no
    longer covers — the background job must not throw (scenario S3, one bad row
    would abort the whole batch), so it flags instead. Nothing surfaced those
    flags, which made the flag a place data went to be forgotten.

    ⚠️ HR Manager only, like `get_data_health`: Finger Log is restricted to
    HR Manager and System Manager (D40), and these rows carry OT figures.
    """
    frappe.only_for(["HR Manager", "System Manager"])

    rows = frappe.get_all(
        "Finger Log",
        filters={"caf_hr_review": 1, "docstatus": ("<", 2)},
        fields=["name", "employee", "employee_name", "work_date", "shift_type",
                "day_type", "final_ot", "ot_approval_id", "caf_hr_review_note",
                "docstatus"],
        order_by="work_date desc",
        limit_page_length=cint(limit) or 50,
    )
    total = frappe.db.count("Finger Log", {"caf_hr_review": 1, "docstatus": ("<", 2)})
    return {"rows": rows, "total": total, "shown": len(rows)}


@frappe.whitelist()
def get_dashboard():
    """One round trip for the whole page."""
    payload = {
        "is_hr_manager": is_hr_manager(),
        "employee": get_employee_for_user(),
        "monthly": get_monthly_progress(),
        "queue": get_action_queue(),
        # OD-64. Visible to a supervisor too, scoped to their own subtree — if a
        # number moved on an appraisal they wrote, they are the person who would
        # notice it is wrong.
        "refreshed": get_refreshed_after_submit(),
    }
    if payload["is_hr_manager"]:
        payload["health"] = get_data_health()
        payload["hr_review"] = get_hr_review_flags()
    return payload
