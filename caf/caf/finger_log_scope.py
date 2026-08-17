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

from caf.caf.overrides.appraisal import get_employee_for_user, is_hr_manager


def _own_employee(user):
    return get_employee_for_user(user)


def has_permission(doc, ptype=None, user=None, **kwargs):
    """Per-document check (read only). Returns False, never raises - a refusal
    from here leaves no app frame in the traceback (same quirk as the Appraisal
    and Leave Application hooks)."""
    user = user or frappe.session.user
    if user == "Administrator" or is_hr_manager(user):
        return True

    if ptype != "read":
        return False

    own = _own_employee(user)
    employee = getattr(doc, "employee", None)
    if not own or not employee:
        return False
    return employee == own


def get_permission_query_conditions(user=None):
    """List layer. HR/Administrator see all; everyone else sees their own rows."""
    user = user or frappe.session.user
    if user == "Administrator" or is_hr_manager(user):
        return ""

    own = _own_employee(user)
    if not own:
        # No linked Employee -> nothing. An empty IN () would be a SQL syntax
        # error, so emit a condition that is simply always false.
        return "1=0"

    return "`tabFinger Log`.`employee` = {0}".format(frappe.db.escape(own))
