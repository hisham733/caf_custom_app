"""Refresh a SUBMITTED appraisal after a late correction — Chunk 5, OD-44.

A correction that arrives after the appraisal was submitted has to reach the
appraisal, or the two documents disagree permanently. There are exactly two such
corrections, and Chunks 3 and 4 already built both halves of what they do to the
day:

  late Leave Application   Attendance ➜ On Leave + leave_type   a counted day APPEARS
  late Shift Assignment    the false Absent is cancelled        a counted day DISAPPEARS

OD-44 — WHY option (a), and what it does NOT unlock
---------------------------------------------------
`allow_on_submit = 1` on the **two** cells `refresh_auto_fill()` actually writes
(`caf_date_cell`, `caf_remarks`), and nothing else. Measured: the other three
`caf_` columns — `caf_description`, `caf_root_cause`, `caf_corrective_action` —
are the supervisor's own words and stay locked, so a background job can never
rewrite a person's judgement. `Appraisal.auto_fill_computed_on` was already
`allow_on_submit = 1`, which is why the count is two and not three.

Rejected: `db_set` (option b) writes **no Version** — the same audit hole OD-26
exists to close. Cancel + amend (option c) mints `APRSL-xxx-1` and breaks
one-appraisal-per-cycle. And the fourth idea, "move docstatus 1 ➜ 0 like a
reject", is **impossible** — Frappe raises `DocstatusTransitionError`. The
workflow only appears to do it because Draft and Pending HR Review are *both*
docstatus 0.

WHY `submitted_on()` READS THE VERSION LOG
------------------------------------------
FBR39's window is "one month after the appraisal was **submitted**". Frappe
stores no such timestamp — and `modified` is worse than useless here: every
refresh this module performs *is* an `update_after_submit`, which moves
`modified` forward. Using it, the window would be re-opened by the very act of
refreshing and would never close. The Version row carrying
`changed: [["docstatus", 0, 1]]` is the only stable record of the submit.

WHY THE REFRESH MUST NOT THROW — scenario S3, again
---------------------------------------------------
`on_submit` runs inside the leave application's own transaction. A throw there
would not just skip the refresh, it would **undo an approved leave** — the
approval is the important document, the appraisal cell is downstream of it. So
the refusal (FBR39) happens in `before_submit`, where refusing is the point, and
the refresh happens in `on_submit`, where it is caught and logged.

Spec §2.2, §2.3, §2.4 · framework OD-44, OD-26 · scenarios A1–A5, B3.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime

from caf.caf import re_resolve
from caf.caf.overrides import appraisal as ap

# The cells this module is allowed to move. Kept as a constant so the unlock in
# the fixture and the write here cannot drift apart — the test asserts they match.
REFRESHABLE = ("caf_date_cell", "caf_remarks")

# FBR39 — how long after submission a correction may still be filed.
LEAVE_WINDOW_MONTHS = 1


# ---------------------------------------------------------------- lookups

def cycles_covering(start_date, end_date):
    """Every Appraisal Cycle whose period overlaps [start_date, end_date].

    A leave spanning a month boundary (30 June – 2 July) belongs to two cycles,
    so this returns a list, not a single cycle.
    """
    return frappe.get_all(
        "Appraisal Cycle",
        filters={"start_date": ("<=", getdate(end_date)),
                 "end_date": (">=", getdate(start_date))},
        fields=["name", "start_date", "end_date"],
        order_by="start_date")


def submitted_appraisals(employee, start_date, end_date):
    """SUBMITTED appraisals for this employee whose cycle overlaps the range."""
    cycles = [c.name for c in cycles_covering(start_date, end_date)]
    if not cycles:
        return []
    return frappe.get_all(
        "Appraisal",
        filters={"employee": employee, "appraisal_cycle": ("in", cycles), "docstatus": 1},
        fields=["name", "appraisal_cycle", "employee", "employee_name"])


def submitted_on(appraisal_name):
    """When docstatus went 0 ➜ 1, from the Version log. None if unrecorded.

    Do NOT substitute `modified` — see the module docstring. Returning None is
    deliberate: an unknowable submit date must not silently become "just now",
    which would hold the FBR39 window open forever.
    """
    rows = frappe.get_all("Version",
                          filters={"ref_doctype": "Appraisal", "docname": appraisal_name},
                          fields=["creation", "data"], order_by="creation desc",
                          limit_page_length=0)
    for row in rows:
        try:
            data = json.loads(row.data or "{}")
        except ValueError:
            continue
        for change in data.get("changed") or []:
            # ["docstatus", 0, 1] — the submit. Take the most recent, which is
            # what `order_by creation desc` gives us.
            if change[0] == "docstatus" and int(change[2] or 0) == 1:
                return get_datetime(row.creation)
    return None


def window_closed(appraisal_name, on_date=None):
    """(closed, submitted_on, deadline) — FBR39.

    `closed` is False when the submit date cannot be established: refusing a
    person's MC on the strength of a missing audit record would be the wrong way
    to be wrong.
    """
    submitted = submitted_on(appraisal_name)
    if not submitted:
        return False, None, None
    deadline = add_to_date(submitted, months=LEAVE_WINDOW_MONTHS)
    return (get_datetime(on_date or now_datetime()) > get_datetime(deadline),
            submitted, deadline)


# ---------------------------------------------------------------- the refresh

def _auto_fill_cells(doc):
    return {row.kra: {f: (row.get(f) or "") for f in REFRESHABLE}
            for row in doc.appraisal_kra if row.kra in ap.AUTO_FILLED_KRAS}


def refresh_submitted_appraisal(name, reason="", trigger=None):
    """Recompute the two auto-fill cells on a SUBMITTED appraisal.

    Returns a dict describing what moved. Idempotent: recomputing an appraisal
    that already agrees with the data writes nothing and comments nothing.

    ⚠️ `force=True` is what makes scenario **A5** work — the case where the
    number goes DOWN. `refresh_auto_fill(force=False)` only fills cells that are
    still empty, so it can add a counted day but can never remove one. Every
    other test in the suite adds something; A5 is the one that would pass
    silently with the wrong flag.
    """
    doc = frappe.get_doc("Appraisal", name)
    if doc.docstatus != 1:
        return {"name": name, "skipped": f"docstatus {doc.docstatus}, not submitted"}

    before = _auto_fill_cells(doc)
    doc.refresh_auto_fill(force=True)
    after = _auto_fill_cells(doc)

    changed = {}
    for kra, cells in after.items():
        for field, new in cells.items():
            old = before.get(kra, {}).get(field, "")
            if old != new:
                changed.setdefault(kra, {})[field] = (old, new)

    if not changed:
        return {"name": name, "changed": {}}

    doc.flags.ignore_permissions = True
    # OD-61: this is the system writing the cells, which is the one thing the
    # guard in `CustomAppraisal.before_update_after_submit` lets through.
    doc.flags.caf_system_write = True
    # update_after_submit — validated against allow_on_submit, and it writes a
    # Version. That trail is the whole reason option (a) beat db_set.
    doc.save(ignore_permissions=True)

    lines = [_("Refreshed after submit (OD-44){0}.").format(f" — {reason}" if reason else "")]
    for kra, cells in changed.items():
        for field, (old, new) in cells.items():
            lines.append("{0} · {1}: {2} ➜ {3}".format(
                kra, field, f"“{old}”" if old else _("(empty)"),
                f"“{new}”" if new else _("(empty)")))
    if trigger:
        lines.append(_("Caused by {0} {1}.").format(trigger[0], trigger[1]))
    doc.add_comment("Comment", "<br>".join(lines))

    return {"name": name, "changed": changed}


def refresh_for(employee, start_date, end_date, reason="", trigger=None, within_window=False):
    """Refresh every submitted appraisal this date range touches. Never throws.

    One savepoint per appraisal — the Chunk 4 rule. A single unrefreshable
    appraisal must not roll back the document that triggered this.

    `within_window` (D-13): refresh only appraisals whose FBR39 window is still
    open. The OT-cancel cascade uses this — a settled appraisal stays final
    (MG's ruling); the flag + comment on the log still record the event.
    """
    results = []
    for app in submitted_appraisals(employee, start_date, end_date):
        if within_window and window_closed(app.name)[0]:
            results.append({"name": app.name, "skipped": "window closed"})
            continue
        sp = f"ar_{app.name}".replace("-", "_")[:60]
        frappe.db.savepoint(sp)
        try:
            results.append(refresh_submitted_appraisal(app.name, reason, trigger))
        except Exception as e:
            frappe.db.rollback(save_point=sp)
            frappe.log_error(
                title=f"Appraisal refresh failed: {app.name}",
                message=frappe.get_traceback())
            results.append({"name": app.name, "error": str(e).splitlines()[0][:140]})
    return results


# ---------------------------------------------------- the cancel side (OD-60)

def _days(from_date, to_date):
    out, day, end = [], getdate(from_date), getdate(to_date or from_date)
    while day <= end:
        out.append(day)
        day = add_days(day, 1)
    return out


def restore_day_after_leave(employee, from_date, to_date, leave_application):
    """Put the day's own verdict back after a leave is cancelled — OD-60.

    🔴 **Stock does not revert the day, it ERASES it.**
    `LeaveApplication.cancel_attendance()` (hrms `leave_application.py:347`) runs

        frappe.db.set_value("Attendance", name, "docstatus", 2)

    — a raw `db_set` of `docstatus`. So: no Version, `on_cancel` never fires, and
    `leave_type` / `leave_application` are left populated on the dead row. Worst
    of all, the `Absent` that stood there *before* the leave does not come back.

    Measured consequence, which is why this function exists: a punchless day
    counted by FBR37's second branch (unexplained absence) becomes an MC counted
    by its first branch, and on cancel becomes **counted by nothing**. The
    appraisal number would go DOWN when it should return to where it started —
    and `refresh_for()` would faithfully write that wrong number into a submitted
    appraisal.

    `existing_attendance()` filters `docstatus < 2`, so the cancelled row is
    invisible to Chunk 4's reconciler and it rebuilds the verdict cleanly. Where
    no Finger Log exists — a leave for a day Ingress never emitted a row for —
    there is correctly nothing to restore.

    ⚠️ **No FBR39 gate here, by decision (MG, 2026-08-11).** Filing asks for
    something new; cancelling corrects something already on the record. Refusing
    a late cancel would leave a known-wrong leave standing, and the appraisal
    counting it, forever.
    """
    trail, restored = [], []

    # The trail stock did not write (OD-26). `db_set` leaves no Version, so on a
    # row that feeds an appraisal and a pay slip the comment is the only record.
    for row in frappe.get_all(
            "Attendance",
            filters={"employee": employee, "leave_application": leave_application,
                     "attendance_date": ("between", [getdate(from_date), getdate(to_date)])},
            fields=["name", "docstatus", "attendance_date", "status", "leave_type"]):
        if row.docstatus != 2:
            continue
        att = frappe.get_doc("Attendance", row.name)
        att.flags.ignore_permissions = True
        att.add_comment("Comment", _(
            "Leave Application {0} was cancelled. Stock set docstatus = 2 directly, which "
            "writes no Version — this comment is the trail (OD-26). The day's own verdict "
            "is restored from its Finger Log below."
        ).format(leave_application))
        trail.append(row.name)

    for day in _days(from_date, to_date):
        for log in frappe.get_all("Finger Log",
                                  filters={"employee": employee, "work_date": day,
                                           "docstatus": 1}, fields=["name"]):
            sp = f"rl_{log.name}".replace("-", "_")[:60]
            frappe.db.savepoint(sp)
            try:
                fl = frappe.get_doc("Finger Log", log.name)
                restored.append((str(day), re_resolve.reconcile_attendance(fl)))
            except Exception as e:
                frappe.db.rollback(save_point=sp)
                restored.append((str(day), f"error: {str(e).splitlines()[0][:80]}"))

    return {"commented": trail, "restored": restored}


# ---------------------------------------------------------------- doc_events

def check_leave_window(doc, method=None):
    """FBR39 — refuse a leave filed more than a month after the appraisal was
    submitted. **This is the only place that boundary is enforced.**

    In `before_submit`, not `on_submit`: Frappe writes `docstatus = 1` before
    `on_submit` runs, so a refusal there leaves the document both submitted and
    rejected. That trap cost a day during Chunk 3.

    ⚠️ **Approved applications only.** A submitted Leave Application is either
    Approved or Rejected (stock `on_submit` throws on anything else), and
    `update_attendance()` opens with `if self.status != "Approved": return` — so
    a **rejection touches no Attendance whatsoever**. FBR39 protects a submitted
    appraisal from an Attendance change; where there is no change there is
    nothing to protect, and refusing would only stop a supervisor recording that
    they said no. Raised by MG 2026-08-11.
    """
    if doc.get("__islocal") or not doc.employee:
        return
    if doc.status != "Approved":
        return
    for app in submitted_appraisals(doc.employee, doc.from_date, doc.to_date):
        closed, submitted, deadline = window_closed(app.name)
        if not closed:
            continue
        # 🔴 The message names the WAY OUT, not just the refusal — MG, 2026-08-17.
        #
        # FBR39 is not a ceiling on backdating; it is a gate that forces the
        # deliberate route. Cancelling the appraisal removes it from
        # `submitted_appraisals()` (which filters docstatus = 1), so this check
        # stops applying and the leave files normally. The appraisal is then
        # amended and re-submitted, recomputing from the corrected attendance —
        # which is SAFER than the in-place refresh, because nothing can be left
        # stale.
        #
        # The old message ended "Ask HR how to record it", which told a supervisor
        # nothing and told HR nothing either. A refusal that hides the remedy gets
        # worked around, not obeyed.
        frappe.throw(
            _(
                "Appraisal {0} for cycle {1} was submitted on {2}, and leave for that "
                "period could be filed until {3}. That window has closed, so this "
                "application cannot be approved as it stands (FBR39)."
                "<br><br><b>How to record it anyway:</b> HR cancels appraisal {0}, "
                "then this leave can be approved normally, then the appraisal is "
                "amended and re-submitted — it will recompute from the corrected "
                "attendance. There is no time limit on that route; the window only "
                "governs changing a <i>submitted</i> appraisal in place."
            ).format(frappe.bold(app.name), app.appraisal_cycle,
                     frappe.format(submitted, {"fieldtype": "Datetime"}),
                     frappe.format(deadline, {"fieldtype": "Datetime"})),
            title=_("Leave window closed — appraisal must be re-opened"))


def on_leave_application_submit(doc, method=None):
    """An approved leave rewrote the day. Carry that into a submitted appraisal.

    Caught, never raised: the leave approval is the document that matters, and
    it is already committed by the time this runs.

    A **Rejected** application is skipped for the same reason `check_leave_window`
    skips it: stock wrote no Attendance, so there is nothing to recompute. The
    refresh is idempotent and would be harmless — but it would also fire on every
    rejection forever, for no reason.
    """
    if doc.status != "Approved":
        return
    try:
        refresh_for(doc.employee, doc.from_date, doc.to_date,
                    reason=_("{0} approved for {1} to {2}").format(
                        doc.leave_type, doc.from_date, doc.to_date),
                    trigger=("Leave Application", doc.name))
    except Exception:
        frappe.log_error(title=f"Appraisal refresh failed for {doc.name}",
                         message=frappe.get_traceback())


def on_leave_application_cancel(doc, method=None):
    """A withdrawn leave moves Attendance too — OD-60.

    Order is the contract, exactly as on the submit side: the day is restored
    FIRST, then the appraisal reads it. Reversed, the appraisal would recompute
    against the hole stock left and record the wrong number.
    """
    try:
        restore_day_after_leave(doc.employee, doc.from_date, doc.to_date, doc.name)
        refresh_for(doc.employee, doc.from_date, doc.to_date,
                    reason=_("{0} for {1} to {2} was CANCELLED").format(
                        doc.leave_type, doc.from_date, doc.to_date),
                    trigger=("Leave Application", doc.name))
    except Exception:
        frappe.log_error(title=f"Appraisal refresh failed for cancelled {doc.name}",
                         message=frappe.get_traceback())


def on_shift_assignment_refresh(doc, method=None):
    """A late swap can REMOVE a counted day — scenario A5, the direction nobody
    tests. Chunk 4 already cancelled the false Absent; this tells the appraisal.

    Hooked after `re_resolve.on_shift_assignment_submit`, so the Attendance is
    already correct when the appraisal reads it. The same function serves
    `on_cancel` — Chunk 4 re-resolves the day there too, so by the time this runs
    the Attendance is right either way and the refresh simply reads it.
    """
    try:
        refresh_for(doc.employee, doc.start_date, doc.end_date or doc.start_date,
                    reason=_("Shift Assignment {0} for {1}").format(doc.name, doc.shift_type),
                    trigger=("Shift Assignment", doc.name))
    except Exception:
        frappe.log_error(title=f"Appraisal refresh failed for {doc.name}",
                         message=frappe.get_traceback())
