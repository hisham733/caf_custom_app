"""Chunk R — the role pass. R1–R7.

    bench --site <site> execute caf.tests.fingerlog.test_chunk_r.run

WHY THIS EXISTS
---------------
Every other suite in this project runs as **`Administrator`**, which skips
`has_permission` outright and has an explicit early return inside CAF's own
`validate_state_edit_permission`. Chunk 5's fixtures also set
`flags.caf_skip_supervisor_check`.

> **A suite that runs as Administrator passes identically against a completely
> broken permission model.** `PROTOCOL.md` §C1.

So nothing in Chunks 3–T proves who may actually do any of this.

THE QUESTION THAT MATTERS
-------------------------
`refresh_submitted_appraisal()` writes to a **submitted Appraisal** on behalf of
whoever approved a leave. It does that with `ignore_permissions=True`. Nobody had
ever run it as someone who genuinely lacks the permission — so it was unknown
whether the privilege boundary was real or accidental.

WHAT DISCOVERY CHANGED
----------------------
The scope for this chunk assumed a *supervisor* would be the actor. Measured, that
is impossible: **supervisors hold only the `Employee` role, and `Employee` has
`submit = 0` on Leave Application.** A supervisor may create one and never submit
it. The real actor is a **Leave Approver** — and that role carries **no Appraisal
permission at all**, so its Appraisal access comes from `Employee`: `write = 1`,
**`submit = 0`**. It is exactly the caller R1 needed.

`frappe.set_user()` rather than REST tokens: the questions here are all about the
permission model, which `set_user` exercises in full — `has_permission`,
`get_valid_perms` and the controller hooks all read `frappe.session.user`. What it
does **not** cover is the HTTP/whitelist layer; nothing in R1–R7 turns on that.

RE-RUNNABLE: artifacts are removed FIRST, not last. The session is always returned
to Administrator in a `finally` — leaving it switched would silently corrupt every
suite that ran afterwards in the same process.
"""

import frappe
from frappe.utils import add_to_date, getdate

from caf.caf import appraisal_refresh as ar

SUP = "HR-EMP-00001"                      # 22 direct reports
REP = "HR-EMP-00075"                      # reports to SUP, 8am Schedule (Mon–Sat)
REP_USER = "seriramulu@caffood.com"       # role: Employee
APPROVER = "quality@caffood.com"          # roles: Employee + Leave Approver
HRM = "hr.manager.test@caffood.com"       # role: HR Manager

CYCLE = "2026-06"
TEMPLATE = "CAF Monthly Appraisal"
# 🔴 JUNE, NOT JULY — found the hard way while building this file. The Ingress
# importer covers 2026-07-01..31 and nothing else, and `cleanup()` deletes by
# (employee, date). The first version of this suite used 2026-07-28/29 and
# DELETED TWO IMPORTED ROWS on its very first run, silently, while reporting
# 11/12 green. Re-importing the month restored 67 rows in total — the other three
# suites had been doing the same thing for days. June has no imported Finger Logs
# at all, so a fixture here can only delete what it created, and the expected
# values are exact because no imported day can drift into the cell.
D_ABS = "2026-06-16"                      # Tue — punchless -> Absent -> counted
# ⚠️ NOT the 17th: 2026-06-17 is AWAL MUHARRAM in both CAF holiday lists, and
# stock refuses a leave application whose every day is a holiday — *"You need not
# apply for leave"*. That refusal arrives long before any CAF logic, so six of
# this suite's twelve assertions failed for a reason that had nothing to do with
# roles. A calendar clash reads exactly like a broken permission model.
D_LEAVE = "2026-06-18"                    # Thu — the leave the approver files
NO_SAT = "8am no OT no Sat"
LEAVE_TYPE = "Emergency"                  # is_lwp, and FBR37 counts it

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def as_user(user, fn, *args, **kwargs):
    """Run `fn` as `user`, then always come back. Returns (result, exception_name)."""
    frappe.set_user(user)
    try:
        return fn(*args, **kwargs), ""
    except Exception as e:
        return None, type(e).__name__
    finally:
        frappe.set_user("Administrator")


def remove(doctype, name):
    if not frappe.db.exists(doctype, name):
        return
    doc = frappe.get_doc(doctype, name)
    doc.flags.ignore_links = True
    doc.flags.ignore_permissions = True
    if doc.docstatus == 1:
        doc.cancel()
    frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


def cleanup():
    days = [D_ABS, D_LEAVE]
    for dt, field in (("Leave Application", "from_date"),
                      ("Attendance", "attendance_date"),
                      ("Finger Log", "work_date"),
                      ("Shift Assignment", "start_date")):
        for r in frappe.get_all(dt, filters={"employee": REP, field: ("in", days)},
                                fields=["name"]):
            remove(dt, r.name)
    for r in frappe.get_all("Appraisal", filters={"employee": REP,
                                                  "appraisal_cycle": CYCLE},
                            fields=["name"]):
        remove("Appraisal", r.name)
    frappe.db.commit()


