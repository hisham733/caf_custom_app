"""Finger Log scoped read — fix session 2026-08-15, decision D-1 / AC-1.

Purpose : give Employee READ access to Finger Log, scoped server-side to their
          own rows. HR Manager and Administrator see everything (write/create/
          submit are unchanged - role table still blocks those for Employee).
Hooks   : permission_query_conditions["Finger Log"]
          has_permission["Finger Log"]
Refs    : FIX_DECISION_LOG.md D-1, D-6, AC-1 · TESTING_ISSUES_LOG issue 1 (OD-63)

WHY THIS EXISTS
---------------
The desk report path checks `has_permission(ref_doctype, "report")`
(query_report.py:57). "My Attendance" reads Finger Log, and employees hold zero
permissions there - so the self-service report died with a 403 (OD-63).
MG's chosen fix (option d): employees stop using the report; the /app/finger-log
list + calendar becomes their surface, with READ scoped to their own rows.

F-1: Finger Log.employee is a Data field (D-6 converts it to Link). Frappe's
User Permission match-filters only apply to Link fields, so this module is the
enforcement, not a nicety - the same shape the Appraisal (D18) and Leave
Application (OD-82) permission layers already use.

AC-1 (MG's hard condition): if an employee can see anything but their own rows,
the whole option-(d) decision is cancelled. The test suite asserts:
  - list / calendar -> own rows only
  - GET of a colleague's row by name -> 403
  - HR Manager -> all rows, unchanged
"""

import frappe
from frappe import _
from frappe.utils import getdate

from caf.caf.overrides.appraisal import get_employee_for_user, is_hr_manager

PINK_ABSENT = "#f8d7da"
PLAIN = "#ffffff"


def refresh_appraisal_on_submit(doc, method=None):
    """D-15 (2026-08-15) — a Finger Log correction reaches the appraisal like
    the leave / Shift Assignment triggers. Skipped during the importer batch:
    thousands of rows per run must not refresh per row
    (`frappe.flags.in_import`, set by ingress_import.run)."""
    if frappe.flags.in_import:
        return
    from caf.caf.appraisal_refresh import refresh_for
    refresh_for(doc.employee, doc.work_date, doc.work_date,
                reason=_("Finger Log {0} submitted").format(doc.name),
                trigger=("Finger Log", doc.name))


def refresh_appraisal_on_cancel(doc, method=None):
    """D-15 — the cancel direction. The importer never cancels; the flag check
    is belt-and-braces."""
    if frappe.flags.in_import:
        return
    from caf.caf.appraisal_refresh import refresh_for
    refresh_for(doc.employee, doc.work_date, doc.work_date,
                reason=_("Finger Log {0} cancelled").format(doc.name),
                trigger=("Finger Log", doc.name))


def _hhmm(value):
    """A punch as HH:MM; an all-zero punch renders as nothing (OD-49)."""
    if not value:
        return ""
    text = str(value)
    if text.startswith("0:00:00") or text.startswith("00:00:00"):
        return ""
    parts = text.split(":")
    return "{0:02d}:{1}".format(int(parts[0]), parts[1]) if len(parts) >= 2 else text


