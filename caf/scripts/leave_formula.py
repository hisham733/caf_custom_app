"""HR's pro-rating formula for service under 2 years — and whether it fits.

Purpose : encode the rule HR gave MG on 2026-08-13, then CHECK it against the
          allocations already in ERPNext rather than assuming it holds.
Run     : bench --site <site> execute caf.scripts.leave_formula.verify
Refs    : FBR29/30/31 · P-6 · LEAVE_POLICY_for_HR_confirmation.html

HR'S RULE, AS GIVEN
-------------------
Two time windows, and this is the part that was missing:

    HR CYCLE        1 Jan - 31 Dec, the same for everybody
    SERVICE WINDOW  join date -> 31 Dec of the cycle being allocated

The service window is measured to the END OF THE CYCLE, not to its start —
which is why somebody who joined in July 2025 gets 17 months of credit in the
2026 cycle, not 5.

    months = completed months from join_date to 31 Dec of the cycle year
    AL     = months / 12 * 8
    MC     = months / 12 * 14

and once the service window reaches 24 months the flat bands take over
(2-5y: 12 / 18 · >5y: 16 / 22).

⚠️ SEPARATE FROM ALLOCATION: an employee with under **one year** of service may
not TAKE annual leave at all — it shows as 0 and they use MC or unpaid. So the
number allocated and the number usable are two different things, and only the
first is computed here.

🔴 TWO DETAILS THE DATA SETTLED, NOT HR
---------------------------------------
MG's note said *"round down — 3.9 = 4"*, which is round **up**, so the rounding
had to be derived. Fitted against the eight employees under two years:

  · **completed MONTHS, not fractional years.** Nafiz joined 13 Apr 2026; to
    13 Dec is 8 completed months, and 8/12 x 14 = 9.33 -> **9**, which is what
    he has. Counting 262 days gives 10.05 -> 10, which he does not.
  · **floor to the nearest HALF day, not to a whole one.** 22 months gives
    22/12 x 8 = 14.667. Floored to a whole day that is 14; floored to a half it
    is **14.5** — and both employees at 22 months hold exactly 14.5.

  With those two, the formula reproduces **six of six** under-2-year annual
  figures that HR has not flagged as special. See `verify()` for the rest.

⚠️ **MC APPEARS TO CAP AT THE BAND VALUE (14).** Everyone with 12+ months of
service holds exactly 14, though the raw formula would give 19, 21, 26. Only
Nafiz, at 8 months, is below the cap and holds the formula's own answer. Stated
as an observation, not as HR's rule — it needs confirming.

Changelog
---------
1.0  2026-08-13  Initial — HR's formula via MG, rounding derived from the data
"""

import math
from datetime import date

import frappe
from frappe.utils import getdate

AL_CONSTANT = 8
MC_CONSTANT = 14
MC_BAND_CAP = 14          # observed, not stated by HR — see the module note

BANDS = {                 # service at cycle end -> (annual, medical)
    "2-5": (12, 18),
    "5+": (16, 22),
}


def floor_half(x):
    """Down to the nearest half day. Derived from the data, not from the brief."""
    return math.floor(x * 2) / 2


def completed_months(start, end):
    """Whole months from `start` to `end`, discarding the part month.

    13 Apr -> 31 Dec is 8 (to 13 Dec), not 8.6.
    """
    start, end = getdate(start), getdate(end)
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def entitlement(join_date, cycle_year):
    """What HR's rule gives this person for this cycle."""
    cycle_end = date(int(cycle_year), 12, 31)
    months = completed_months(join_date, cycle_end)

    if months >= 60:
        al, mc = BANDS["5+"]
        return {"months": months, "al": al, "mc": mc, "rule": ">5y band"}
    if months >= 24:
        al, mc = BANDS["2-5"]
        return {"months": months, "al": al, "mc": mc, "rule": "2-5y band"}

    al = floor_half(months / 12 * AL_CONSTANT)
    mc = floor_half(months / 12 * MC_CONSTANT)
    capped = min(mc, MC_BAND_CAP)
    return {"months": months, "al": al, "mc": capped,
            "mc_uncapped": mc, "rule": "pro-rated"}


def entitlement_exact_days(join_date, cycle_year):
    """MG's literal reading of HR: exact days, then round DOWN to a whole day.

    Kept alongside `entitlement()` so the two can be scored against the same
    records rather than argued about. HR describes exact dates; MG doubts the
    arithmetic is done that precisely by hand. `compare_methods()` settles it.
    """
    cycle_end = date(int(cycle_year), 12, 31)
    days = (cycle_end - getdate(join_date)).days
    if days < 0:
        days = 0
    months_equiv = days / 365 * 12

    if months_equiv >= 60:
        al, mc = BANDS["5+"]
        return {"al": al, "mc": mc, "days": days, "rule": ">5y band"}
    if months_equiv >= 24:
        al, mc = BANDS["2-5"]
        return {"al": al, "mc": mc, "days": days, "rule": "2-5y band"}

    al = math.floor(days / 365 * AL_CONSTANT)
    mc = math.floor(days / 365 * MC_CONSTANT)
    return {"al": al, "mc": min(mc, MC_BAND_CAP), "days": days, "rule": "pro-rated"}


