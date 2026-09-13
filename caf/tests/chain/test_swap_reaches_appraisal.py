"""Does a backdated swap reach a SUBMITTED appraisal? T-45, L3 rung 3.8.

    bench --site <site> execute caf.tests.chain.test_swap_reaches_appraisal.run

🔴 WHY THIS EXISTS — the rung L3 could not measure
---------------------------------------------------
The L3 climb (2026-09-12) walked a backdated Shift Assignment end to end and had
to stop one rung short: **no submitted appraisal covered its test days**, so the
refresh could only be shown not to fail. MG, 2026-09-13: *"possible that you
select a day and emp based on FL.doc already imported, then run a script to submit
an appraisal, hence creating a data point for the ladder?"* — yes, and that is
what this does.

WHAT IT TAKES FOR THE RUNG TO MEAN ANYTHING
--------------------------------------------
⚠️ A swap only reaches the appraisal if it changes **something the appraisal
counts**, and the appraisal counts **absence days** (FBR37 — `status = Absent`
with no leave_type, plus the listed leave codes). Moving a day between two
ordinary shifts changes the hours and nothing the appraisal reads.

So the day here is deliberately:

    a SATURDAY   ·  nobody punched  ·  submitted  ->  Attendance `Absent`
         │
         │  a Shift Assignment onto a shift that does NOT work Saturdays
         ▼
    the day becomes a REST DAY  ->  `should_have_attendance` is false
                                ->  the Absent row is CANCELLED
                                ->  the absence the appraisal counted is gone

⭐ **A rest day is not an absence.** He was never rostered, so there is nothing to
answer for — and an `Absent` left standing there would sit on his appraisal.

⚠️ Self-cleaning, and the appraisal it builds is removed in the `finally`.
"""

import traceback

import frappe
from frappe.utils import getdate

from caf.tests.chain import dataset

RESULTS = []

TEMPLATE = "CAF Monthly Appraisal"
REST_SHIFT = "8:30am no Sat"        # caf_work_sat = 0 — the lever


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<26}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _saturday(emp, tries=16):
    for d in dataset.free_workdays(emp, tries):
        if getdate(d).weekday() == 5:
            return d
    return None


def _cells(name):
    """The auto-filled grid cells. They live on the KRA CHILD rows, never the
    parent — a probe that reads the parent finds nothing and reports no change."""
    doc = frappe.get_doc("Appraisal", name)
    return {r.kra: r.get("caf_date_cell") for r in (doc.get("appraisal_kra") or [])}


def _cleanup(emp, day, cycle):
    for r in frappe.get_all("Shift Assignment",
                            filters={"employee": emp, "start_date": day},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Shift Assignment", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Shift Assignment", r.name, force=True,
                          ignore_permissions=True)
    for r in frappe.get_all("Appraisal",
                            filters={"employee": emp, "appraisal_cycle": cycle},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Appraisal", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.flags.caf_skip_supervisor_check = True
            doc.cancel()
        frappe.delete_doc("Appraisal", r.name, force=True, ignore_permissions=True)
    for dt, field in (("Attendance", "attendance_date"),
                      ("Finger Log", "work_date")):
        for r in frappe.get_all(dt, filters={"employee": emp, field: day},
                                fields=["name", "docstatus"]):
            doc = frappe.get_doc(dt, r.name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.flags.ignore_links = True
                doc.flags.caf_skip_leave_guard = True
                doc.cancel()
            frappe.delete_doc(dt, r.name, force=True, ignore_permissions=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    emp = dataset.employee("OLD", required=False)
    if not emp:
        print("SKIPPED — the cast does not resolve on this site (dataset.CAST)")
        return True
    if not frappe.db.exists("Shift Type", REST_SHIFT):
        print(f"SKIPPED — no shift named {REST_SHIFT!r}. The lever is any shift "
              f"with caf_work_sat = 0; name another one here.")
        return True

    day = _saturday(emp)
    if not day:
        print("SKIPPED — no clear SATURDAY for the cast in the search window. "
              "The rung needs one: only a Saturday can become a rest day by "
              "moving to a no-Saturday shift.")
        return True
    cycle = day[:7]
    if not frappe.db.exists("Appraisal Cycle", cycle):
        print(f"SKIPPED — no Appraisal Cycle {cycle!r} on this site.")
        return True

    try:
        _cleanup(emp, day, cycle)

        # ── an ABSENT Saturday, submitted ──────────────────────────────────
        log = dataset._log(emp, day, absent=True)
        log.submit()
        frappe.db.commit()
        att = frappe.db.get_value("Attendance",
                                  {"employee": emp, "attendance_date": day,
                                   "docstatus": 1},
                                  ["name", "status"], as_dict=True)
        check("APR1-ABSENT-EXISTS", bool(att) and att.status == "Absent",
              f"the day starts as an absence the appraisal will count — "
              f"{att and att.name} ({att and att.status}) on {day}")

        # ── a SUBMITTED appraisal for that cycle ───────────────────────────
        apr = frappe.new_doc("Appraisal")
        apr.employee = emp
        apr.appraisal_cycle = cycle
        apr.appraisal_template = TEMPLATE
        apr.flags.caf_skip_supervisor_check = True
        apr.flags.ignore_permissions = True
        apr.insert()
        apr.flags.caf_skip_supervisor_check = True
        apr.submit()
        frappe.db.commit()
        before = _cells(apr.name)
        before_mod = frappe.db.get_value("Appraisal", apr.name, "modified")
        check("APR2-SUBMITTED", frappe.db.get_value("Appraisal", apr.name,
                                                    "docstatus") == 1,
              f"an appraisal for {cycle} is SUBMITTED ({apr.name}) and its "
              f"auto-filled cells read {before}. ⚠️ The cells live on the KRA "
              f"CHILD rows — a probe reading the parent finds nothing and reports "
              f"no change")

        # ── the backdated swap that makes the day a rest day ───────────────
        from caf.caf import shift_swap
        frappe.set_user("natalie@caffood.com")
        shift_swap.create(day, emp, None, REST_SHIFT)
        frappe.set_user("Administrator")
        frappe.db.commit()

        live = frappe.db.count("Attendance", {"employee": emp,
                                              "attendance_date": day,
                                              "docstatus": 1})
        check("APR3-ABSENT-CANCELLED", live == 0,
              f"the day became a rest day, so the Absent row was CANCELLED "
              f"({live} live row(s) left). ⭐ A rest day is not an absence — he "
              f"was never rostered, and an Absent left standing there would sit "
              f"on his appraisal")

        after = _cells(apr.name)
        after_mod = frappe.db.get_value("Appraisal", apr.name, "modified")
        check("APR4-APPRAISAL-REFRESHED",
              after != before or after_mod != before_mod,
              f"🔴 **THE RUNG L3 COULD NOT REACH** — the SUBMITTED appraisal "
              f"followed the swap: cells {before} ➜ {after} (modified "
              f"{before_mod} ➜ {after_mod}). A backdated roster change that left "
              f"a signed-off appraisal counting an absence that no longer exists "
              f"is exactly what FBR39/OD-44 exist to prevent")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        _cleanup(emp, day, cycle)
        left = frappe.db.count("Appraisal", {"employee": emp,
                                             "appraisal_cycle": cycle,
                                             "docstatus": ("<", 2)})
        check("APR-RESTORE", left == 0,
              f"the appraisal this suite built is gone ({left} left, must be 0). "
              f"It is a fixture, not a record of anybody's performance")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
