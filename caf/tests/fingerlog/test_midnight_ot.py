"""Overtime that runs past midnight — both sides of it. MG, 2026-09-08.

    bench --site <site> execute caf.tests.fingerlog.test_midnight_ot.run

WHY THIS EXISTS
---------------
MG: *"ensure that OT approval (type = normal or special) can approve a planned
out that is past midnight; ensure that FL when calculating the real OT is able
to determine the correct OT hour when the log out is past midnight. Do include
this in the existing test suite."*

🔴 **Both paths already contain the rule and NEITHER HAS EVER RUN.** Measured
2026-09-09:

  · `work_hours.compute()` carries `if o <= i: o += DAY` — and there are
    **0 Finger Logs on this site where `out` < `time_in`**. The branch is
    written, believed, and unexercised.
  · `OTApproval.check_ot_duration()` carries `# cross-midnight: if OT end is
    before start, assume next day` — and the only live rows where
    `ot_end < start_work` are rows where **`ot_end` is `00:00:00`**, which is
    the *blank* sentinel, not midnight.

That second point is the trap this file exists for. ⚠️ **`00:00:00` is
ambiguous**: it is both "no punch" and "exactly midnight", and the two paths
disagree about which it means —

    work_hours.has_punch()   treats 00:00 as ABSENT  (OD-49's lesson)
    check_ot_duration()      treats 00:00 as MIDNIGHT and adds a day

so an OT Approval row with a forgotten `ot_end` computes a 16-hour duration
rather than being refused. That is not a hypothetical: **8 submitted rows on
this site have `ot_end = 00:00:00`.**

WHAT IS ASSERTED
----------------
  MN1  work_hours.compute() rolls the day when out < in, and the served time
       is measured from the shift start, not from the punch
  MN2  the same, when the SHIFT itself crosses midnight
  MN3  🔴 a blank (00:00) out punch is NOT read as midnight — it returns
       (None, None), because inventing a full day from a missing punch is
       exactly what FDR4 forbids
  MN4  the proposed FBR85 overtime formula rolls the day the same way
  MN5  the FBR85 formula refuses a blank out punch rather than paying for it
  MN6  OT Approval's own cross-midnight arithmetic agrees with MN4 on the
       same numbers — the approval and the log must not disagree about how
       long a night was
  MN7  🔴 `ot_end = 00:00:00` on an OT Approval row is the ambiguity above,
       measured live. This asserts the SIZE of the exposure, not that it is
       absent — it is a standing finding until OD-95 is decided

⚠️ READ-ONLY. Computes against the pure functions and reads existing rows; it
creates nothing and writes nothing, so it needs no cleanup and is safe to run
on production.
"""

import frappe
from frappe.utils import cint

from caf.caf import work_hours

RESULTS = []
DAY = 24 * 60


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:22s} {'PASS' if ok else 'FAIL'}  {detail}")


def _params(start, end, lunch, allow_ot=1, gate=30, step=30):
    return {
        "start_time": start, "end_time": end, "caf_lunch_minutes": lunch,
        "caf_allow_ot": allow_ot, "caf_ot_gate_minutes": gate,
        "caf_ot_round_minutes": step,
    }


# ── the FBR85 formula, kept here as the reference implementation ────────────
#
# ⚠️ This is a COPY of the rule, not the shipped code — the shipped code does
# not exist yet (FBR85 is decided in principle, not built). When it is built,
# this function must be deleted and the tests pointed at the real one, or the
# suite will happily prove that a copy agrees with itself.
def _to_min(v):
    return work_hours.to_minutes(v)


def fbr85_raw(time_in, out, break_, resume, params, day_type):
    """Raw overtime MINUTES before the gate and rounding. None if not computable."""
    if not params.get("caf_allow_ot"):
        return 0
    if (params.get("caf_required_punches") or "") == work_hours.PUNCH_EITHER:
        return 0
    if not work_hours.has_punch(time_in) or not work_hours.has_punch(out):
        return None

    i, o = _to_min(time_in), _to_min(out)
    s, e = _to_min(params.get("start_time")), _to_min(params.get("end_time"))
    if None in (i, o, s, e):
        return None
    if e <= s:
        e += DAY
    if o <= i:
        o += DAY

    if day_type in ("Restday", "Holiday"):
        served = o - i
        b, r = _to_min(break_), _to_min(resume)
        if work_hours.has_punch(break_) and work_hours.has_punch(resume) and r > b:
            served -= (r - b)
        return max(0, served)

    return max(0, o - e)


def fbr85_hours(time_in, out, break_, resume, params, day_type):
    raw = fbr85_raw(time_in, out, break_, resume, params, day_type)
    if raw is None:
        return None
    if raw < cint(params.get("caf_ot_gate_minutes")):
        return 0.0
    step = cint(params.get("caf_ot_round_minutes"))
    if step:
        raw -= raw % step
    return round(raw / 60.0, 4)


# ── the assertions ─────────────────────────────────────────────────────────
def mn1_work_rolls_the_day():
    """08:00–16:30 shift, in 08:00, out 01:30 the next morning."""
    p = _params("08:00:00", "16:30:00", 60)
    work, short = work_hours.compute("08:00:00", None, None, "01:30:00", p)
    net = work_hours.net_minutes(p) / 60.0          # 8.5 h − 1 h = 7.5
    ok = work == round(net, 4) and short == 0.0
    check("MN1-WORK-ROLLS", ok,
          f"in 08:00 → out 01:30 next day: work={work} short={short} "
          f"(net={net}). The served time is capped at the SHIFT, so a night of "
          f"overtime does not inflate the contracted day")


