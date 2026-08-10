"""Chunk 4 — a late Shift Assignment corrects the past. Scenarios S1-S4, E5.

    bench --site <site> execute caf.tests.fingerlog.test_chunk4_reresolve.run

The trap this suite exists for is **S3**: `check_ot_approval()` throws, which is
right for an interactive submit and wrong for a batch. One uncovered row must
not abort every remaining employee.

RE-RUNNABLE: artifacts are removed FIRST, not last.
"""

import frappe
from frappe.utils import add_days, getdate, nowdate

from caf.caf import re_resolve

EMP_A = "HR-EMP-00016"   # 8am Schedule - works Saturday, OT allowed
NO_SAT = "8am no OT no Sat"
SAT = None               # resolved below

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


def past_saturday():
    """A fixed Saturday that the employee's default shift works.

    🔴 It used to be computed from `nowdate()` — two Saturdays ago — which on
    2026-08-11 resolved to **2026-07-25, inside the imported month**. `cleanup()`
    then deleted that day's imported Finger Log on every run. A moving date cannot
    be checked against the import window, so it is pinned instead.

    2026-06-13: a Saturday, a workday under `CAF Mon-Sat 2026`, a rest day under
    `CAF Mon-Fri 2026` (which is what the swap tests need), carrying no seeded OT
    Approval for this employee, and in a month the importer never touched.
    """
    return getdate("2026-06-13")


def cleanup(day):
    for a in frappe.get_all("Attendance",
                            filters={"employee": EMP_A, "attendance_date": day},
                            fields=["name"]):
        remove("Attendance", a.name)
    for f in frappe.get_all("Finger Log",
                            filters={"employee": EMP_A, "work_date": day},
                            fields=["name"]):
        remove("Finger Log", f.name)
    for s in frappe.get_all("Shift Assignment",
                            filters={"employee": EMP_A, "start_date": day},
                            fields=["name"]):
        remove("Shift Assignment", s.name)
    frappe.db.commit()


def make_log(day, punched):
    doc = frappe.new_doc("Finger Log")
    doc.employee = EMP_A
    doc.employee_name = frappe.db.get_value("Employee", EMP_A, "employee_name")
    doc.work_date = day
    if punched:
        doc.time_in, doc.out = "08:00:00", "16:30:00"
        doc.set("break", "12:00:00")
        doc.resume = "13:00:00"
        doc.overtime = 0
    else:
        for f in ("time_in", "break", "resume", "out"):
            doc.set(f, "00:00:00")
        doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def file_assignment(day, shift):
    sa = frappe.new_doc("Shift Assignment")
    sa.employee = EMP_A
    sa.company = frappe.db.get_value("Employee", EMP_A, "company")
    sa.shift_type = shift
    sa.start_date = day
    sa.end_date = day
    sa.status = "Active"
    sa.flags.ignore_permissions = True
    sa.insert()
    sa.submit()
    return sa


def versions(name):
    return frappe.db.count("Version", {"ref_doctype": "Finger Log", "docname": name})


