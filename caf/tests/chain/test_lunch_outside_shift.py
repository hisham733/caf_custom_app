"""A lunch punched AFTER the shift ends, on a shift that pays no overtime.

    bench --site <site> execute caf.tests.chain.test_lunch_outside_shift.run

🔴 WHY THIS EXISTS — MG asked for it, 2026-09-13
-------------------------------------------------
*"for emp.shift_type.allow_ot = FALSE, create fl with lunch out that is > ST.end,
then see how fl behaves."*

⭐ **Written as a MEASUREMENT, not as an expectation.** Neither of us knew what the
right answer was, so this records what the code actually does and asserts only the
invariants we are sure of. When the behaviour is decided, the decision replaces
the report here.

WHAT THE FORMULA ACTUALLY IS — and it is not the obvious one
-------------------------------------------------------------
MG's reading was `work = (out − in) − lunch`. ⚠️ That is **elapsed time**, and
`work_hours.py` measured it against 24,963 real rows: it matched **10**. The real
formula is the part of the SCHEDULED shift that was served:

    work  = min(out, shift_end) − max(in, shift_start) − lunch   clamped to [0, net]
    net   = (shift_end − shift_start) − the shift's lunch allowance
    short = net − work

🔴 **And `lunch` is the ACTUAL gap between the two lunch punches when both exist**,
not the allowance. That is deliberate — people who took a longer lunch than the
allowance were the residual mismatch against Ingress — but it is also what makes
this question interesting: **a lunch taken after the shift has already ended is
still subtracted from the contracted day.**

So on a shift that pays no overtime, somebody who stays late and takes their break
during that late period can be credited with FEWER contracted hours for it.
"""

import traceback

import frappe

from caf.caf import work_hours
from caf.caf.shift_resolution import get_shift_params
from caf.tests.chain import dataset

RESULTS = []

NO_OT_SHIFT = "8-4.30 no OT"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<26}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def run():
    frappe.set_user("Administrator")
    if not frappe.db.exists("Shift Type", NO_OT_SHIFT):
        print(f"SKIPPED — no shift named {NO_OT_SHIFT!r}; the lever is any shift "
              f"with caf_allow_ot = 0.")
        return True

    p = get_shift_params(NO_OT_SHIFT)
    start = work_hours.to_minutes(p.get("start_time"))
    end = work_hours.to_minutes(p.get("end_time"))
    allowance = int(p.get("caf_lunch_minutes") or 0)
    net = max(0, end - start - allowance)

    print(f"\n{NO_OT_SHIFT}: {_hhmm(start)}–{_hhmm(end)}, lunch allowance "
          f"{allowance} min, so a full day is net {net} min = {net / 60.0} h\n")

    shapes = [
        ("lunch INSIDE the shift, normal length",
         _hhmm(start), _hhmm(start + 240), _hhmm(start + 300), _hhmm(end + 210)),
        ("lunch STARTS AFTER the shift ended, 60 min",
         _hhmm(start), _hhmm(end + 60), _hhmm(end + 120), _hhmm(end + 210)),
        ("lunch STARTS AFTER the shift ended, 150 min",
         _hhmm(start), _hhmm(end + 60), _hhmm(end + 210), _hhmm(end + 240)),
        ("lunch STRADDLES the shift end",
         _hhmm(start), _hhmm(end - 30), _hhmm(end + 90), _hhmm(end + 210)),
    ]

    print(f"  {'shape':<44}{'work':<8}{'short':<8}{'work+short':<12}lunch used")
    rows = []
    for label, i, b, r, o in shapes:
        work, short = work_hours.compute(i, b, r, o, p)
        used = work_hours.to_minutes(r) - work_hours.to_minutes(b)
        rows.append((label, work, short, used))
        print(f"  {label:<44}{work:<8}{short:<8}"
              f"{round((work or 0) + (short or 0), 4):<12}{used} min")

    check("LOS1-CHECKSUM-HOLDS",
          all(abs(((w or 0) + (s or 0)) * 60 - net) < 1 for _l, w, s, _u in rows),
          f"`work + short = net` holds to the minute in every shape — that pair is "
          f"the import's own checksum, and a shape that broke it would mean the "
          f"day no longer adds up")

    inside = rows[0]
    after60 = rows[1]
    after150 = rows[2]

    check("LOS2-LATE-LUNCH-COSTS-THE-SAME",
          abs((inside[1] or 0) - (after60[1] or 0)) < 0.001,
          f"a 60-minute lunch taken AFTER the shift ended costs exactly what one "
          f"taken during it costs — both give work={inside[1]} h. ⭐ Because the "
          f"deduction is the lunch's LENGTH, not its position, and 60 happens to "
          f"equal this shift's allowance")

    check("LOS3-A-LONG-LATE-LUNCH-EATS-CONTRACTED-HOURS",
          (after150[1] or 0) < (inside[1] or 0),
          f"🔴 **THE ANSWER TO MG'S QUESTION.** A **150-minute** break taken "
          f"entirely AFTER the shift ended drops the contracted day from "
          f"{inside[1]} h to {after150[1]} h and reports {after150[2]} h SHORT — "
          f"even though every minute of it fell outside the scheduled shift. "
          f"⚠️ On a shift that pays **no overtime** the employee therefore gets no "
          f"credit for staying AND loses contracted hours for the break they took "
          f"while staying. The formula deducts the lunch's length wherever it "
          f"happened; it never asks whether the break was inside the window")

    # ── and the same shape through a real Finger Log ───────────────────────
    emp = frappe.db.get_value("Employee", {"default_shift": NO_OT_SHIFT,
                                           "status": "Active"}, "name")
    if not emp:
        print(f"\nSKIPPED the live half — nobody is on {NO_OT_SHIFT!r} today, so "
              f"a Finger Log cannot be built against it without moving somebody.")
    else:
        day = dataset.free_workdays(emp, 1)[0]
        try:
            d = frappe.new_doc("Finger Log")
            d.employee = emp
            d.work_date = day
            d.time_in = _hhmm(start)
            d.set("break", _hhmm(end + 60))
            d.resume = _hhmm(end + 210)
            d.out = _hhmm(end + 240)
            d.overtime = 3.0
            d.flags.ignore_permissions = True
            d.insert(ignore_permissions=True)
            d.reload()
            check("LOS4-LIVE-LOG-AGREES",
                  abs(float(d.caf_work_hours) - (after150[1] or 0)) < 0.01
                  and float(d.ot_in_hour or 0) == 0.0,
                  f"a real Finger Log on {day} for {emp} agrees: "
                  f"caf_work_hours={d.caf_work_hours}, short={d.short}, and "
                  f"ot_in_hour={d.ot_in_hour} — **three clocked overtime hours "
                  f"come to nothing**, because the shift forbids overtime "
                  f"(FBR36/FDR7). The day is not held: the punches are complete, "
                  f"so `caf_not_full_day`={d.caf_not_full_day}")
        finally:
            for r in frappe.get_all("Finger Log",
                                    filters={"employee": emp, "work_date": day},
                                    fields=["name"]):
                frappe.delete_doc("Finger Log", r.name, force=True,
                                  ignore_permissions=True)
            frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