@frappe.whitelist()
def get_employee_events(doctype, start, end, fields=None, filters=None, field_map=None):
    """Calendar events for the Finger Log calendar view — D-5 / D-7 / AC-1.

    The STATUS column (the Attendance verdict) comes from a server-side join:
    employees never read Attendance itself, and leave_type (MC) is never
    selected. Rows are scoped by the CALLER's identity, never by a
    client-supplied filter — employees get their own rows only (AC-1).
    """
    user = frappe.session.user
    conditions = ["fl.docstatus < 2"]
    values = {}

    if user == "Administrator" or is_hr_manager(user):
        emp = (filters or {}).get("employee")
        if emp:
            conditions.append("fl.employee = %(employee)s")
            values["employee"] = emp
    else:
        own = _own_employees(user)
        if not own:
            return []
        conditions.append("fl.employee in ({0})".format(
            ", ".join(frappe.db.escape(e) for e in own)))

    if start:
        conditions.append("fl.work_date >= %(start)s")
        values["start"] = getdate(start)
    if end:
        conditions.append("fl.work_date <= %(end)s")
        values["end"] = getdate(end)

    rows = frappe.db.sql("""
        SELECT fl.name, fl.employee, fl.work_date, fl.day_type, fl.shift_type,
               fl.time_in, fl.`break`, fl.resume, fl.`out`, fl.final_ot,
               fl.docstatus, att.status
          FROM `tabFinger Log` fl
          LEFT JOIN `tabAttendance` att
                 ON att.employee = fl.employee
                AND att.attendance_date = fl.work_date
                AND att.docstatus = 1
         WHERE {conditions}
      ORDER BY fl.work_date
    """.format(conditions=" AND ".join(conditions)), values, as_dict=True)

    events = []
    for r in rows:
        t_in, t_out = _hhmm(r.time_in), _hhmm(r.get("out"))
        l_out, l_in = _hhmm(r.get("break")), _hhmm(r.resume)
        punches = " · ".join(p for p in (
            "{0}–{1}".format(t_in, t_out) if (t_in or t_out) else "",
            "L{0}–{1}".format(l_out, l_in) if (l_out or l_in) else "",
        ) if p)
        label = "DRAFT" if r.docstatus == 0 else "SUBMITTED"
        status = r.status or ""
        title = " · ".join(x for x in (label, status, punches) if x)
        tooltip = (
            "{0} · {1} · {2} · {3}\n"
            "in {4} · lunch {5}–{6} · out {7}\n"
            "final OT {8} · {9}"
        ).format(
            r.work_date, r.day_type or "", r.shift_type or "", label,
            _hhmm(r.time_in) or "-", _hhmm(r.get("break")) or "-",
            _hhmm(r.resume) or "-", _hhmm(r.get("out")) or "-",
            r.final_ot or 0, r.name,
        )
        events.append({
            "name": r.name,
            "start": r.work_date,
            "end": r.work_date,
            "allDay": 1,
            "title": title,
            "tooltip": tooltip,
            "color": PINK_ABSENT if status == "Absent" else PLAIN,
            "doctype": "Finger Log",
        })
    return events


def _own_employee(user):
    return get_employee_for_user(user)


def _own_employees(user):
    """The Employee records this user may read: their user_id-linked record plus
    any `Employee` User Permission rows — the same two conventions the site
    already uses to scope Attendance (prod links user_id; the fixture users are
    linked by User Permission rows, verified live)."""
    linked = get_employee_for_user(user)
    up = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Employee"},
        pluck="for_value",
    )
    own = {e for e in [linked] + up if e}
    return sorted(own)


def has_permission(doc, ptype=None, user=None, **kwargs):
    """Per-document check (read only). Returns False, never raises - a refusal
    from here leaves no app frame in the traceback (same quirk as the Appraisal
    and Leave Application hooks)."""
    user = user or frappe.session.user
    if user == "Administrator" or is_hr_manager(user):
        return True

    if ptype != "read":
        return False

    employee = getattr(doc, "employee", None)
    if not employee:
        return False
    return employee in _own_employees(user)


def get_permission_query_conditions(user=None):
    """List layer. HR/Administrator see all; everyone else sees their own rows."""
    user = user or frappe.session.user
    if user == "Administrator" or is_hr_manager(user):
        return ""

    own = _own_employees(user)
    if not own:
        # No linked Employee and no Employee User Permission -> nothing. An empty
        # IN () would be a SQL syntax error, so emit a condition that is simply
        # always false.
        return "1=0"

    return "`tabFinger Log`.`employee` in ({0})".format(
        ", ".join(frappe.db.escape(e) for e in own)
    )
