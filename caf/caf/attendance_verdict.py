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
        # MG, 2026-09-01: name the person, and make the leave clickable. The
        # employee id was the only identifier here, and the Leave Application was
        # named but not reachable — so HR read the message, then went looking.
        # ⚠️ The FIRST line is what the import manifest keeps (`strip_html`, one
        # line, 280 chars), so it has to carry who / when / why on its own; the
        # rest is for the dialog.
        who = frappe.db.get_value("Employee", doc.employee, "employee_name") \
            or doc.employee
        frappe.throw(_(
            '<a href="/app/employee/{0}">{1}</a> has approved leave on {2} '
            '(<b>{3}</b>, <a href="/app/leave-application/{4}">{4}</a>).'
            "<br><br>A Finger Log may not overwrite an approved absence — cancel "
            "or amend the leave application first, and the day is restored from "
            "this log automatically."
        ).format(doc.employee, frappe.utils.escape_html(who), doc.work_date,
                 leave[0].leave_type, leave[0].name),
            title=_("The day is already decided by leave"))

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


def leave_owns_the_day(row):
    """Is this Attendance row owned by a leave that is STILL APPROVED?

    🔴 ONE PREDICATE, TWO CALL SITES — and it exists because they disagreed.
    `block_cancel_of_leave_owned_day` (the D-12 guard) asked this question;
    `cancel_attendance` (the Finger Log cascade) did not ask it at all, and
    switched the guard off instead. **T-44 is that gap**: measured 2026-09-12,
    a programmatic cancel of a Finger Log took an approved leave's day with it
    while the Leave Application stayed Approved.

    `re_resolve.reconcile_attendance` has had the equivalent check in BOTH of its
    branches since D-12 — *"a row carrying a leave_type was decided by a Leave
    Application. Re-resolve must not touch it."* This makes the third sibling
    agree with the other two.

    ⚠️ The "still approved" clause is deliberate and is D-12's own: a STRAY row
    left behind after a leave was cancelled must stay repairable, or the only
    route to tidy it is closed too.

    `row` may be a Document or any object with `leave_type` / `leave_application`.
    """
    la = row.get("leave_application") if hasattr(row, "get") else None
    leave_type = row.get("leave_type") if hasattr(row, "get") else None
    if not la and not leave_type:
        return False                      # a plain day — corrections stay open
    if not la:
        return False                      # leave_type with no application: stray
    return frappe.db.get_value("Leave Application", la, "docstatus") == 1


def cancel_attendance(doc):
    """Cancel, never delete — Attendance is submittable and the trail must survive.

    Spec §6.6. Used when a Finger Log is cancelled, and by Chunk 4's re-resolve.

    🔴 A LEAVE-OWNED DAY IS LEFT ALONE — fixed 2026-09-12, T-44.
    ------------------------------------------------------------
    This used to set `caf_skip_leave_guard = True` unconditionally, on the stated
    assumption that *"FL-created rows carry no leave_type (FDR4)"*. **That
    assumption is false**: when a late leave lands on a day whose Attendance is
    `Absent`, stock reconciles **the same row** to `On Leave` and leaves
    `caf_finger_log` in place. The row then carries both claims, and this
    cascade — selecting on exactly that link — cancelled an approved leave's day
    with nobody told.

    ⚠️ **Measured both ways, 2026-09-12.** Through the DESK it never fired:
    Frappe's *"Cancel All Documents"* cascade calls a plain `att.cancel()`, so
    D-12 refused and the Finger Log stayed submitted. It fired only on the
    PROGRAMMATIC route — `doc.cancel()` from re-resolve, the API or `bench` —
    which is the one nobody watches.

    ⭐ **Skips, never throws**, matching `re_resolve`'s *"left alone (leave)"*:
    a bulk cancel over a month must not abort on one day that a leave owns.

    🔴 **This does NOT close T-44 itself.** The row still carries `caf_finger_log`
    AND `leave_type`, so `test_chunk3_decisions` FDR4 stays red. Whether the link
    should be CLEARED when leave takes the day is a design decision about which
    source owns a day, and it is MG's.
    """
    cancelled, left_alone = [], []
    for row in frappe.get_all(
            "Attendance",
            filters={"caf_finger_log": doc.name, "docstatus": 1},
            fields=["name", "leave_type", "leave_application"]):
        if leave_owns_the_day(row):
            left_alone.append((row.name, row.leave_application))
            continue
        att = frappe.get_doc("Attendance", row.name)
        att.flags.ignore_permissions = True
        # D-12 — a machine cancel of a day this Finger Log genuinely decided.
        # The guard would otherwise refuse a plain-day correction.
        att.flags.caf_skip_leave_guard = True
        att.cancel()
        cancelled.append(row.name)

    if left_alone:
        # Silence is what made T-44 dangerous. Say it where a person can see it.
        frappe.msgprint(
            _("{0} was cancelled, but {1} for that day is owned by an approved "
              "leave ({2}) and has been left standing. Cancel the leave "
              "application if the day should go back to what was punched."
              ).format(frappe.bold(doc.name),
                       frappe.bold(", ".join(n for n, _la in left_alone)),
                       ", ".join(la for _n, la in left_alone)),
            title=_("The leave keeps its day"), indicator="orange")
    return cancelled


def block_cancel_of_leave_owned_day(doc, method=None):
    """D-12 (2026-08-15) — a leave-decided day may only be un-decided by
    cancelling the LEAVE, which restores the day from its Finger Log (OD-60)
    and refreshes the appraisal. A direct cancel of the leave-owned Attendance
    row is the one route that silently drops the day from FBR37's count while
    the Leave Application stays Approved.

    Registered as `doc_events "Attendance" -> before_cancel`. The stock
    leave-cancel path erases rows with a raw `db_set docstatus=2` — no events
    fire — so the sanctioned route never trips this guard.
    """
    if doc.flags.caf_skip_leave_guard:
        return

    # ⭐ The same predicate `cancel_attendance` now asks (2026-09-12, T-44). The
    # two used to disagree, and the disagreement was the hole: this one asked,
    # the cascade did not. It covers both earlier clauses — a plain day, and a
    # stray row whose leave has since been cancelled, both stay correctable.
    if not leave_owns_the_day(doc):
        return

    la = doc.get("leave_application")
    frappe.throw(
        _("Attendance {0} belongs to Leave Application {1}, which is still approved. "
          "Cancel the leave application instead - it restores the day from its "
          "Finger Log and keeps the appraisal correct.").format(
              frappe.bold(doc.name), frappe.bold(la)),
        title=_("Leave-owned day"),
    )
