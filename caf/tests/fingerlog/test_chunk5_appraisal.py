"""Chunk 5 — refreshing a SUBMITTED appraisal. Scenarios A1-A5, B3, plus the locks.

    bench --site <site> execute caf.tests.fingerlog.test_chunk5_appraisal.run

Two of these are the reason the chunk exists:

  A5   the appraisal number going DOWN. Every other scenario adds something, so
       a `refresh_auto_fill(force=False)` would pass A4 and fail A5 silently.
  B3   the FBR39 refusal — the only place that boundary is enforced anywhere.

And two guard the narrowness of OD-44 option (a):

  LOCK the supervisor's own text must still refuse an update_after_submit
  SUBM `submitted_on()` must not drift when a refresh bumps `modified`

FIXTURE: EMP_A has almost no July 2026 Attendance (two Annual days, which FBR37
does not count), so every counted day in these tests is one this file created.
The Attendance cell is therefore exactly predictable, not merely "different".

RE-RUNNABLE: artifacts are removed FIRST, not last.
"""

import frappe
from frappe.utils import add_to_date, getdate

from caf.caf import appraisal_refresh as ar

EMP_A = "HR-EMP-00016"
EMP_B = "HR-EMP-00017"          # A1 — the draft-appraisal case
CYCLE = "2026-06"
TEMPLATE = "CAF Monthly Appraisal"
NO_SAT = "8am no OT no Sat"     # the shift that does not work Saturday

# 🔴 JUNE, NOT JULY — and this is not cosmetic. The Ingress importer covers
# 2026-07-01..31 and nothing else. `cleanup()` deletes by (employee, date), so
# every July run was deleting REAL IMPORTED ROWS: 67 of them across the four
# suites before this was caught on 2026-08-11, while every run reported green.
# June carries zero imported Finger Logs and zero Attendance for these employees,
# so a fixture here can only ever delete what it created. It also makes the
# expected values exact, because no imported day can drift into the cell.
D_ABSENT = "2026-06-20"         # a Saturday: Workday by default, punchless -> Absent
D_LEAVE = "2026-06-15"          # a free Monday, NO Finger Log
D_BOTH = "2026-06-18"           # punchless AND later covered by leave — the OD-60 case
D_LATE = "2026-06-22"           # the B3 / A3 probe date
D_REJ = "2026-06-23"            # REJ needs its OWN date — B3 leaves a refused draft
                                # on D_LATE, and stock's overlap check would fire
                                # first, failing REJ1 for the wrong reason


def d(*dates):
    """Render the expected cell for these dates, the way format_day_cell would.

    Derived from the date constants rather than typed as "9, 11": when the dates
    moved from July to June, every hardcoded expectation became a lie at once.
    """
    return ", ".join(str(getdate(x).day) for x in sorted(dates))
LEAVE_TYPE = "Emergency"        # is_lwp -> no allocation needed, and FBR37 counts it

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


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
    """Scoped to this suite's employees, cycle and dates — never by employee
    alone. Purging by employee ate ~50 rows of imported July data once."""
    days = [D_ABSENT, D_LEAVE, D_BOTH, D_LATE, D_REJ]
    for emp in (EMP_A, EMP_B):
        for la in frappe.get_all("Leave Application",
                                 filters={"employee": emp,
                                          "from_date": ("in", days)}, fields=["name"]):
            remove("Leave Application", la.name)
        for a in frappe.get_all("Attendance",
                                filters={"employee": emp,
                                         "attendance_date": ("in", days)}, fields=["name"]):
            remove("Attendance", a.name)
        for f in frappe.get_all("Finger Log",
                                filters={"employee": emp,
                                         "work_date": ("in", days)}, fields=["name"]):
            remove("Finger Log", f.name)
        for s in frappe.get_all("Shift Assignment",
                                filters={"employee": emp,
                                         "start_date": ("in", days)}, fields=["name"]):
            remove("Shift Assignment", s.name)
        for ap in frappe.get_all("Appraisal",
                                 filters={"employee": emp, "appraisal_cycle": CYCLE},
                                 fields=["name"]):
            remove("Appraisal", ap.name)
    frappe.db.commit()


# ------------------------------------------------------------------ fixtures

