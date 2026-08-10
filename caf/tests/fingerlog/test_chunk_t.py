"""Chunk T — the enriched fixture, and the coverage no chunk had.

    bench --site <site> execute caf.tests.fingerlog.test_chunk_t.run

WHY THIS FILE EXISTS
--------------------
MG reviewed the Chunk 5 fixture on 2026-08-11 and asked four things: is
`final_ot` ever non-zero, is there a Present as well as an Absent, does a swap
onto a **Mon–Fri** shift work, and is a late leave ever something other than MC.
Checked against the site rather than from memory, and three of the four were
real holes:

  🔴 **The OT Hours and Punctuality cells were `''` in all 23 Chunk 5
     assertions.** Every Finger Log in that fixture is punchless with
     `overtime = 0`, so `get_ot_hours()` summed nothing and `get_late_dates()`
     had no late punch to find. `refresh_submitted_appraisal()` writes **three**
     KRA cells and exactly **one** had ever been proven to move.

  🔴 **Counted leave was the only leave tested.** FBR37 counts MC, Leave Without
     Pay, MC Without Pay and Emergency — and **not** Annual, Sick Leave or PH
     Replacment. So a late *Annual* over an `Absent` day REMOVES a counted day:
     the number goes DOWN via a leave application, the opposite of A4, and in
     the same silent direction as A5.

  🔴 **Only one direction of the swap.** Chunk 5's A5 goes Saturday-working ➜
     Mon–Fri (`8am Schedule` ➜ `8am no OT no Sat`), which cancels a false
     Absent. The reverse — a Mon–Fri employee put onto a Saturday shift — turns
     a rest day into a workday and *creates* one.

T-KEEP is not from MG's list; it came out of building this. Measured on
2026-08-11: live appraisal `HR-APR-2026-00094` stores `13, 30` in its Attendance
cell while the current data computes `''`, because dev only carries July
Attendance. `refresh_auto_fill(force=True)` would blank it. A5 needs `force=True`
to work at all, so the risk is structural, not hypothetical: **a refresh
triggered for one cell rewrites all three.**

RE-RUNNABLE: artifacts are removed FIRST, not last.
"""

import frappe
from frappe.utils import getdate

from caf.caf.overrides import appraisal as ap

EMP_A = "HR-EMP-00016"        # 8am Schedule    — Mon–Sat, caf_allow_ot 1, 08:00–16:30
EMP_C = "HR-EMP-00127"        # 8am no OT no Sat — Mon–Fri, Saturday is a rest day
NO_OT_SHIFT = "8am no OT no Sat"
SAT_SHIFT = "8am Schedule"
CYCLE = "2026-07"
TEMPLATE = "CAF Monthly Appraisal"
MARKER = "CHUNK T TEST"

D_OT = "2026-07-20"           # Mon — punches + 2.0 h APPROVED OT  -> the OT Hours cell
D_LATEP = "2026-07-21"        # Tue — a late punch                 -> the Punctuality cell
D_ABS = "2026-07-23"          # Thu — punchless -> Absent          -> the uncounted-leave case
D_SAT = "2026-07-25"          # Sat — EMP_C's rest day             -> the REVERSE swap

UNCOUNTED = "Annual"          # deliberately NOT in caf_attendance_leave_codes

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
    """Scoped to this suite's employees, dates and cycle — never by employee
    alone. Purging by employee ate ~50 rows of imported July data once, and the
    run reported green while doing it."""
    days = [D_OT, D_LATEP, D_ABS, D_SAT]
    for emp in (EMP_A, EMP_C):
        for dt, field in (("Leave Application", "from_date"),
                          ("Attendance", "attendance_date"),
                          ("Finger Log", "work_date"),
                          ("Shift Assignment", "start_date")):
            for r in frappe.get_all(dt, filters={"employee": emp, field: ("in", days)},
                                    fields=["name"]):
                remove(dt, r.name)
        for r in frappe.get_all("Appraisal", filters={"employee": emp,
                                                      "appraisal_cycle": CYCLE},
                                fields=["name"]):
            remove("Appraisal", r.name)
    for r in frappe.get_all("OT Approval", filters={"reason": ("like", f"%{MARKER}%")},
                            fields=["name"]):
        remove("OT Approval", r.name)
    frappe.db.commit()


# ------------------------------------------------------------------ fixtures