def run():
    day = past_saturday()

    # ---------------------------------------------------------------- S1
    # He did NOT punch. The Saturday looked like a workday, so the import marked
    # him Absent. The swap is filed later: that Absent was never true.
    cleanup(day)
    log = make_log(day, punched=False)
    att = frappe.get_all("Attendance", filters={"caf_finger_log": log.name},
                         fields=["name", "status", "docstatus"])
    before_v = versions(log.name)
    check("S1a", log.day_type == "Workday" and att and att[0].status == "Absent",
          f"before the swap: day_type={log.day_type}, attendance={att[0].status if att else None}")

    file_assignment(day, NO_SAT)
    log.reload()
    after = frappe.db.get_value("Attendance", att[0].name, ["status", "docstatus"], as_dict=True)
    check("S1b", log.day_type == "Restday" and after.docstatus == 2,
          f"after the swap: day_type={log.day_type}, attendance docstatus={after.docstatus} "
          f"(2 = cancelled, NOT deleted)")
    check("S1c", frappe.db.exists("Attendance", att[0].name) is not None,
          "the Attendance row still EXISTS - cancelled, never deleted (spec §6.6)")
    check("S1d", versions(log.name) > before_v,
          f"a Version records the Finger Log change: {before_v} -> {versions(log.name)}")

    # ---------------------------------------------------------------- S4
    # Cancel the assignment: the day must revert, with no orphan.
    sa = frappe.get_all("Shift Assignment",
                        filters={"employee": EMP_A, "start_date": day, "docstatus": 1},
                        fields=["name"])
    frappe.get_doc("Shift Assignment", sa[0].name).cancel()
    log.reload()
    live = frappe.get_all("Attendance",
                          filters={"employee": EMP_A, "attendance_date": day, "docstatus": 1},
                          fields=["name", "status"])
    check("S4", log.day_type == "Workday" and len(live) == 1 and live[0].status == "Absent",
          f"assignment cancelled -> day_type={log.day_type}, "
          f"live attendance={[r.status for r in live]} (exactly one Absent, no orphans)")

    # ---------------------------------------------------------------- S2
    # He DID punch. The swap changes his shift; he stays Present, but the
    # derived numbers must move.
    cleanup(day)
    log = make_log(day, punched=True)
    att = frappe.get_all("Attendance", filters={"caf_finger_log": log.name},
                         fields=["name", "status"])
    before = (log.day_type, log.shift_type, log.caf_work_hours)
    file_assignment(day, NO_SAT)
    log.reload()
    still = frappe.db.get_value("Attendance", att[0].name, ["status", "docstatus"], as_dict=True)
    check("S2", log.day_type == "Restday" and log.shift_type == NO_SAT
          and still.docstatus == 1 and still.status == "Present",
          f"punched: {before} -> ({log.day_type}, {log.shift_type}, {log.caf_work_hours}); "
          f"attendance stays {still.status} docstatus={still.docstatus}")
    check("FDR10", log.time_in and str(log.time_in) != "0:00:00" and log.out,
          f"punches untouched by the re-resolve: in={log.time_in} out={log.out}")

    # ---------------------------------------------------------------- S3
    # OT that is no longer covered. This MUST flag, not throw - a batch has to
    # survive one bad row.
    cleanup(day)
    log = make_log(day, punched=True)
    log.db_set("overtime", 2.0)          # clocked OT with no approval anywhere
    threw = False
    try:
        res = re_resolve.re_resolve_finger_log(log.name, "S3 probe")
    except Exception as e:
        threw = True
        res = {"error": str(e)}
    log.reload()
    check("S3", not threw and log.caf_hr_review == 1,
          f"uncovered OT -> threw={threw} (must be False), caf_hr_review={log.caf_hr_review}, "
          f"note={(log.caf_hr_review_note or '')[:60]}")

    # and the batch keeps going after a flagged row
    batch = re_resolve.re_resolve_assignment(
        frappe._dict(employee=EMP_A, start_date=day, end_date=day, name="probe"),
        reason="S3 batch")
    check("S3b", batch["logs"] >= 1 and not any("error" in r for r in batch["results"]),
          f"batch continued past the flagged row: {batch['logs']} log(s), "
          f"flagged={len(batch['flagged_for_hr'])}, errors=0")

    # ---------------------------------------------------------------- E5
    # Cancel + amend once Attendance links to the log.
    cleanup(day)
    log = make_log(day, punched=True)
    att_name = frappe.get_all("Attendance", filters={"caf_finger_log": log.name},
                              fields=["name"])[0].name
    log.reload()
    log.flags.ignore_links = True
    log.flags.ignore_permissions = True
    log.cancel()
    att_after = frappe.db.get_value("Attendance", att_name, "docstatus")
    amended = frappe.copy_doc(log)
    amended.amended_from = log.name
    amended.flags.ignore_permissions = True
    amended.insert()
    check("E5", att_after == 2 and str(amended.time_in) == str(log.time_in)
          and str(amended.out) == str(log.out),
          f"cancel cascaded (attendance docstatus={att_after}); amend carried the punches "
          f"across unchanged (no_copy is 0): in={amended.time_in} out={amended.out}")

    cleanup(day)
    frappe.db.commit()

    print(f"\n=== Chunk 4 — re-resolve (test Saturday {day}) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:7s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
