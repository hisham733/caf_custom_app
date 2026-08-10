"""OD-61 / OD-62 — the lock the design claimed but never had.

    bench --site <site> execute caf.tests.fingerlog.test_od61_guard.run

WHY
---
Both decisions rested on the same false premise, stated in two register rows and
in spec §7: that `allow_on_submit = 1 + read_only = 1` means *"code may write it
and a person may not"*.

**Measured 2026-08-11, and it does not.** `read_only` is form decoration — forced
to 1, `doc.save()` stored the value with no exception. So is `hidden`.
`set_only_once` is never even checked on child rows. The only field property
Frappe truly enforces is `permlevel`, and it cannot be made conditional on
`docstatus` — which would have killed D3's draft-time manual edit, the same cost
`read_only = 1` would have had if it worked at all.

MG chose the controller guard for both (option (c), 2026-08-11), because it is
the only route that closes the post-submit hole while leaving draft editing alone.

WHAT WOULD SILENTLY REGRESS
---------------------------
The guard has to distinguish the machine from a person. It does that with
`flags.caf_system_write`, set by exactly three callers:

    appraisal_refresh.refresh_submitted_appraisal   the automatic refresh
    appraisal.refresh_auto_fill_action              the "Refresh Data" button
    re_resolve.re_resolve_finger_log                the late-swap re-resolve

**If the guard is too broad it breaks all of Chunks 4, 5 and 5b; if it is too
narrow it protects nothing.** SYS1–SYS3 assert the first, GUARD1–GUARD3 the
second — this file is only meaningful with both halves.

RE-RUNNABLE: artifacts are removed FIRST, not last.
"""

import frappe

from caf.caf import appraisal_refresh, re_resolve

EMP = "HR-EMP-00016"
CYCLE = "2026-06"
TEMPLATE = "CAF Monthly Appraisal"
# 🔴 June: the importer covers July only, and cleanup() deletes by (employee,
# date). Every July run deleted real imported rows — 67 across the four suites.
D_LOG = "2026-06-19"          # a Friday, clear of the other suites' dates

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
    for dt, field in (("Attendance", "attendance_date"), ("Finger Log", "work_date")):
        for r in frappe.get_all(dt, filters={"employee": EMP, field: D_LOG},
                                fields=["name"]):
            remove(dt, r.name)
    for r in frappe.get_all("Appraisal", filters={"employee": EMP,
                                                  "appraisal_cycle": CYCLE},
                            fields=["name"]):
        remove("Appraisal", r.name)
    frappe.db.commit()


def make_log():
    doc = frappe.new_doc("Finger Log")
    doc.employee = EMP
    doc.employee_name = frappe.db.get_value("Employee", EMP, "employee_name")
    doc.work_date = D_LOG
    for f in ("time_in", "break", "resume", "out"):
        doc.set(f, "00:00:00")
    doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def make_appraisal():
    doc = frappe.new_doc("Appraisal")
    doc.employee = EMP
    doc.appraisal_cycle = CYCLE
    doc.appraisal_template = TEMPLATE
    doc.flags.caf_skip_supervisor_check = True
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.flags.caf_skip_supervisor_check = True
    doc.submit()
    return doc


def write(doctype, name, mutate, system=False):
    """The shape a REST PUT arrives in: load, mutate, save."""
    doc = frappe.get_doc(doctype, name)
    mutate(doc)
    doc.flags.caf_skip_supervisor_check = True
    doc.flags.ignore_permissions = True
    if system:
        doc.flags.caf_system_write = True
    try:
        doc.save(ignore_permissions=True)
        return ""
    except Exception as e:
        return type(e).__name__