def make_log(day):
    doc = frappe.new_doc("Finger Log")
    doc.employee = REP
    doc.employee_name = frappe.db.get_value("Employee", REP, "employee_name")
    doc.work_date = day
    for f in ("time_in", "break", "resume", "out"):
        doc.set(f, "00:00:00")
    doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def make_appraisal():
    doc = frappe.new_doc("Appraisal")
    doc.employee = REP
    doc.appraisal_cycle = CYCLE
    doc.appraisal_template = TEMPLATE
    doc.flags.caf_skip_supervisor_check = True
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.flags.caf_skip_supervisor_check = True
    doc.submit()
    doc.db_set("workflow_state", "Completed", update_modified=False)
    return doc


def cell(name):
    doc = frappe.get_doc("Appraisal", name)
    for r in doc.appraisal_kra:
        if r.kra == "Attendance":
            return (r.caf_date_cell or "").strip()
    return None


def file_leave(day, submit=True, leave_type=LEAVE_TYPE):
    """No ignore_permissions ANYWHERE — that is the entire point of this file."""
    la = frappe.new_doc("Leave Application")
    la.employee = REP
    la.leave_type = leave_type
    la.from_date = day
    la.to_date = day
    la.status = "Approved"
    la.company = frappe.db.get_value("Employee", REP, "company")
    la.insert()
    if submit:
        la.submit()
    return la.name


def tamper_appraisal(name, field="caf_date_cell", value="9, 9, 9"):
    doc = frappe.get_doc("Appraisal", name)
    setattr(doc.appraisal_kra[0], field, value)
    doc.save()
    return "saved"


def tamper_log(name):
    doc = frappe.get_doc("Finger Log", name)
    doc.final_ot = 42.0
    doc.save()
    return "saved"


# ------------------------------------------------------------------ the suite

