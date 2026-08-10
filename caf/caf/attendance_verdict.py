"""Finger Log ➜ Attendance — the observation becomes the company's verdict.

Chunk 3, roadmap §7. Spec §9.

  FDR4  🔴 **THE RULE THIS FILE EXISTS TO KEEP.** An observation may never be
        written as a decision. Finger Log writes `status` and NOTHING else.
        `leave_type` belongs to an approved Leave Application, always.

  OD-56 Finger Log NEVER writes `Half Day`. Every row Ingress marked as a half
        day was missing its final punch, so a half day and a forgotten tap-out
        are the SAME observation — only a human knows which. Those rows are
        `caf_not_full_day` and never reach here (OD-58). `Half Day` arrives on
        Attendance only via a Leave Application.

  So this module writes exactly two statuses: **Present** and **Absent**.
"""

import frappe
from frappe import _

from caf.caf import work_hours

PRESENT = "Present"
ABSENT = "Absent"


def should_have_attendance(doc) -> bool:
    """Does this day warrant an Attendance row at all?

    🔴 **A REST DAY IS NOT AN ABSENCE.** He was never scheduled, so there is
    nothing to record and nothing to answer for. Creating an `Absent` there is a
    false accusation, and FBR37 counts unexplained absence — so it would land on
    his appraisal.

    Measured 2026-08-10, after the appraisal was re-pointed at Attendance:
    **287 false Absents in one month, every one on a Sunday.** The creation path
    had no day_type check while `reconcile_attendance()` did, so the two
    disagreed. They now share this predicate precisely so they cannot drift.

    He punched on a rest day → that IS an Attendance. He turned up; FBR4 makes
    every hour of it OT.
    """
    return not work_hours.is_all_zero(doc) or doc.day_type == "Workday"


def verdict(doc) -> str:
    """`Absent` for the all-zero row, else `Present`.

    The all-zero row is not a gap in the data — Ingress emits one per rostered
    day whether or not anyone punched, and 3,993 of them exist. It is the
    observation that he did not come, and FBR37 counts it.
    """
    return ABSENT if work_hours.is_all_zero(doc) else PRESENT


def existing_attendance(employee: str, work_date):
    return frappe.get_all(
        "Attendance",
        filters={"employee": employee, "attendance_date": work_date,
                 "docstatus": ("<", 2)},
        fields=["name", "status", "leave_type", "docstatus"], limit=1)


def assert_no_clash(doc):
    """Refuse the submit if this day is already decided. Runs in `before_submit`.

    ⚠️ It must run BEFORE the docstatus is written. When this lived in
    `on_submit`, a refused Finger Log was left at `docstatus = 1` in the database
    while the caller saw an exception — a document both submitted and rejected.
    `before_submit` is the only place the refusal is clean.
    """
    # 🔴 An approved Leave Application with NO live Attendance row is the
    # dangerous case, and checking for the row alone does not catch it: stock's
    # check_leave_record() then SILENTLY REWRITES our `Present` to `On Leave`
    # and fills in leave_type (analysis §12.4b claim 3). Measured on the first
    # import run — 7 Attendance rows came out carrying a leave_type this module
    # never wrote, which is a straight FDR4 violation. A cancelled row is enough
    # to trigger it, because validate_duplicate_record filters docstatus < 2.
    leave = frappe.get_all(
        "Leave Application",
        filters={"employee": doc.employee, "docstatus": 1, "status": "Approved",
                 "from_date": ("<=", doc.work_date), "to_date": (">=", doc.work_date)},
        fields=["name", "leave_type"], limit=1)
    if leave:
        frappe.throw(_(
            "{0} has approved leave on {1} ({2}, {3}). A Finger Log may not overwrite "
            "an approved absence — resolve the leave application first."
        ).format(doc.employee, doc.work_date, leave[0].leave_type, leave[0].name))

    clash = existing_attendance(doc.employee, doc.work_date)
    if clash:
        row = clash[0]
        # The Leave Application got there first (§2.1 case C2). That is a real
        # contradiction between what was approved and what the clock saw — it
        # belongs in front of a human, not swallowed.
        frappe.throw(_(
            "{0} already has an Attendance record for {1} ({2}{3}). "
            "Resolve the leave application or the Finger Log before submitting."
        ).format(doc.employee, doc.work_date, row.status,
                 f" / {row.leave_type}" if row.leave_type else ""))


def create_attendance(doc):
    """Create the Attendance row for a submitted Finger Log.

    ⚠️ Deliberately NOT using stock `mark_attendance()`. It catches
    `DuplicateAttendanceError` and `OverlappingShiftAttendanceError`, rolls back
    to its own savepoint and returns **None** — the caller is told nothing
    (verified: hrms attendance.py; analysis §12.4b claim 1). A Finger Log would
    then submit happily with no Attendance for the work it observed: silent data
    loss, and the contradiction never surfaces.

    Worse, §12.4b claim 3: a `Present` insert is **silently rewritten to
    `On Leave`** by stock's `check_leave_record()` when an approved Leave
    Application exists and no live Attendance row does. So the collision has to
    be caught BEFORE the insert, not after.
    """
    # Belt and braces: before_submit already refused a clash, but this is the
    # last point before a row is written.
    if not should_have_attendance(doc):
        return None                     # a rest day nobody worked. Nothing to record.

    assert_no_clash(doc)

    att = frappe.new_doc("Attendance")
    att.employee = doc.employee
    att.attendance_date = doc.work_date
    att.status = verdict(doc)
    att.shift = doc.shift_type or None
    att.caf_finger_log = doc.name
    # FDR4 — leave_type is NOT set here, and must never be. Its absence is the
    # point: `Absent` with an empty leave_type is what FBR37's second branch
    # counts as unexplained absence.
    att.flags.ignore_permissions = True
    att.insert()
    att.submit()

    return att.name


def cancel_attendance(doc):
    """Cancel, never delete — Attendance is submittable and the trail must survive.

    Spec §6.6. Used when a Finger Log is cancelled, and by Chunk 4's re-resolve.
    """
    cancelled = []
    for row in frappe.get_all("Attendance",
                              filters={"caf_finger_log": doc.name, "docstatus": 1},
                              fields=["name"]):
        att = frappe.get_doc("Attendance", row.name)
        att.flags.ignore_permissions = True
        att.cancel()
        cancelled.append(row.name)
    return cancelled
