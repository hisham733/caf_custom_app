"""Re-resolve a past day after a Shift Assignment is filed late — Chunk 4, OD-40.

A swap recorded after the fact does not change what the clock saw. It changes
what that day MEANT. So this recomputes the *interpretation* and leaves the
observation alone:

  rewritten   day_type · shift_type · caf_work_hours · short · ot_in_hour · final_ot
  UNTOUCHED   time_in · break · resume · out · overtime          ← FDR10, absolute

WHY `doc.save()` AND NEVER `db_set`
-----------------------------------
`db_set` writes **no Version record** (measured: analysis §12.5, protocol §9).
These fields feed someone's appraisal and their OT pay — a change with no
before/after trail is exactly the audit hole OD-26 exists to close. `save()` on
a submitted document is `update_after_submit`, which the Chunk 1 flag flip
(OD-48) made possible: `allow_on_submit = 1` on every derived field, `read_only
= 1` so a person still cannot type them.

WHY IT MUST NOT THROW — scenario S3
-----------------------------------
`check_ot_approval()` calls `frappe.throw()`. That is right for an interactive
submit and **wrong here**: this runs over every date an assignment covers, so
one uncovered row would abort every remaining employee in the batch, silently.
Instead the row is flagged — `caf_hr_review` + a comment — and the batch
continues.

BOTH MEN TAKE THE SAME PATH
---------------------------
There is **always** a Finger Log: Ingress emits a row per rostered day whether
or not anyone punched (3,993 punchless rows). So the man who covered the
Saturday and the man who stayed home are the same code path, distinguished only
by whether the punches are all-zero. Spec §6.7.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

from caf.caf import work_hours
from caf.caf.attendance_verdict import (
    existing_attendance, should_have_attendance, verdict)
from caf.caf.doctype.finger_log.finger_log import apply_ot_rules
from caf.caf.shift_resolution import get_shift_params, resolve_day_type

TRACKED = ("day_type", "shift_type", "caf_work_hours", "short", "ot_in_hour", "final_ot")


def _ot_coverage(doc):
    """(final_ot, approval_id, has_overwrite, problem) — the non-throwing twin of
    `check_ot_approval()`. `problem` is None when the OT is properly covered."""
    if not doc.ot_in_hour:
        return 0.0, None, 0, None

    # 🔴 The wording is kept deliberately close to `check_ot_approval`'s, because
    # HR meets the two in the same worklist — one as a refusal at submit, one as a
    # note on a flagged row. Two descriptions of one problem is how a person ends
    # up believing they are two problems.
    who = frappe.db.get_value("Employee", doc.employee, "employee_name") or doc.employee

    rows = frappe.get_all("OT Approval Table",
                          filters={"emp_id": doc.employee, "work_date": doc.work_date,
                                   "docstatus": 1},
                          fields=["parent", "ot_duration"], order_by="creation desc")
    if not rows:
        return 0.0, None, 0, _(
            "{0} now has {1}h of overtime on {2} and no approved OT Approval "
            "covers that day (FBR11). File one for {2}, or correct the punches."
        ).format(who, doc.ot_in_hour, doc.work_date)

    child = rows[0]
    parent = frappe.db.get_value("OT Approval", child.parent,
                                 ["name", "type", "docstatus"], as_dict=True)
    if not parent:
        return 0.0, None, 0, _(
            "OT Approval {0} covering {1} on {2} no longer exists, although its "
            "row remains. A data problem, not a decision."
        ).format(child.parent, who, doc.work_date)

    # Parity with `check_ot_approval`: a draft or cancelled approval authorises
    # nothing. The parent's own work_date is NOT compared — 77 submitted child
    # rows legitimately differ from their header, and multi-date approvals exist.
    if parent.docstatus != 1:
        return 0.0, None, 0, _(
            "OT Approval {0} is {1}, so it cannot authorise {2}h for {3} on {4}."
        ).format(parent.name,
                 {0: _("still a draft"), 2: _("cancelled")}.get(
                     parent.docstatus, _("not submitted")),
                 doc.ot_in_hour, who, doc.work_date)

    if parent.type == "special_approve":
        return child.ot_duration, parent.name, 1, None
    if doc.ot_in_hour <= child.ot_duration:
        return doc.ot_in_hour, parent.name, 0, None

    return 0.0, None, 0, _(
        "{0} now has {1}h of overtime on {2} but OT Approval {3} approved only "
        "{4}h — {5}h more than authorised. Amend {3}, file a special approval, or "
        "correct the punches."
    ).format(who, doc.ot_in_hour, doc.work_date, parent.name, child.ot_duration,
             round(flt(doc.ot_in_hour) - flt(child.ot_duration), 2))


def reconcile_attendance(doc):
    """Update, create or CANCEL the day's Attendance. Never delete — spec §6.6.

    He punched            -> the verdict stands. He was there; a reclassified
                             Saturday does not unmake that.
    All-zero, Workday     -> an Absent belongs here.
    All-zero, not Workday -> the Absent was false. Cancel it.
    """
    rows = existing_attendance(doc.employee, doc.work_date)
    # One predicate, shared with the creation path — they disagreed once and it
    # produced 287 false Absents on rest days.
    should_exist = should_have_attendance(doc)

    if not should_exist:
        for row in rows:
            if row.docstatus == 1:
                # D-12 (2026-08-15) — mirror the update branch's FDR4 check:
                # a row carrying a leave_type was decided by a Leave
                # Application. The machine must never cancel it either.
                if row.leave_type:
                    return "left alone (leave)"
                att = frappe.get_doc("Attendance", row.name)
                att.flags.ignore_permissions = True
                att.flags.caf_skip_leave_guard = True
                att.cancel()
                att.add_comment("Comment", _(
                    "Cancelled by re-resolve: {0} is now a {1} for {2}. Cancelled, never "
                    "deleted — spec §6.6.").format(doc.work_date, doc.day_type, doc.employee))
                return "cancelled"
        return "nothing to cancel"

    want = verdict(doc)
    for row in rows:
        if row.docstatus != 1:
            continue
        # 🔴 FDR4 — a row carrying a leave_type was decided by a Leave
        # Application. Re-resolve must not touch it.
        if row.leave_type:
            return "left alone (leave)"
        if row.status != want:
            att = frappe.get_doc("Attendance", row.name)
            att.flags.ignore_permissions = True
            # add_comment first: db_set writes no Version, so the comment IS the
            # trail here (OD-26).
            att.add_comment("Comment", _("status {0} ➜ {1} by re-resolve of {2}").format(
                row.status, want, doc.name))
            att.db_set("status", want)
            return f"status {row.status} -> {want}"
        return "unchanged"

    att = frappe.new_doc("Attendance")
    att.employee = doc.employee
    att.attendance_date = doc.work_date
    att.status = want
    att.shift = doc.shift_type or None
    att.caf_finger_log = doc.name
    att.flags.ignore_permissions = True
    att.insert()
    att.submit()
    return f"created {want}"


def re_resolve_finger_log(name: str, reason: str = "") -> dict:
    """Recompute one submitted Finger Log. Returns what changed. Never throws."""
    doc = frappe.get_doc("Finger Log", name)
    before = {f: doc.get(f) for f in TRACKED}

    day_type, shift = resolve_day_type(doc.employee, doc.work_date)
    if not shift:
        return {"name": name, "skipped": "no shift resolves for this date"}

    doc.day_type = day_type
    doc.shift_type = shift
    params = get_shift_params(shift)

    work, short = work_hours.compute(doc.time_in, doc.get("break"), doc.resume,
                                     doc.out, params)
    if work is None and work_hours.is_all_zero(doc):
        doc.caf_work_hours = 0
        doc.short = round(work_hours.net_minutes(params) / 60.0, 4) \
            if day_type == "Workday" else 0
    else:
        doc.caf_work_hours = work or 0
        doc.short = short if short is not None else 0

    doc.ot_in_hour = apply_ot_rules(doc.overtime, params)
    final_ot, approval, overwrite, problem = _ot_coverage(doc)
    doc.final_ot = final_ot
    doc.ot_approval_id = approval
    doc.has_overwrite = overwrite

    # S3 — flag, do not throw. A background batch must survive a bad row.
    doc.caf_hr_review = 1 if problem else 0
    doc.caf_hr_review_note = problem or ""

    changed = {f: (before[f], doc.get(f)) for f in TRACKED if before[f] != doc.get(f)}
    if not changed and not problem:
        return {"name": name, "changed": {}, "attendance": "unchanged"}

    doc.flags.ignore_permissions = True
    # OD-62: re-resolve IS the machine writing the derived fields — the one
    # caller `FingerLog.before_update_after_submit` lets past.
    doc.flags.caf_system_write = True
    doc.save()                      # update_after_submit — writes a Version (OD-48)

    if changed:
        doc.add_comment("Comment", _("Re-resolved{0}: {1}").format(
            f" ({reason})" if reason else "",
            ", ".join(f"{k} {v[0]} ➜ {v[1]}" for k, v in changed.items())))
    if problem:
        doc.add_comment("Comment", _("Flagged for HR: {0}").format(problem))

    return {"name": name, "changed": changed,
            "attendance": reconcile_attendance(doc),
            "hr_review": bool(problem), "note": problem}


def _covered_dates(assignment):
    start = getdate(assignment.start_date)
    end = getdate(assignment.end_date or assignment.start_date)
    today = getdate(nowdate())
    if end > today:
        end = today                 # the future needs no correcting
    out, day = [], start
    while day <= end:
        out.append(day)
        day = add_days(day, 1)
    return out


def re_resolve_assignment(assignment, reason: str = "") -> dict:
    """Re-resolve every PAST date a Shift Assignment covers."""
    results, flagged = [], []
    for day in _covered_dates(assignment):
        logs = frappe.get_all("Finger Log",
                              filters={"employee": assignment.employee,
                                       "work_date": day, "docstatus": 1},
                              fields=["name"])
        for log in logs:
            # Savepoint per row: one uncorrectable day must not roll back the rest.
            sp = f"rr_{log.name}".replace("-", "_")[:60]
            frappe.db.savepoint(sp)
            try:
                res = re_resolve_finger_log(log.name, reason)
                results.append(res)
                if res.get("hr_review"):
                    flagged.append(log.name)
            except Exception as e:
                frappe.db.rollback(save_point=sp)
                results.append({"name": log.name, "error": str(e).splitlines()[0][:120]})

    return {"dates": len(_covered_dates(assignment)), "logs": len(results),
            "flagged_for_hr": flagged, "results": results}


# ---------------------------------------------------------------- doc_events

def on_shift_assignment_submit(doc, method=None):
    """FBR25 — a swap is a per-instance Shift Assignment. Filed late, it has to
    reach back and correct the days it covers."""
    res = re_resolve_assignment(doc, reason=f"Shift Assignment {doc.name} submitted")
    if res["flagged_for_hr"]:
        frappe.msgprint(_("Re-resolved {0} day(s). {1} need HR review: {2}").format(
            res["logs"], len(res["flagged_for_hr"]), ", ".join(res["flagged_for_hr"][:5])),
            indicator="orange", title=_("Needs HR review"))


def before_shift_assignment_cancel(doc, method=None):
    """Clear the way for stock's own cancel guard — scenario S4.

    `ShiftAssignment.validate_attendance()` (hrms, `on_cancel`) refuses the
    cancel if ANY Attendance matches employee + shift + date range. Chunk 3
    started writing `Attendance.shift`, which is what makes that filter match —
    so a swap could be filed and then never unfiled.

    ⚠️ **Cancelling the Attendance does not help**: stock's query carries **no
    `docstatus` filter**, so a cancelled row blocks the cancel just as firmly as
    a live one. What has to go is the `shift` REFERENCE, not the row.

    So: cancel the live rows (the day is about to be re-resolved anyway) and
    clear `shift` on all of them. Nothing is deleted — spec §6.6 — and
    `on_cancel` immediately re-resolves, which writes the correct shift back.
    `db_set` leaves no Version, so the comment is the trail (OD-26).
    """
    rows = frappe.get_all(
        "Attendance",
        filters={"employee": doc.employee, "shift": doc.shift_type,
                 "attendance_date": ("between", [doc.start_date,
                                                 doc.end_date or doc.start_date])},
        fields=["name", "docstatus"])
    for row in rows:
        att = frappe.get_doc("Attendance", row.name)
        att.flags.ignore_permissions = True
        att.add_comment("Comment", _(
            "Shift Assignment {0} cancelled: shift reference cleared so the assignment "
            "can be unfiled, then the day is re-resolved. Row kept, never deleted."
        ).format(doc.name))
        if row.docstatus == 1:
            att.cancel()
        att.db_set("shift", None)


def on_shift_assignment_cancel(doc, method=None):
    """Cancelling the assignment must put the day back — scenario S4.

    The resolver reads only SUBMITTED assignments, so by the time this runs the
    day already resolves to the employee's default shift again; re-resolving
    simply writes that back.
    """
    re_resolve_assignment(doc, reason=f"Shift Assignment {doc.name} cancelled")