def run():
    try:
        cleanup()
        log = make_log(D_ABS)
        app = make_appraisal()
        base = cell(app.name)
        check("R-FIX", app.docstatus == 1 and base == str(getdate(D_ABS).day),
              f"fixture: {app.name} submitted for {REP}, Attendance cell {base!r} "
              f"— exactly day {getdate(D_ABS).day}, nothing imported drifting in")

        # ------------------------------------------------------------- R6
        # The employee themselves. Employee has create = 1 but submit = 0 on Leave
        # Application, so self-service stops at the draft.
        made, err = as_user(REP_USER, file_leave, D_LEAVE, False)
        check("R6a", err == "" and made,
              f"{REP_USER} (Employee) CAN create their own leave: {made or err}")
        _, err = as_user(REP_USER, lambda n: frappe.get_doc("Leave Application", n).submit(),
                         made)
        check("R6b", err in ("PermissionError", "ValidationError"),
              f"...and CANNOT submit it: {err or 'IT SUBMITTED — submit=0 is not holding'}")
        remove("Leave Application", made)

        # ------------------------------------------------------------- R1
        # 🔴 The heart of the chunk. A Leave Approver submits a leave, which makes
        # the system rewrite a SUBMITTED appraisal — a document this user has
        # `write` on but NOT `submit`, so they could never write it themselves.
        before = cell(app.name)
        la, err = as_user(APPROVER, file_leave, D_LEAVE)
        check("R1a", err == "" and la,
              f"{APPROVER} (Leave Approver) submitted a leave for {REP}: {la or err}")
        after = cell(app.name)
        # Assert on the DATA, not on the rendered string: format_day_cell collapses
        # consecutive days into a range (D68), so "28, 30, 31" becoming "28-31" IS
        # day 29 appearing — and a naive `"29" in after` reports the opposite.
        counted = frappe.get_all("Attendance",
                                 filters={"employee": REP, "attendance_date": D_LEAVE,
                                          "docstatus": 1},
                                 fields=["status", "leave_type"])
        check("R1b", after != before and counted and counted[0].leave_type == LEAVE_TYPE
              and after == ", ".join(sorted(
                  {str(getdate(D_ABS).day), str(getdate(D_LEAVE).day)}, key=int)),
              f"...and the SUBMITTED appraisal refreshed: {before!r} -> {after!r}, "
              f"attendance {[(r.status, r.leave_type) for r in counted]} — "
              f"ignore_permissions carried a caller who lacks `submit` on Appraisal")

        _, err = as_user(APPROVER, tamper_appraisal, app.name)
        check("R1c", err in ("PermissionError", "ValidationError"),
              f"...but that same user editing the appraisal DIRECTLY is refused ({err}) "
              f"— so R1b was the privilege boundary working, not the user's own rights")

        # ------------------------------------------------------------- R3
        # The OD-61 guard, per role. The approver is stopped by PERMISSION (no
        # submit); HR Manager HAS submit, so only the guard stands between them
        # and the cell — which is precisely why the guard had to exist.
        _, err_hrm = as_user(HRM, tamper_appraisal, app.name)
        check("R3", err_hrm == "ValidationError",
              f"HR Manager typing into caf_date_cell on a submitted appraisal: {err_hrm} "
              f"— they HAVE write+submit, so OD-61's guard is the only thing refusing")

        _, err_ro = as_user(HRM, tamper_log, log.name)
        check("R3b", err_ro == "ValidationError",
              f"HR Manager typing final_ot onto a submitted Finger Log: {err_ro} "
              f"— OD-62's guard, same shape. final_ot drives OT pay")

        # ------------------------------------------------------------- R7
        # The supervisor's own text. A DIFFERENT lock (allow_on_submit = 0), so it
        # must be asserted separately — and it must hold for the privileged role too.
        _, err = as_user(HRM, tamper_appraisal, app.name, "caf_description", "forged")
        check("R7", err == "UpdateAfterSubmitError",
              f"the supervisor's own caf_description refuses even HR Manager: {err}")

        # ------------------------------------------------------------- R4
        # HR Manager cancels the leave. restore_day_after_leave() then CREATES an
        # Attendance row on their behalf — another ignore_permissions path.
        pre = cell(app.name)
        _, err = as_user(HRM, lambda n: frappe.get_doc("Leave Application", n).cancel(), la)
        live = frappe.get_all("Attendance",
                              filters={"employee": REP, "attendance_date": D_LEAVE,
                                       "docstatus": 1}, fields=["status"])
        check("R4", err == "" and cell(app.name) != pre,
              f"HR Manager cancelled the leave ({err or 'ok'}): appraisal {pre!r} -> "
              f"{cell(app.name)!r}, attendance now {[r.status for r in live] or 'none'}")

        # ------------------------------------------------------------- R5
        # A Shift Assignment filed by HR Manager re-resolves a SUBMITTED Finger Log
        # belonging to someone else.
        def file_sa():
            sa = frappe.new_doc("Shift Assignment")
            sa.employee = REP
            sa.company = frappe.db.get_value("Employee", REP, "company")
            sa.shift_type = NO_SAT
            sa.start_date = sa.end_date = D_ABS
            sa.status = "Active"
            sa.insert()
            sa.submit()
            return sa.name

        # Assert on shift_type, not day_type: D_ABS is a weekday, which BOTH shifts
        # work, so day_type would read "Workday -> Workday" and prove nothing. The
        # shift reference is what actually moved on the submitted document.
        before_st = frappe.db.get_value("Finger Log", log.name, "shift_type")
        sa, err = as_user(HRM, file_sa)
        after_st = frappe.db.get_value("Finger Log", log.name, "shift_type")
        check("R5", err == "" and sa and after_st == NO_SAT and after_st != before_st,
              f"HR Manager filed a Shift Assignment ({err or 'ok'}) which re-resolved "
              f"{REP}'s SUBMITTED Finger Log: shift_type {before_st!r} -> {after_st!r}")

        # ------------------------------------------------------------- R2
        # The FBR39 refusal has to reach the person who tried, with a message that
        # explains itself. ⚠️ PROTOCOL E5 — the message is the part that silently
        # goes missing.
        old = add_to_date(ar.submitted_on(app.name), months=-2)
        for v in frappe.get_all("Version", filters={"ref_doctype": "Appraisal",
                                                    "docname": app.name},
                                fields=["name"]):
            frappe.db.set_value("Version", v.name, "creation", old, update_modified=False)
        frappe.db.commit()

        frappe.set_user(APPROVER)
        msg = ""
        try:
            file_leave(D_LEAVE)
        except Exception as e:
            msg = str(e)
        finally:
            frappe.set_user("Administrator")
        check("R2", ("window has closed" in msg or "FBR39" in msg) and app.name in msg,
              f"the FBR39 refusal reached the Leave Approver, naming the appraisal and "
              f"the deadline: {msg[:120] or 'NO MESSAGE — it was allowed through'}")

        cleanup()
        frappe.db.commit()
    finally:
        # If this is ever skipped, every later suite in the same process runs as
        # somebody else and the failures appear far from here.
        frappe.set_user("Administrator")

    print(f"\n=== Chunk R — the role pass (cycle {CYCLE}) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:7s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    print(f"   session restored to: {frappe.session.user}")
    return not failed