def run():
    cleanup()
    log = make_log()
    app = make_appraisal()

    # ---------------------------------------------------------------- GUARD3
    # OD-62. final_ot drives overtime pay and was rewritable on a submitted log.
    # from the DB, not the in-memory doc: a Float that was never assigned reads
    # back as None in Python and 0.0 from MariaDB, which failed this assertion
    # once while the guard itself was working perfectly.
    before_ot = frappe.db.get_value("Finger Log", log.name, "final_ot")
    err = write("Finger Log", log.name, lambda d: d.set("final_ot", 99.0))
    stored = frappe.db.get_value("Finger Log", log.name, "final_ot")
    check("GUARD3", err == "ValidationError" and stored == before_ot,
          f"final_ot on a SUBMITTED Finger Log: raised {err or 'NOTHING'}, "
          f"stored still {stored} (was {before_ot}) — OD-62 closed")

    err = write("Finger Log", log.name, lambda d: d.set("day_type", "Holiday"))
    check("GUARD3b", err == "ValidationError"
          and frappe.db.get_value("Finger Log", log.name, "day_type") == log.day_type,
          f"day_type likewise: raised {err or 'NOTHING'}, still "
          f"{frappe.db.get_value('Finger Log', log.name, 'day_type')!r}")

    # HR's own working field is deliberately NOT guarded
    err = write("Finger Log", log.name, lambda d: d.set("caf_hr_review", 1))
    check("GUARD3c", err == "" and frappe.db.get_value("Finger Log", log.name,
                                                       "caf_hr_review") == 1,
          f"but caf_hr_review IS still writable (raised {err or 'nothing'}) — it exists "
          f"for a human to action, so HR keeps a route to clear it")

    # ---------------------------------------------------------------- GUARD1
    # OD-61. The four auto-filled grid cells on a submitted appraisal.
    def tamper_cell(d):
        d.appraisal_kra[0].caf_date_cell = "1, 2, 3"

    err = write("Appraisal", app.name, tamper_cell)
    row0 = frappe.get_doc("Appraisal", app.name).appraisal_kra[0]
    check("GUARD1", err == "ValidationError" and (row0.caf_date_cell or "") != "1, 2, 3",
          f"caf_date_cell on a SUBMITTED appraisal: raised {err or 'NOTHING'}, "
          f"cell still {row0.caf_date_cell!r} — OD-61 closed")

    err = write("Appraisal", app.name,
                lambda d: setattr(d.appraisal_kra[0], "caf_remarks", "forged"))
    check("GUARD1b", err == "ValidationError",
          f"caf_remarks likewise: raised {err or 'NOTHING'}")

    # ---------------------------------------------------------------- GUARD2
    # The supervisor's own columns were ALREADY protected by allow_on_submit = 0,
    # which Frappe does enforce. Different mechanism, so assert it separately.
    err = write("Appraisal", app.name,
                lambda d: setattr(d.appraisal_kra[0], "caf_description", "forged"))
    check("GUARD2", err == "UpdateAfterSubmitError",
          f"the supervisor's own caf_description still raises {err or 'NOTHING'} — "
          f"allow_on_submit = 0, a different lock that Frappe DOES enforce")

    # ---------------------------------------------------------------- SYS
    # 🔴 The other half. A guard that also blocks the machine breaks Chunks 4/5/5b
    # and every one of their tests would fail somewhere far from here.
    err = write("Appraisal", app.name, tamper_cell, system=True)
    check("SYS1", err == "",
          f"with caf_system_write the SAME write goes through (raised "
          f"{err or 'nothing'}) — the guard blocks people, not code")

    res = appraisal_refresh.refresh_submitted_appraisal(app.name, "guard probe")
    check("SYS2", "error" not in res and "skipped" not in res,
          f"refresh_submitted_appraisal still works through the guard: {res}")

    out = re_resolve.re_resolve_finger_log(log.name, "guard probe")
    check("SYS3", "error" not in out,
          f"re_resolve_finger_log still works through the guard: "
          f"changed={out.get('changed')}, attendance={out.get('attendance')}")

    doc = frappe.get_doc("Appraisal", app.name)
    doc.flags.caf_skip_supervisor_check = True
    action = doc.refresh_auto_fill_action()
    check("SYS4", isinstance(action, dict),
          f"the \"Refresh Data\" button's method still works: {str(action)[:80]} "
          f"(hidden in JS once submitted, but reachable by design — it only "
          f"recomputes, it cannot forge)")

    cleanup()
    frappe.db.commit()

    print("\n=== OD-61 / OD-62 — the controller guard ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:9s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
