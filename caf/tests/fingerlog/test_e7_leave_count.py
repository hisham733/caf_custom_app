"""E7 — a leave spanning a swapped Saturday.  ✅ FIXED 2026-08-13 (Chunk 6c), 4/4.

    bench --site <site> execute caf.tests.fingerlog.test_e7_leave_count.run

✅ **NOW IN `run_all()`.** It was written BEFORE the fix and deliberately kept
out of the matrix while it stood at **2/4** — a matrix that is red on purpose is
a matrix nobody reads. E7-GAIN and E7-LOSE were therefore **watched failing for
a known reason and then watched passing**, which is §F3's mutation proof
obtained the right way round: the assertions are known to be capable of going
red, because they were red.

The fix is `caf/caf/leave_days.py`, hooked to Leave Application's `validate`.

Written at MG's instruction (2026-08-13: *"also don't forget to write test for
it"*), so the number was watched rather than remembered.

WHAT IS WRONG, AND WHERE
------------------------
Two systems answer "is this date a working day for X" and only one can see a
Shift Assignment:

    CAF   resolve_day_type()          Shift Assignment -> default_shift -> list
    STOCK get_number_of_leave_days()  Holiday List ONLY

Nothing in CAF is broken — the Finger Log, the Attendance and the roster grid are
all right. Stock's leave arithmetic simply never asks CAF.

⚠️ **It cuts BOTH ways, which is why "it favours the employee" is not a defence:**
the person who gains the working Saturday gets a free leave day, and their mirror
partner, who gains the rest Saturday, is overcharged one.

THE FIX — option C (MG, 2026-08-13)  ✅ BUILT
---------------------------------------------
Not an override of `get_number_of_leave_days()` (option A): that is the function
payroll and allocation also call, and it is whitelisted so the form previews
through it. Instead a hook on **Leave Application's own `validate`** — after
stock computes `total_leave_days`, recount the span through `resolve_day_type`.

✅ **The precondition was CONFIRMED before a line was written**, as this file
demanded. `create_leave_ledger_entry()` builds `leaves=self.total_leave_days *
-1` — derived, not recomputed — and across all **693** submitted applications
**0** disagree with their ledger. The six matches that "pointed that way" are now
693. (47 rows show a ledger summing to zero; every one is an *amended* 2025 row
carrying a reversing pair — document history, not a second source.)

FIXTURES
--------
**2026-08-31 .. 2026-09-05**, not June. June's four Saturdays are all owned by
suites that ARE in the matrix, and neither August nor September holds imported
data — the importer covers 2026-07 only. That is what makes this suite safe to
add to `run_all()` without moving it: it owns dates nothing else touches.
"""

import frappe

from caf.caf import shift_swap
from caf.caf.shift_resolution import resolve_day_type

A = "HR-EMP-00009"          # Seow Zi Ying — 8:30am Alt Sat 1st-3rd
B = "HR-EMP-00010"          # Hazwani      — 8:30am Alt Sat 2nd-4th (her mirror)

SAT = "2026-09-05"          # A rests it, B works it
FROM = "2026-08-31"         # Mon .. Sat = 6 calendar days; 31 Aug is Merdeka Day
LTYPE = "Leave Without Pay"

RESULTS = []
_sa = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def make_leave(employee):
    doc = frappe.new_doc("Leave Application")
    doc.employee = employee
    doc.leave_type = LTYPE
    doc.from_date, doc.to_date = FROM, SAT
    doc.status = "Approved"
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def cleanup():
    # ⚠️ Leave FIRST. The S5/S6 guard refuses to cancel an assignment while
    # approved leave still covers it — correctly — so teardown has to unwind in
    # the opposite order from the one the test builds in.
    for r in frappe.get_all("Leave Application",
                            filters={"employee": ("in", [A, B]),
                                     "from_date": FROM, "to_date": SAT},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Leave Application", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Leave Application", r.name, ignore_permissions=True,
                          force=True)
    frappe.db.commit()

    scope = {"employee": ("in", [A, B]), "start_date": SAT}
    for r in frappe.get_all("Shift Assignment", filters=scope, fields=["name"]):
        frappe.db.set_value("Shift Assignment", r.name, "caf_swap_partner", None,
                            update_modified=False)
    frappe.db.commit()
    for r in frappe.get_all("Shift Assignment", filters=scope, fields=["name"]):
        doc = frappe.get_doc("Shift Assignment", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Shift Assignment", r.name, ignore_permissions=True,
                          force=True)
    _sa.clear()
    frappe.db.commit()


def days(name):
    return frappe.db.get_value("Leave Application", name, "total_leave_days")


def run():
    frappe.set_user("Administrator")
    cleanup()

    try:
        # ── baseline, no swap. This part is CORRECT today and must stay so ──
        la, lb = make_leave(A), make_leave(B)
        base_a, base_b = days(la.name), days(lb.name)
        check("E7-BASE", base_a == 4.0 and base_b == 5.0,
              f"with no swap the count is right: {A} rests {SAT} and is charged "
              f"{base_a} (6 days − Merdeka − her rest Saturday); {B} works it and "
              f"is charged {base_b}. R1 put the routine rest Saturdays into the "
              f"Holiday List, so stock sees them by itself")
        cleanup()

        # ── ordering (1): swap FIRST, then leave. MG: "very possible" ───────
        res = shift_swap.create(SAT, A, B)
        _sa.extend(res["created"])
        day_a, _s = resolve_day_type(A, SAT)
        day_b, _s = resolve_day_type(B, SAT)
        la, lb = make_leave(A), make_leave(B)
        got_a, got_b = days(la.name), days(lb.name)

        check("E7-GAIN", got_a == base_a + 1,
              f"🔴 {A} now WORKS {SAT} (resolve_day_type says {day_a}) so the "
              f"leave should cost {base_a + 1}. Stock charged {got_a} — "
              f"{'correct' if got_a == base_a + 1 else 'a FREE day, because stock reads the Holiday List and the swap is not in it'}")

        check("E7-LOSE", got_b == base_b - 1,
              f"🔴 and it cuts the OTHER way: {B} now RESTS {SAT} "
              f"(resolve_day_type says {day_b}) so the leave should cost "
              f"{base_b - 1}. Stock charged {got_b} — "
              f"{'correct' if got_b == base_b - 1 else 'OVERCHARGED one day. This is why favouring the employee is not a defence'}")

        # ── the ledger follows the document, which is what option C rests on ──
        led_a = [r.leaves for r in frappe.get_all(
            "Leave Ledger Entry", filters={"transaction_name": la.name},
            fields=["leaves"])]
        check("E7-LEDGER", led_a and abs(led_a[0]) == got_a,
              f"the ledger mirrors `total_leave_days` exactly ({led_a} vs "
              f"{got_a}) — so fixing the document in `validate` fixes the "
              f"balance too, which is the whole reason option C is narrower "
              f"than overriding get_number_of_leave_days()")

    finally:
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    print("\n=== E7 — leave over a swapped Saturday (EXPECTED TO FAIL until Chunk 6) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:12s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED (expected until Chunk 6): {failed}" if failed else
             " — 🎉 E7 IS FIXED. Add this suite to run_all()."))
    return not failed
