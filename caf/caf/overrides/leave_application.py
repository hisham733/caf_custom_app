"""OD-82 — scope leave approval to the RIGHT approver. Chunk 6b.

Purpose : make `Employee.leave_approver` decide AUTHORITY, not just routing.
Hooks   : has_permission["Leave Application"]
          permission_query_conditions["Leave Application"]
Refs    : framework §6.16 · OD-82 · OD-76 · spec §4

WHY THIS EXISTS — measured, not assumed
---------------------------------------
MG asked the question that found it: *"A approves for B, C approves for D — can
A approve leave for C?"*

**Measured live: YES.** `production.p.caf@gmail.com`, who is not Ow Yong Mian
Fatt's approver, read, wrote and **submitted** his leave application. Three
reasons, all verified:

    hrms has NO validate_leave_approver method
    Leave Application had NO permission_query_conditions and NO has_permission
    the `Leave Approver` role grants blanket read+write+submit at permlevel 0 AND 1

So the role is a **door**, not a lock: it says *"you may touch Leave
Applications"*, never *"you may touch THIS one"*. With 19 holders, any of them
could approve any of the other 88 employees' leave.

THE PATTERN IS ALREADY IN THIS APP — MG spotted it
---------------------------------------------------
*"I think this is solved in the report_to mechanic — note that in the appraisal
structure all emp has the same role, right."* Exactly:

    Appraisal   role `Employee` (all 117)  +  may_appraise()      -> reports_to
    Leave       role `Leave Approver` (19) +  may_handle_leave()  -> leave_approver

This module is the second half of that sentence. It is deliberately the same
shape as `caf/caf/overrides/appraisal.py` so the two read alike.

⚠️ A Workflow Transition's *Allowed* column takes a ROLE, never a person — so the
workflow cannot express "this employee's approver" by itself. The workflow draws
the button; this decides whether it works. **Both, not either.**

⚠️ AND THE LA FILES FOR THEIR REPORT (MG, practice)
In practice the Leave Approver fills in the application FOR their direct report.
So this governs `create` and `write` as well as `submit` — without it, any of the
19 could file leave in anybody's name.

Changelog
---------
1.0  2026-08-13  Chunk 6b — OD-82
"""

import frappe

HR_ROLES = ("HR Manager", "HR User")


def is_hr(user=None):
    """HR sees and does everything. Mirrors `appraisal.is_hr_manager`, widened to
    HR User because the Custom DocPerm already grants them submit + permlevel 1."""
    roles = frappe.get_roles(user or frappe.session.user)
    return any(r in roles for r in HR_ROLES)


def may_handle_leave(employee, user=None):
    """The write rule. Mirrors `appraisal.may_appraise`.

    Three ways in, and no others:
        1. HR — any HR Manager or HR User
        2. it is YOUR OWN leave
        3. you are the `leave_approver` recorded on that employee
    """
    user = user or frappe.session.user
    if user == "Administrator" or is_hr(user):
        return True
    if not employee:
        return True                     # nothing to judge yet; validate() still gates
    row = frappe.db.get_value("Employee", employee,
                              ["user_id", "leave_approver"], as_dict=True)
    if not row:
        return False
    return user in (row.user_id, row.leave_approver)


def has_permission(doc, ptype=None, user=None, **kwargs):
    """Per-document check. Registered under the `has_permission` hook, which
    `frappe.permissions` calls from `check_permission()` — BEFORE validate and
    before the DB write.

    ⚠️ It RETURNS False; it never raises. So a refusal from here leaves **no
    frame in the traceback** and reads as a pure-Frappe PermissionError. That
    cost an hour on the Appraisal side (protocol_issue_2026-08-13b §3) — if a
    leave permission failure ever looks like it comes from the framework, this
    function is the first place to look.
    """
    user = user or frappe.session.user
    return may_handle_leave(getattr(doc, "employee", None), user)


def get_permission_query_conditions(user=None):
    """Read layer / list filtering. Returns a SQL fragment.

    Without this the LIST shows every application to every Leave Approver even
    though they cannot open them — the same split between `read` and `write`
    the appraisal side solves.
    """
    user = user or frappe.session.user
    if user == "Administrator" or is_hr(user):
        return ""

    mine = frappe.get_all("Employee",
                          filters={"leave_approver": user}, pluck="name")
    own = frappe.get_all("Employee", filters={"user_id": user}, pluck="name")
    visible = sorted(set(mine) | set(own))
    if not visible:
        # An empty IN () is a SQL syntax error — emit an always-false condition
        # instead. Same fix as `appraisal.get_permission_query_conditions`.
        return "1=0"
    quoted = ", ".join(frappe.db.escape(n) for n in visible)
    return f"`tabLeave Application`.`employee` in ({quoted})"
