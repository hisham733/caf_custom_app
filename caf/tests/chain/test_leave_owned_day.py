"""A Finger Log cancel may not take an approved leave's day with it. T-44.

    bench --site <site> execute caf.tests.chain.test_leave_owned_day.run

🔴 WHY THIS EXISTS — the L2 climb, 2026-09-12
----------------------------------------------
`cancel_attendance()` selects `WHERE caf_finger_log = <log>` and used to set
`caf_skip_leave_guard = True` unconditionally, on the stated assumption that
*"FL-created rows carry no leave_type (FDR4)"*. **The assumption is false.** When
a late leave lands on a day whose Attendance is `Absent`, stock reconciles **the
same row** to `On Leave` and leaves `caf_finger_log` in place — so the cascade
selected it, switched the guard off, and cancelled an approved leave's day with
nobody told.

⚠️ **Measured both ways before it was fixed.** Through the DESK it never fired:
Frappe's *"Cancel All Documents"* cascade calls a plain `att.cancel()`, so D-12
refused. It fired only on the PROGRAMMATIC route — re-resolve, the API, `bench` —
which is the one nobody watches. **So a test is the only thing that can hold it.**

WHAT EACH ASSERTION PROTECTS
----------------------------
    LOD1  the guard does not OVER-REACH — a plain day still cascades
    LOD2  🔴 the actual hole: a leave-owned day survives the log's cancel
    LOD3  D-12's front door still refuses a direct cancel
    LOD4  a STRAY row (its leave since cancelled) is still correctable — the
          repair route D-12 deliberately leaves open

⚠️ Self-cleaning: builds its own days and removes them in `finally`.
🔴 It does NOT assert that `caf_finger_log` is cleared. Whether the link should
go when leave takes the day is a design decision about which source owns a day,
and it is MG's — `test_chunk3_decisions` FDR4 stays red until he takes it.
"""

import traceback

import frappe
from frappe.utils import strip_html

from caf.tests.chain import dataset

RESULTS = []

PLAIN_DAY = "2026-06-29"        # measured clear for the cast, like L1/L2's days
LEAVE_DAY = "2026-06-30"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<20}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _att(emp, date):
    return frappe.db.get_value(
        "Attendance", {"employee": emp, "attendance_date": date},
        ["name", "docstatus", "status", "leave_type", "leave_application",
         "caf_finger_log"],
        as_dict=True)


def _cleanup(emp):
    for date in (PLAIN_DAY, LEAVE_DAY):
        for dt, field in (("Leave Application", "from_date"),
                          ("Attendance", "attendance_date"),
                          ("Finger Log", "work_date")):
            for r in frappe.get_all(dt, filters={"employee": emp, field: date},
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
        print("SKIPPED — the cast does not resolve on this site (see dataset.CAST)")
        return True

    try:
        _cleanup(emp)                      # artifacts first, so a crash is survivable

        # ── LOD1 — a PLAIN day still cascades ──────────────────────────────
        plain = dataset._log(emp, PLAIN_DAY, absent=True)
        plain.submit()
        before = _att(emp, PLAIN_DAY)
        plain.reload()
        plain.flags.ignore_permissions = True
        plain.cancel()
        after = _att(emp, PLAIN_DAY)
        check("LOD1", before and before.docstatus == 1 and after.docstatus == 2,
              f"a day NO leave owns still cascades: Attendance {before and before.name} "
              f"went docstatus {before and before.docstatus} -> {after and after.docstatus}. "
              f"The fix must not close the ordinary correction route — that is what "
              f"`caf_skip_leave_guard` is legitimately for")

        # ── the leave-owned day ────────────────────────────────────────────
        if not frappe.db.exists("Leave Allocation",
                                {"employee": emp, "leave_type": dataset.LEAVE_TYPE,
                                 "docstatus": 1}):
            print("SKIPPED LOD2-4 — no submitted allocation, so no leave can be "
                  "approved and the hole cannot be reproduced")
            return not [t for t, ok, _d in RESULTS if not ok]

        log = dataset._log(emp, LEAVE_DAY, absent=True)
        log.submit()
        la = dataset._leave(emp, LEAVE_DAY)
        row = _att(emp, LEAVE_DAY)
        # ⚠️ `_att()` must SELECT caf_finger_log for this: a frappe._dict returns
        # None for any attribute it was never given, so `hasattr` is always True
        # and an unselected field reads as absent. That cost this suite a false
        # FAIL on its first run.
        check("LOD2a", bool(row) and row.status == "On Leave"
              and row.leave_application == la.name and bool(row.caf_finger_log),
              f"the starting state T-44 is about: the SAME row was reconciled to "
              f"{row and row.status}/{row and row.leave_type}, belongs to "
              f"{row and row.leave_application}, AND still carries "
              f"caf_finger_log={row and row.caf_finger_log} — the double claim")

        # 🔴 the hole itself, on the route that used to open it
        log.reload()
        log.flags.ignore_permissions = True
        log.cancel()
        after = _att(emp, LEAVE_DAY)
        la_state = frappe.db.get_value("Leave Application", la.name,
                                       ["docstatus", "status"], as_dict=True)
        check("LOD2", after and after.docstatus == 1 and la_state.docstatus == 1,
              f"🔴 THE HOLE: cancelling the Finger Log PROGRAMMATICALLY left the "
              f"leave's day standing — Attendance docstatus {after and after.docstatus} "
              f"(must be 1) while {la.name} is {la_state.status}. Before the fix this "
              f"was docstatus 2 with the leave still Approved: the day silently left "
              f"FBR37's count while the leave said it was taken")

        # ── LOD3 — D-12's front door is unchanged ──────────────────────────
        refused = ""
        att = frappe.get_doc("Attendance", after.name)
        att.flags.ignore_permissions = True
        try:
            att.cancel()
        except Exception as e:
            refused = strip_html(str(e))
        check("LOD3", "still approved" in refused and la.name in refused,
              f"a DIRECT cancel of the leave-owned row is still refused by name — "
              f"{refused[:90]!r}. The fix added a second lock; it did not replace "
              f"the first")

        # ── LOD4 — a STRAY row stays correctable ───────────────────────────
        la_doc = frappe.get_doc("Leave Application", la.name)
        la_doc.flags.ignore_permissions = True
        la_doc.cancel()
        stray = frappe.get_all(
            "Attendance", filters={"employee": emp, "attendance_date": LEAVE_DAY,
                                   "docstatus": 1},
            fields=["name", "leave_type", "leave_application"])
        from caf.caf.attendance_verdict import leave_owns_the_day
        still_owned = [r.name for r in stray if leave_owns_the_day(r)]
        check("LOD4", not still_owned,
              f"once the leave is cancelled the day is nobody's — {len(stray)} live "
              f"row(s), {len(still_owned)} still reported as leave-owned. D-12 leaves "
              f"this route open on purpose: a stray row after a leave cancel must "
              f"stay repairable, or the only way to tidy it is closed too")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        _cleanup(emp)

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