def make_absent_log(employee, day):
    doc = frappe.new_doc("Finger Log")
    doc.employee = employee
    doc.employee_name = frappe.db.get_value("Employee", employee, "employee_name")
    doc.work_date = day
    for f in ("time_in", "break", "resume", "out"):
        doc.set(f, "00:00:00")
    doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def make_appraisal(employee, submit=True):
    doc = frappe.new_doc("Appraisal")
    doc.employee = employee
    doc.appraisal_cycle = CYCLE
    doc.appraisal_template = TEMPLATE
    doc.flags.caf_skip_supervisor_check = True
    doc.flags.ignore_permissions = True
    doc.insert()
    if submit:
        doc.flags.caf_skip_supervisor_check = True
        doc.submit()
        # The workflow has no Draft -> Completed edge (the real path is
        # Draft -> Pending HR Review -> Completed). What is under test is
        # docstatus, not the workflow, so the state is stamped afterwards.
        # update_modified=False deliberately: test SUBM-b watches `modified`.
        doc.db_set("workflow_state", "Completed", update_modified=False)
    return doc


def file_leave(employee, day, leave_type=LEAVE_TYPE, status="Approved"):
    la = frappe.new_doc("Leave Application")
    la.employee = employee
    la.leave_type = leave_type
    la.from_date = day
    la.to_date = day
    la.status = status
    la.company = frappe.db.get_value("Employee", employee, "company")
    la.flags.ignore_permissions = True
    la.insert()
    la.submit()
    return la


def file_assignment(employee, day, shift):
    sa = frappe.new_doc("Shift Assignment")
    sa.employee = employee
    sa.company = frappe.db.get_value("Employee", employee, "company")
    sa.shift_type = shift
    sa.start_date = day
    sa.end_date = day
    sa.status = "Active"
    sa.flags.ignore_permissions = True
    sa.insert()
    sa.submit()
    return sa


def cell(name, kra="Attendance"):
    doc = frappe.get_doc("Appraisal", name)
    for row in doc.appraisal_kra:
        if row.kra == kra:
            return (row.caf_date_cell or "").strip()
    return None


def versions(name):
    return frappe.db.count("Version", {"ref_doctype": "Appraisal", "docname": name})


def comments(name):
    return frappe.db.count("Comment", {"reference_doctype": "Appraisal",
                                       "reference_name": name, "comment_type": "Comment"})


# ------------------------------------------------------------------ the suite