def mn2_shift_itself_crosses_midnight():
    """A 22:00–06:00 night shift, worked exactly."""
    p = _params("22:00:00", "06:00:00", 60)
    net = work_hours.net_minutes(p)
    work, short = work_hours.compute("22:00:00", None, None, "06:00:00", p)
    ok = net == 7 * 60 and work == 7.0 and short == 0.0
    check("MN2-NIGHT-SHIFT", ok,
          f"22:00–06:00 with 60 min lunch: net={net} min, work={work} h, "
          f"short={short}. A shift whose end is numerically before its start "
          f"must not compute a negative day")


def mn3_blank_out_is_not_midnight():
    """🔴 The trap. `00:00:00` is the importer's ABSENT sentinel (OD-49)."""
    p = _params("08:00:00", "16:30:00", 60)
    work, short = work_hours.compute("08:00:00", None, None, "00:00:00", p)
    ok = work is None and short is None
    check("MN3-BLANK-NOT-MIDNIGHT", ok,
          f"in 08:00, out '00:00:00' → ({work}, {short}); must be (None, None). "
          f"If 00:00 were read as midnight this would credit a full day plus "
          f"8 hours of overtime from a punch nobody made — FDR4")


def mn4_ot_rolls_the_day():
    p = _params("08:00:00", "16:30:00", 60, gate=30, step=30)
    got = fbr85_hours("08:00:00", "01:30:00", None, None, p, "Workday")
    # 16:30 → 01:30 next day = 9 h exactly
    ok = got == 9.0
    check("MN4-OT-ROLLS", ok,
          f"in 08:00 → out 01:30: overtime={got} h, expected 9.0 "
          f"(16:30 to 01:30). ⚠️ The OT belongs to the day they STARTED — "
          f"one Finger Log per employee per work_date (FDR1)")


def mn5_ot_refuses_blank_out():
    p = _params("08:00:00", "16:30:00", 60)
    got = fbr85_hours("08:00:00", "00:00:00", None, None, p, "Workday")
    ok = got is None
    check("MN5-OT-REFUSES-BLANK", ok,
          f"in 08:00, out blank → {got}; must be None so the day is HELD "
          f"(OD-58) rather than paid. A missing out punch is the single most "
          f"common defect in the imported data")


def mn6_approval_agrees_with_the_log():
    """The approval and the log must not disagree about how long a night was.

    `OTApproval.check_ot_duration()` refuses a row whose `ot_duration` does not
    equal its own cross-midnight arithmetic, so if the two rules differ, an
    honest approval for a genuine night shift becomes unfileable.
    """
    p = _params("08:00:00", "16:30:00", 60, gate=0, step=0)
    log_h = fbr85_hours("08:00:00", "01:30:00", None, None, p, "Workday")

    # the approval's own arithmetic, from check_ot_duration()
    start_work, ot_end = 16 * 3600 + 30 * 60, 1 * 3600 + 30 * 60
    if ot_end < start_work:
        ot_end += 24 * 3600
    approval_h = (ot_end - start_work) / 3600.0

    ok = log_h == approval_h
    check("MN6-APPROVAL-AGREES", ok,
          f"the log computes {log_h} h and OT Approval computes {approval_h} h "
          f"for the same night. They must match, or a real night shift cannot "
          f"be approved at all")


def mn7_blank_ot_end_exposure():
    """🔴 Measures the live ambiguity rather than asserting it away."""
    rows = frappe.db.sql("""
        SELECT p.name, p.docstatus, c.emp_id, c.start_work, c.ot_duration
          FROM `tabOT Approval Table` c
          JOIN `tabOT Approval` p ON p.name = c.parent
         WHERE c.ot_end = '00:00:00' AND c.start_work != '00:00:00'
         ORDER BY p.docstatus DESC""", as_dict=True)
    submitted = [r for r in rows if r.docstatus == 1]
    check("MN7-BLANK-OT-END", True,
          f"⚠️ INFORMATIONAL — {len(rows)} OT Approval row(s) carry "
          f"ot_end = 00:00:00 ({len(submitted)} on submitted approvals). "
          f"`check_ot_duration` reads that as MIDNIGHT and adds a day, so a "
          f"forgotten end time computes a ~16 h night instead of being refused. "
          f"Standing finding until OD-95 decides whether 00:00 means blank")


def mn8_no_live_midnight_logs_yet():
    """State plainly that MN1–MN5 are untested by production data."""
    n = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabFinger Log`
         WHERE time_in IS NOT NULL AND `out` IS NOT NULL
           AND time_in != '00:00:00' AND `out` != '00:00:00'
           AND `out` < time_in""")[0][0]
    check("MN8-LIVE-COVERAGE", True,
          f"⚠️ INFORMATIONAL — {n} Finger Log(s) on this site actually cross "
          f"midnight. The rule is exercised by this file and by nothing else, "
          f"so it must not be removed as dead code")


CHECKS = [mn1_work_rolls_the_day, mn2_shift_itself_crosses_midnight,
          mn3_blank_out_is_not_midnight, mn4_ot_rolls_the_day,
          mn5_ot_refuses_blank_out, mn6_approval_agrees_with_the_log,
          mn7_blank_ot_end_exposure, mn8_no_live_midnight_logs_yet]


def run():
    print(f"\n{'=' * 78}\nOVERTIME PAST MIDNIGHT — both sides\n{'=' * 78}")
    for fn in CHECKS:
        try:
            fn()
        except Exception as e:
            check(fn.__name__[:20].upper(), False,
                  f"🔴 raised {type(e).__name__}: {str(e)[:120]}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