def make_approval(emp, day, duration, start_work, ot_end):
    """`check_ot_duration()` recomputes duration from (ot_end − start_work) minus
    the shift's own hours and REFUSES a mismatch, so both times must be real.
    EMP_A works 08:00–16:30 = 8.5 h, so 18:30 gives exactly 2.0 h."""
    doc = frappe.new_doc("OT Approval")
    doc.work_date = day
    doc.type = "normal"
    doc.ot_department = frappe.db.get_value("Employee", emp, "department")
    doc.reason = MARKER
    doc.append("emp_list", {"emp_id": emp, "work_date": day, "ot_duration": duration,
                            "start_work": start_work, "ot_end": ot_end})
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def make_log(emp, day, time_in=None, out=None, overtime=0):
    doc = frappe.new_doc("Finger Log")
    doc.employee = emp
    doc.employee_name = frappe.db.get_value("Employee", emp, "employee_name")
    doc.work_date = day
    if time_in:
        doc.time_in, doc.out = time_in, out
        doc.set("break", "12:00:00")
        doc.resume = "13:00:00"
    else:
        for f in ("time_in", "break", "resume", "out"):
            doc.set(f, "00:00:00")
    doc.overtime = overtime
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def make_appraisal(emp):
    doc = frappe.new_doc("Appraisal")
    doc.employee = emp
    doc.appraisal_cycle = CYCLE
    doc.appraisal_template = TEMPLATE
    doc.flags.caf_skip_supervisor_check = True
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.flags.caf_skip_supervisor_check = True
    doc.submit()
    doc.db_set("workflow_state", "Completed", update_modified=False)
    return doc


def file_leave(emp, day, leave_type):
    la = frappe.new_doc("Leave Application")
    la.employee = emp
    la.leave_type = leave_type
    la.from_date = day
    la.to_date = day
    la.status = "Approved"
    la.company = frappe.db.get_value("Employee", emp, "company")
    la.flags.ignore_permissions = True
    la.insert()
    la.submit()
    return la


def file_assignment(emp, day, shift):
    sa = frappe.new_doc("Shift Assignment")
    sa.employee = emp
    sa.company = frappe.db.get_value("Employee", emp, "company")
    sa.shift_type = shift
    sa.start_date = day
    sa.end_date = day
    sa.status = "Active"
    sa.flags.ignore_permissions = True
    sa.insert()
    sa.submit()
    return sa


def cells(name):
    doc = frappe.get_doc("Appraisal", name)
    return {r.kra: (r.caf_date_cell or "").strip()
            for r in doc.appraisal_kra if r.kra in ap.AUTO_FILLED_KRAS}


# ------------------------------------------------------------------ the suite