def run():
    cleanup()

    # Two punchless days -> two Absents -> FBR37's second branch counts 9 and 11.
    make_absent_log(EMP_A, D_ABSENT)
    make_absent_log(EMP_A, D_BOTH)
    app = make_appraisal(EMP_A, submit=True)
    baseline = cell(app.name)
    check("FIX", app.docstatus == 1 and baseline == d(D_BOTH, D_ABSENT),
          f"fixture: appraisal {app.name} submitted, Attendance cell = {baseline!r} "
          f"(days {getdate(D_BOTH).day} and {getdate(D_ABSENT).day} = the punchless days)")

    submitted_at = ar.submitted_on(app.name)
    check("SUBM-a", submitted_at is not None,
          f"submitted_on() found the docstatus 0->1 Version: {submitted_at}")

    # ---------------------------------------------------------------- A2 / A4
    # A late leave ADDS a counted day to an already-submitted appraisal.
    v_before, c_before = versions(app.name), comments(app.name)
    file_leave(EMP_A, D_LEAVE)
    after = cell(app.name)
    check("A4", after == d(D_LEAVE, D_BOTH, D_ABSENT),
          f"late {LEAVE_TYPE} on {D_LEAVE}: cell {baseline!r} -> {after!r} — the number went UP")
    check("A2a", versions(app.name) > v_before,
          f"a Version was written: {v_before} -> {versions(app.name)} (option (a), not db_set)")
    check("A2b", comments(app.name) > c_before,
          f"an OD-26 comment records what changed: {c_before} -> {comments(app.name)}")

    doc = frappe.get_doc("Appraisal", app.name)
    supervisor_text = [(r.caf_description or "", r.caf_root_cause or "",
                        r.caf_corrective_action or "") for r in doc.appraisal_kra]
    check("A2c", all(not any(t) for t in supervisor_text),
          "the supervisor's own columns are untouched by the refresh")

    # ---------------------------------------------------------------- A5
    # 🔴 The direction nobody tests. A late Shift Assignment makes the Saturday a
    # rest day, Chunk 4 cancels the false Absent, and the count must go DOWN.
    sa = file_assignment(EMP_A, D_ABSENT, NO_SAT)
    down = cell(app.name)
    att = frappe.get_all("Attendance",
                         filters={"employee": EMP_A, "attendance_date": D_ABSENT},
                         fields=["name", "status", "docstatus"])
    check("A5", down == d(D_LEAVE, D_BOTH),
          f"late Shift Assignment on {D_ABSENT}: cell {after!r} -> {down!r} — "
          f"the number went DOWN")
    check("A5b", att and att[0].docstatus == 2,
          f"the Absent was CANCELLED not deleted: docstatus={att[0].docstatus if att else None} "
          f"(the row still exists)")

    # ---------------------------------------------------------------- A7
    # OD-60, the easy half: unfiling the assignment must put the day back on the
    # appraisal too. Chunk 4 already reverts the Attendance; this proves the
    # appraisal follows it.
    frappe.get_doc("Shift Assignment", sa.name).cancel()
    back = cell(app.name)
    check("A7", back == d(D_LEAVE, D_BOTH, D_ABSENT),
          f"Shift Assignment cancelled: cell {down!r} -> {back!r} — the day returns")

    # ------------------------------------------------------- A6 / B4 / AUDIT
    # 🔴 OD-60, the half that is NOT two lines. Stock's cancel_attendance()
    # db_sets docstatus = 2, which ERASES the day instead of reverting it: the
    # Absent that stood there before the leave does not come back. So the count
    # must be IDENTICAL before the leave and after the cancel — without
    # restore_day_after_leave() it silently drops to "8, 11".
    before_leave = cell(app.name)
    la = file_leave(EMP_A, D_BOTH)
    covered = cell(app.name)
    on_leave = frappe.get_all("Attendance",
                              filters={"employee": EMP_A, "attendance_date": D_BOTH,
                                       "docstatus": 1},
                              fields=["status", "leave_type"])
    check("B4a", covered == before_leave and covered == d(D_LEAVE, D_BOTH, D_ABSENT)
          and on_leave and on_leave[0].status == "On Leave",
          f"leave over an existing Absent: cell {before_leave!r} -> {covered!r} (unchanged — "
          f"still counted, other branch), attendance now {on_leave[0].status if on_leave else None}")

    frappe.get_doc("Leave Application", la.name).cancel()
    restored = cell(app.name)
    live = frappe.get_all("Attendance",
                          filters={"employee": EMP_A, "attendance_date": D_BOTH,
                                   "docstatus": 1},
                          fields=["name", "status", "leave_type"])
    check("A6", restored == before_leave,
          f"leave CANCELLED: cell {covered!r} -> {restored!r} — back to where it started, "
          f"not down to {d(D_LEAVE, D_ABSENT)!r}")
    check("B4b", len(live) == 1 and live[0].status == "Absent" and not live[0].leave_type,
          f"the day's own verdict is restored: {[(r.status, r.leave_type) for r in live]} "
          f"(exactly one live row, Absent, no leave_type)")

    killed = frappe.get_all("Attendance",
                            filters={"employee": EMP_A, "attendance_date": D_BOTH,
                                     "docstatus": 2}, fields=["name"])
    trail = sum(frappe.db.count("Comment", {"reference_doctype": "Attendance",
                                            "reference_name": r.name,
                                            "comment_type": "Comment"}) for r in killed)
    check("AUDIT", killed and trail > 0,
          f"the row stock db_set to docstatus 2 carries a comment: {len(killed)} cancelled "
          f"row(s), {trail} comment(s) — db_set writes no Version, so this is the only trail")

    # ---------------------------------------------------------------- SUBM-b
    # Two update_after_submit writes have now moved `modified`. The FBR39 window
    # must not have moved with it.
    still = ar.submitted_on(app.name)
    modified = frappe.db.get_value("Appraisal", app.name, "modified")
    check("SUBM-b", still == submitted_at and str(still) != str(modified),
          f"submitted_on() is stable at {still} while modified has moved to {modified} — "
          f"using `modified` would re-open the FBR39 window on every refresh")

    # ---------------------------------------------------------------- IDEM
    res = ar.refresh_submitted_appraisal(app.name, "idempotence probe")
    check("IDEM", res.get("changed") == {},
          f"refreshing an appraisal that already agrees writes nothing: {res}")

    # ---------------------------------------------------------------- LOCK
    # OD-44 (a) unlocked TWO cells. Prove it unlocked no more than two.
    doc = frappe.get_doc("Appraisal", app.name)
    doc.appraisal_kra[0].caf_description = "tampered by a background job"
    locked, err = False, ""
    try:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
    except Exception as e:
        locked, err = type(e).__name__ == "UpdateAfterSubmitError", type(e).__name__
    check("LOCK", locked,
          f"caf_description still refuses update_after_submit ({err or 'NO ERROR — it saved!'})")

    # ---------------------------------------------------------------- A1
    # A backdate landing while the appraisal is a DRAFT needs no OD-44 at all.
    draft = make_appraisal(EMP_B, submit=False)
    skipped = ar.refresh_submitted_appraisal(draft.name, "A1 probe")
    make_absent_log(EMP_B, D_LATE)
    draft.reload()
    draft.flags.caf_skip_supervisor_check = True
    draft.refresh_auto_fill(force=True)
    draft.save(ignore_permissions=True)
    check("A1", "skipped" in skipped and cell(draft.name) == d(D_LATE),
          f"draft appraisal: OD-44 declines it ({skipped.get('skipped')}) and an ordinary "
          f"save picks the day up anyway — cell = {cell(draft.name)!r}")

    # ---------------------------------------------------------------- A3 / B3
    # Age the submit past the FBR39 window and file another leave. It must be
    # REFUSED, and refused in before_submit so nothing is left half-submitted.
    old = add_to_date(submitted_at, months=-2)
    for v in frappe.get_all("Version",
                            filters={"ref_doctype": "Appraisal", "docname": app.name},
                            fields=["name"]):
        frappe.db.set_value("Version", v.name, "creation", old, update_modified=False)
    frappe.db.commit()

    closed, sub, deadline = ar.window_closed(app.name)
    check("B3a", closed and sub == old,
          f"window_closed: submitted {sub}, deadline {deadline}, closed={closed}")

    refused, msg = False, ""
    try:
        file_leave(EMP_A, D_LATE)
    except Exception as e:
        refused, msg = "FBR39" in str(e) or "window has closed" in str(e), str(e)[:110]
    check("B3", refused, f"leave filed past the window is refused: {msg or 'IT WAS ACCEPTED'}")

    stuck = frappe.get_all("Leave Application",
                           filters={"employee": EMP_A, "from_date": D_LATE},
                           fields=["name", "docstatus"])
    check("A3", not any(r.docstatus == 1 for r in stuck),
          f"nothing was left submitted-and-rejected: {stuck or 'no rows at all'} "
          f"(refusing in before_submit, not on_submit)")

    # ---------------------------------------------------------------- B5
    # 🔴 The asymmetry, decided by MG 2026-08-11. The window is shut, yet a
    # CANCEL must still go through: filing asks for something new, cancelling
    # corrects what is already on the record. Refusing here would leave a
    # known-wrong leave standing and the appraisal counting it forever.
    before_cancel = cell(app.name)
    la_early = frappe.get_all("Leave Application",
                              filters={"employee": EMP_A, "from_date": D_LEAVE,
                                       "docstatus": 1}, fields=["name"])
    allowed, why = False, ""
    try:
        frappe.get_doc("Leave Application", la_early[0].name).cancel()
        allowed = True
    except Exception as e:
        why = str(e)[:110]
    check("B5", allowed and cell(app.name) != before_cancel,
          f"cancel past the closed window is ALLOWED and still refreshes: "
          f"cell {before_cancel!r} -> {cell(app.name)!r}{' — REFUSED: ' + why if why else ''}")

    # ---------------------------------------------------------------- REJ
    # 🔴 Raised by MG 2026-08-11, and it was a real defect. A submitted Leave
    # Application is Approved or Rejected, and stock's update_attendance() opens
    # with `if self.status != "Approved": return` — so a REJECTION touches no
    # Attendance at all. FBR39 protects a submitted appraisal from an Attendance
    # change; where there is none, refusing only stops a supervisor recording
    # that they said no. The window is still shut from B3 above.
    before_rej = cell(app.name)
    rejected, rej_err = False, ""
    try:
        rej = file_leave(EMP_A, D_REJ, status="Rejected")
        rejected = rej.docstatus == 1
    except Exception as e:
        rej_err = str(e)[:110]
    check("REJ1", rejected,
          f"a REJECTED leave past the closed window submits fine — FBR39 does not apply"
          f"{' — WRONGLY REFUSED: ' + rej_err if rej_err else ''}")
    check("REJ2", cell(app.name) == before_rej,
          f"and it moves no appraisal cell: {before_rej!r} -> {cell(app.name)!r} "
          f"(stock wrote no Attendance, so there is nothing to recompute)")

    cleanup()
    frappe.db.commit()

    print(f"\n=== Chunk 5 — refreshing a submitted appraisal (cycle {CYCLE}) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:8s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
