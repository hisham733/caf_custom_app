"""A Shift Assignment filed over a PAST day. T-45, codified from the L3 climb.

    bench --site <site> execute caf.tests.chain.test_swap_reresolve.run

🔴 WHY THIS EXISTS
-------------------
`test_chunk7_swap` and `test_swap_leave_guard` cover who may file a trade and that
leave refuses one. **Neither walks what a backdated assignment does to a day that
is already submitted** — and that is where the money is.

Measured in a browser 2026-09-12 (`playbooks/L3_swap_ladder.md`): the punches are
never touched, the Attendance row is updated rather than duplicated — and
**2.5 hours of approved overtime went to zero in complete silence.**

WHAT EACH ASSERTION PROTECTS
-----------------------------
    SWP1  the day genuinely re-resolves onto the new shift
    SWP2  🔴 the PUNCHES are never rewritten. The observation is not ours to edit
    SWP3  exactly ONE Attendance row, the SAME document — updated, never
          duplicated, never deleted (spec §6.6)
    SWP4  the run does not throw. One disputed day must not abort a month
    SWP5  🔴 **T-46, asserted AS IT IS TODAY** — approved overtime falls to 0 and
          nothing is flagged
    SWP6  ⚠️ **F11, asserted as it is today** — `Attendance.shift` does not follow

🔴 SWP5 AND SWP6 ARE DELIBERATELY SHAPED TO FLIP. They assert the current, wrong
behaviour so that the code and the register agree about what is true; the day
either is fixed, the assertion goes red and that red is the signal to retire it.
**Neither is this suite's to fix**: T-46 changes what somebody is paid, which is a
standing stop, and it sits beside the open FBR85 decision.
"""

import traceback

import frappe

from caf.tests.chain import dataset

RESULTS = []

NO_OT_SHIFT = "8-4.30 no OT"        # forbids overtime, still works Saturday


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<26}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _log_state(name):
    return frappe.db.get_value(
        "Finger Log", name,
        ["shift_type", "day_type", "caf_work_hours", "short", "ot_in_hour",
         "final_ot", "ot_approval_id", "caf_hr_review", "caf_hr_review_note",
         "time_in", "break", "resume", "out", "overtime"], as_dict=True)


def _rows(emp, day):
    return frappe.get_all("Attendance",
                          filters={"employee": emp, "attendance_date": day},
                          fields=["name", "docstatus", "status", "shift"],
                          order_by="creation")


def _cleanup(emp, day):
    for r in frappe.get_all("Shift Assignment",
                            filters={"employee": emp, "start_date": day},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Shift Assignment", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Shift Assignment", r.name, force=True,
                          ignore_permissions=True)
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
    for r in dataset._ot_approvals(emp, [day]):
        doc = frappe.get_doc("OT Approval", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("OT Approval", r.name, force=True,
                          ignore_permissions=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    emp = dataset.employee("OLD", required=False)
    if not emp:
        print("SKIPPED — the cast does not resolve on this site (dataset.CAST)")
        return True
    if not frappe.db.exists("Shift Type", NO_OT_SHIFT):
        print(f"SKIPPED — no shift named {NO_OT_SHIFT!r} on this site. The lever "
              f"is a shift with caf_allow_ot = 0; pick another and say so here.")
        return True

    day = dataset.free_workdays(emp, 1)[0]
    home = frappe.db.get_value("Employee", emp, "default_shift")

    try:
        _cleanup(emp, day)

        log = dataset._log(emp, day, ot=dataset.OT_CLOCKED)
        appr = dataset._approval(emp, day, 3.0)      # covers the clocked 2.5
        log.reload()
        log.submit()
        frappe.db.commit()
        before, rows_before = _log_state(log.name), _rows(emp, day)

        from caf.caf import shift_swap
        frappe.set_user("natalie@caffood.com")       # only HR may file one
        shift_swap.create(day, emp, None, NO_OT_SHIFT)
        frappe.set_user("Administrator")
        frappe.db.commit()
        after, rows_after = _log_state(log.name), _rows(emp, day)

        check("SWP1-RESOLVES", after.shift_type == NO_OT_SHIFT
              and before.shift_type == home,
              f"the past day re-resolved onto the assigned shift: "
              f"{before.shift_type!r} ➜ {after.shift_type!r} "
              f"(day type {before.day_type} ➜ {after.day_type})")

        punches = ("time_in", "break", "resume", "out", "overtime")
        same = {f: str(before.get(f)) == str(after.get(f)) for f in punches}
        check("SWP2-PUNCHES-UNTOUCHED", all(same.values()),
              f"🔴 the PUNCHES are never rewritten — {same}. Everything derived "
              f"from them is recomputed; the observation itself is not ours to "
              f"edit, and a re-resolve that rewrote it would destroy the only "
              f"record of what the machine saw")

        check("SWP3-ONE-ROW-SAME-DOC",
              len(rows_before) == 1 and len(rows_after) == 1
              and rows_before[0].name == rows_after[0].name
              and rows_after[0].docstatus == 1,
              f"exactly one Attendance before and after, and the SAME document "
              f"({rows_after[0].name}) — updated, not duplicated, not deleted "
              f"(spec §6.6: cancelled never deleted)")

        check("SWP4-RUN-DOES-NOT-STOP", True,
              "the assignment submitted and the re-resolve returned — no "
              "exception reached the caller. One disputed day must never abort a "
              "month's worth of re-resolution")

        # ── 🔴 T-46, asserted as it is TODAY ───────────────────────────────
        fell = float(before.final_ot or 0) > float(after.final_ot or 0)
        silent = not after.caf_hr_review and not (after.caf_hr_review_note or "")
        appr_alive = frappe.db.get_value("OT Approval", appr.name,
                                         "docstatus") == 1
        check("SWP5-T46-OT-FALLS-SILENTLY", fell and silent and appr_alive,
              f"🔴 **T-46, ASSERTED AS IT IS TODAY, NOT AS IT SHOULD BE** — "
              f"final_ot {before.final_ot} ➜ {after.final_ot} while OT Approval "
              f"{appr.name} is still submitted, and caf_hr_review is "
              f"{after.caf_hr_review} with an empty note. ⭐ `_ot_coverage()` only "
              f"asks whether clocked OT is COVERED, and 0 always is — it never "
              f"asks whether approved OT DISAPPEARED. **When that downward check "
              f"is built this assertion flips, and the flip is the signal to "
              f"retire it.** Not fixed here: it changes what somebody is PAID")

        # ── ⚠️ F11, asserted as it is today ────────────────────────────────
        check("SWP6-F11-ATT-SHIFT-STALE",
              rows_after[0].shift == before.shift_type
              and rows_after[0].shift != after.shift_type,
              f"⚠️ **F11, asserted as it is today** — the Finger Log moved to "
              f"{after.shift_type!r} and its Attendance still reads "
              f"{rows_after[0].shift!r}. `reconcile_attendance()` updates `status` "
              f"when it differs and never touches `shift`. Same family as T-44: a "
              f"row asserting something that is no longer true. CAF's reports read "
              f"the shift from the Finger Log, so nothing visible is wrong today")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        _cleanup(emp, day)
        left = frappe.db.count("Shift Assignment",
                               {"employee": emp, "start_date": day,
                                "docstatus": ("<", 2)})
        now_home = frappe.db.get_value("Employee", emp, "default_shift")
        check("SWP-RESTORE", left == 0 and now_home == home,
              f"the site is back as found — {left} live Shift Assignment(s) on "
              f"{day} (must be 0) and default_shift still {now_home!r}. A suite "
              f"that leaves an assignment behind moves a real person's roster")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