def run():
    cleanup()

    # -------------------------------------------------- the enriched fixture
    make_approval(EMP_A, D_OT, 2.0, "08:00:00", "18:30:00")
    ot_log = make_log(EMP_A, D_OT, "08:00:00", "18:30:00", overtime=2.0)
    make_log(EMP_A, D_LATEP, "09:15:00", "16:30:00")     # 75 minutes late
    make_log(EMP_A, D_ABS)                                # punchless -> Absent

    app = make_appraisal(EMP_A)
    base = cells(app.name)
    check("T-FIX", ot_log.final_ot == 2.0
          and base["Attendance"] == "23" and base["Punctuality"] == "21"
          and base["OT Hours"] == "2 h",
          f"the fixture is finally rich enough: final_ot={ot_log.final_ot}, cells={base} "
          f"— all THREE auto-filled cells populated, where Chunk 5 only ever moved one")

    # -------------------------------------------------- T-OT · the OT cell moves
    # A late swap onto a caf_allow_ot = 0 shift. Chunk 4 recomputes ot_in_hour and
    # final_ot; the appraisal's OT Hours cell must follow it DOWN.
    file_assignment(EMP_A, D_OT, NO_OT_SHIFT)
    ot_log.reload()
    after = cells(app.name)
    check("T-OT", after["OT Hours"] == "" and ot_log.final_ot == 0,
          f"swap onto a no-OT shift: OT Hours {base['OT Hours']!r} -> "
          f"{after['OT Hours']!r}, Finger Log final_ot {ot_log.final_ot} — "
          f"the second of the three cells is now proven to move")

    # -------------------------------------------------- T-KEEP · nothing blanked
    # `force=True` rewrites all three cells on every refresh, so a cell that is
    # still correct must survive a refresh triggered for a different one.
    check("T-KEEP", after["Punctuality"] == base["Punctuality"] == "21"
          and after["Attendance"] == base["Attendance"],
          f"the untouched cells survived the refresh: Punctuality "
          f"{after['Punctuality']!r}, Attendance {after['Attendance']!r} "
          f"(force=True rewrites all three — a stale computation would blank them)")

    # -------------------------------------------------- T-UNC · uncounted leave
    # 🔴 The direction MG asked for. Annual is NOT in caf_attendance_leave_codes,
    # so covering an Absent with it REMOVES a counted day — the number goes DOWN
    # via a leave application, the opposite of A4.
    before_unc = cells(app.name)["Attendance"]
    file_leave(EMP_A, D_ABS, UNCOUNTED)
    unc = cells(app.name)["Attendance"]
    att = frappe.get_all("Attendance",
                         filters={"employee": EMP_A, "attendance_date": D_ABS,
                                  "docstatus": 1},
                         fields=["status", "leave_type"])
    check("T-UNC", before_unc == "23" and unc == ""
          and att and att[0].leave_type == UNCOUNTED,
          f"late {UNCOUNTED} over an Absent: Attendance cell {before_unc!r} -> {unc!r} "
          f"— DOWN via a leave application, because {UNCOUNTED} is not a counted code "
          f"(row is now {att[0].status if att else None}/{att[0].leave_type if att else None})")

    codes = ap.attendance_leave_codes()
    check("T-UNC2", UNCOUNTED not in codes and "MC" in codes,
          f"and that is data, not code: caf_attendance_leave_codes = {codes}")

    # -------------------------------------------------- T-REV · the reverse swap
    # Chunk 5's A5 goes Sat-working -> Mon–Fri and CANCELS an Absent. This is the
    # other way: a Mon–Fri man put onto a Saturday shift, turning a rest day into
    # a workday and CREATING one.
    rest_log = make_log(EMP_C, D_SAT)
    app_c = make_appraisal(EMP_C)
    base_c = cells(app_c.name)["Attendance"]
    pre = frappe.get_all("Attendance", filters={"employee": EMP_C,
                                                "attendance_date": D_SAT,
                                                "docstatus": 1}, fields=["name"])
    check("T-REV1", rest_log.day_type == "Restday" and not pre,
          f"before the swap: {D_SAT} is a {rest_log.day_type} for {EMP_C} and carries "
          f"NO Attendance — a rest day is not an absence")

    file_assignment(EMP_C, D_SAT, SAT_SHIFT)
    rest_log.reload()
    post = frappe.get_all("Attendance", filters={"employee": EMP_C,
                                                 "attendance_date": D_SAT,
                                                 "docstatus": 1},
                          fields=["name", "status"])
    after_c = cells(app_c.name)["Attendance"]
    check("T-REV2", rest_log.day_type == "Workday" and post
          and post[0].status == "Absent" and after_c == "25" and base_c != after_c,
          f"reverse swap onto {SAT_SHIFT}: day_type {rest_log.day_type}, attendance "
          f"{post[0].status if post else None}, appraisal cell {base_c!r} -> {after_c!r} "
          f"— an Absent is CREATED and the number goes UP")

    cleanup()
    frappe.db.commit()

    print(f"\n=== Chunk T — enriched fixture (cycle {CYCLE}) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:9s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed


def run_all():
    """The whole matrix, in dependency order. Chunk T's other job."""
    import sys

    from caf.tests.fingerlog import (test_chunk3_decisions, test_chunk4_reresolve,
                                     test_chunk5_appraisal)
    # `__import__(__name__)` returns the top-level `caf` package, not this module.
    out = []
    for name, mod in (("chunk 3 decisions", test_chunk3_decisions),
                      ("chunk 4 re-resolve", test_chunk4_reresolve),
                      ("chunk 5 + 5b appraisal", test_chunk5_appraisal),
                      ("chunk T enriched", sys.modules[__name__])):
        mod.RESULTS.clear()
        ok = mod.run()
        out.append((name, ok, len(mod.RESULTS),
                    len([1 for _, o, _ in mod.RESULTS if not o])))
    print("\n=== THE WHOLE MATRIX ===")
    for name, ok, total, failed in out:
        print(f"   {name:26s} {total - failed}/{total} {'PASS' if ok else 'FAIL'}")
    return all(o for _, o, _, _ in out)
