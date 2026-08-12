"""Seed the ONE trade that is actually in the imported data.  Chunk 7.5.

MG: *"since shift_assignment.doc is empty ... just create some based on real log
of emp currently assigned to the mirror shift_type that has alt sat ... find two
emp that so happen that they don't follow the alt sat trend."*

Found, and it is unambiguous. July 2026, punches only — the facts, nothing
derived:

                       04 Jul   11 Jul   18 Jul   25 Jul
    GROUP A  Too Poh     ---      IN       IN      ---     <- off pattern
    1st-3rd  Najwa        IN     ---       IN      ---
             Seow         IN     ---       IN      ---
    GROUP B  Afiza       ---      IN      ---       IN
    2nd-4th  Nurfarahayu  IN     ---      ---       IN     <- off pattern
             Hazwani     ---      IN      ---       IN

Group A works the 4th and 18th, group B the 11th and 25th — a clean alternation,
**except that Too Poh Chin and Nurfarahayu are exchanged on the 4th and the
11th**. He took the 4th off and worked the 11th; she took his 4th and rested the
11th. That is a reciprocal swap over two Saturdays, and it is the only
disagreement in the month.

🔴 **Filing it REMOVES a disagreement rather than creating one.** Measured
2026-08-12 across all 8 employees x 4 Saturdays = 32 cells: 29 agree with live
`resolve_day_type()`, and the 3 that do not are exactly this trade. Without the
assignments, the next re-resolve, re-import or cancel-and-amend writes the WRONG
value into those logs — and a Restday with punches becomes an all-OT day under
FBR4.

    before        3 cells where stored day_type != live resolution
    after         0

⚠️ It is deliberately BACKDATED, which is the second thing MG wanted tested:
`on_submit` runs Chunk 4's re-resolve and Chunk 5's appraisal refresh, so this
exercises the whole late-filing path (scenario S1) on real data. Too Poh Chin's
04 Jul is a false `Absent` today — a rest day recorded as an absence, the exact
error class that produced 287 of them in Chunk 3 — and filing this cancels it.

Run:
    bench --site development.localhost execute caf.scripts.seed_july_swap.run
"""

import frappe
from frappe.utils import getdate

from caf.caf import shift_swap

# Both are on the 8:30am family, on opposite mirrors, so `plan()` reads Swap
# from `caf_sat_mirror` without being told.
A = "HR-EMP-00003"          # Too Poh Chin    — 8:30am Alt Sat 1st-3rd
B = "HR-EMP-00007"          # Nurfarahayu     — 8:30am Alt Sat 2nd-4th
DATES = ["2026-07-04", "2026-07-11"]


def already_filed(work_date):
    return frappe.db.exists("Shift Assignment", {
        "employee": A, "start_date": getdate(work_date), "docstatus": 1})


def run():
    print(f"Shift Assignments before: {frappe.db.count('Shift Assignment')}")

    for d in DATES:
        if already_filed(d):
            print(f"  {d}  already filed — skipped")
            continue
        res = shift_swap.create(d, A, B)
        print(f"  {d}  {res['kind']}: {', '.join(res['created'])}")

    print(f"Shift Assignments after:  {frappe.db.count('Shift Assignment')}")
    _report()


def _report():
    """What the trade did to the two employees' day types."""
    from caf.caf.shift_resolution import resolve_day_type

    print("\n%-12s %-16s %-9s %-9s %s" % ("date", "employee", "live", "stored", "punch"))
    for d in DATES:
        for emp, label in ((A, "Too Poh Chin"), (B, "Nurfarahayu")):
            live, _shift = resolve_day_type(emp, d)
            log = frappe.db.get_value(
                "Finger Log", {"employee": emp, "work_date": getdate(d), "docstatus": ["<", 2]},
                ["day_type", "time_in"], as_dict=True)
            punch = "in" if (log and str(log.time_in) not in ("0:00:00", "00:00:00")) else "--"
            agree = "" if (log and log.day_type == live) else "   <-- STILL STALE"
            print("%-12s %-16s %-9s %-9s %s%s" % (
                d, label, live, log.day_type if log else "(none)", punch, agree))


def undo():
    """Cancel what `run()` filed. `cancel_both` handles the pairing."""
    for d in DATES:
        name = frappe.db.get_value("Shift Assignment", {
            "employee": A, "start_date": getdate(d), "docstatus": 1})
        if name:
            print(f"  cancelling pair on {d}")
            shift_swap.cancel_both(name)
    print(f"Shift Assignments now: {frappe.db.count('Shift Assignment', {'docstatus': 1})}")