def compare_methods(cycle_year=2026):
    """Score both readings against what is actually recorded.

    MG: *"your month + round to 0.5 approach produces 85% fit, right?"* — close;
    the exact number is printed here, next to the alternative, so the choice is
    made on evidence rather than on which description sounds more official.
    """
    got = actual(cycle_year)
    score = {"months_half": [0, 0, 0, 0], "exact_days": [0, 0, 0, 0]}   # al_ok, al_n, mc_ok, mc_n
    detail = []
    for emp, days in got.items():
        e = frappe.db.get_value("Employee", emp,
                                ["employee_name", "date_of_joining"], as_dict=True)
        if not e or not e.date_of_joining:
            continue
        a = entitlement(e.date_of_joining, cycle_year)
        b = entitlement_exact_days(e.date_of_joining, cycle_year)
        row = {"name": e.employee_name, "joined": str(e.date_of_joining),
               "al_actual": days.get("Annual"), "mc_actual": days.get("MC"),
               "al_m": a["al"], "mc_m": a["mc"], "al_d": b["al"], "mc_d": b["mc"]}
        for key, al, mc in (("months_half", a["al"], a["mc"]),
                            ("exact_days", b["al"], b["mc"])):
            if row["al_actual"] is not None:
                score[key][1] += 1
                if abs(row["al_actual"] - al) < .01:
                    score[key][0] += 1
            if row["mc_actual"] is not None:
                score[key][3] += 1
                if abs(row["mc_actual"] - mc) < .01:
                    score[key][2] += 1
        detail.append(row)

    print(f"{'method':14s} {'annual':>12s} {'medical':>12s} {'combined':>12s}")
    for key, label in (("months_half", "whole months, floor to 1/2 day"),
                       ("exact_days", "exact days, floor to 1 day")):
        a_ok, a_n, m_ok, m_n = score[key]
        pct = (a_ok + m_ok) / max(a_n + m_n, 1) * 100
        print(f"{label:34s} {a_ok:>3}/{a_n:<3} {m_ok:>7}/{m_n:<3} {pct:>10.0f}%")

    print("\nwhere the two methods DISAGREE with each other:")
    for r in detail:
        if r["al_m"] != r["al_d"] or r["mc_m"] != r["mc_d"]:
            print(f"  {r['name'][:32]:32s} joined {r['joined']}  "
                  f"months={r['al_m']}/{r['mc_m']}  days={r['al_d']}/{r['mc_d']}  "
                  f"recorded={r['al_actual']}/{r['mc_actual']}")
    return score


def actual(cycle_year):
    """{employee: {leave_type: days}} from the submitted allocations."""
    out = {}
    for r in frappe.db.sql("""
        SELECT la.employee, la.leave_type, la.new_leaves_allocated AS days
          FROM `tabLeave Allocation` la
         WHERE la.docstatus = 1 AND YEAR(la.from_date) = %s""",
                           int(cycle_year), as_dict=True):
        out.setdefault(r.employee, {})[r.leave_type] = float(r.days)
    return out


def rows(cycle_year=2026):
    """One row per employee who holds any allocation for the cycle."""
    got = actual(cycle_year)
    out = []
    for emp, days in got.items():
        e = frappe.db.get_value("Employee", emp,
                                ["employee_name", "date_of_joining",
                                 "attendance_device_id", "status"], as_dict=True)
        if not e or not e.date_of_joining:
            continue
        want = entitlement(e.date_of_joining, cycle_year)
        out.append({
            "employee": emp,
            "name": e.employee_name,
            "joined": str(e.date_of_joining),
            "device": e.attendance_device_id,
            "status": e.status,
            "months": want["months"],
            "rule": want["rule"],
            "al_formula": want["al"],
            "al_actual": days.get("Annual"),
            "mc_formula": want["mc"],
            "mc_uncapped": want.get("mc_uncapped"),
            "mc_actual": days.get("MC"),
        })
    out.sort(key=lambda r: r["months"])
    return out


def verify(cycle_year=2026):
    data = rows(cycle_year)
    print(f"{'employee':34s} {'joined':11s} {'mo':>3s} {'rule':10s} "
          f"{'AL calc':>7s} {'AL is':>6s} {'':2s} {'MC calc':>7s} {'MC is':>6s}")
    al_ok = mc_ok = al_n = mc_n = 0
    for r in data:
        a_mark = m_mark = "  "
        if r["al_actual"] is not None:
            al_n += 1
            if abs(r["al_actual"] - r["al_formula"]) < 0.01:
                al_ok += 1
            else:
                a_mark = "🔴"
        if r["mc_actual"] is not None:
            mc_n += 1
            if abs(r["mc_actual"] - r["mc_formula"]) < 0.01:
                mc_ok += 1
            else:
                m_mark = "🔴"
        print(f"{r['name'][:34]:34s} {r['joined']:11s} {r['months']:>3} "
              f"{r['rule']:10s} {r['al_formula']:>7} "
              f"{('-' if r['al_actual'] is None else r['al_actual']):>6}{a_mark} "
              f"{r['mc_formula']:>7} "
              f"{('-' if r['mc_actual'] is None else r['mc_actual']):>6}{m_mark}")

    print(f"\nAnnual  : {al_ok}/{al_n} match the formula")
    print(f"Medical : {mc_ok}/{mc_n} match the formula")
    return {"rows": data, "al": (al_ok, al_n), "mc": (mc_ok, mc_n)}
