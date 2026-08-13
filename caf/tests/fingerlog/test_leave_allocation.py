"""LA-* — Chunk 6a: the entitlement rule, the dates, and the dry run.

    bench --site <site> execute caf.tests.fingerlog.test_leave_allocation.run

Purpose : prove `caf.caf.leave_allocation` computes §6.15's rule, classifies the
          population the way FBR29 requires, and — the one that matters —
          **writes nothing**.
Refs    : framework §6.15 · FBR29 · roadmap §9e row 6a · scripts/leave_formula.py

🔴 THE TWO ASSERTIONS THAT MATTER
----------------------------------
**LA-DRYRUN** — `plan()` is a report. If it ever writes, it writes Leave
Allocations, which move a real balance. The count is taken before and after.

**LA-GROUP-A** — the population is FBR29 group B, not "every active employee".
This is not a hypothetical: the first version of `diff()` planned for all 89
actives and reported **106 MISSING allocations**, which is an invitation to
grant entitlement to 58 people HR deliberately gave none. The guard is the
difference between a useful report and a dangerous one.

⚠️ THIS SUITE CREATES A LEAVE ALLOCATION (LA-WRITE) and cancels it again.
LA-CLEAN is the canary. A leftover row inflates somebody's real balance.
"""

import io
from contextlib import redirect_stdout
from datetime import date

import frappe
from frappe.utils import getdate

from caf.caf import leave_allocation as la
from caf.scripts.leave_formula import completed_months, entitlement, floor_half

YEAR = la.CYCLE
RESULTS = []
_made = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def throws(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return ""
    except Exception as e:
        return str(e)


def pick_group_a():
    """An ACTIVE, long-service employee holding no allocation for the cycle.

    Long-service so the expected numbers are the flat band (16/22) rather than a
    pro-rated fraction that would rot as the cycle advances — the same reasoning
    as `test_leave_policy.pick_unallocated` (§F4d).
    """
    holders = set(la.recorded(YEAR))
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "date_of_joining"],
                            order_by="date_of_joining asc"):
        if e.name not in holders and e.date_of_joining \
                and getdate(e.date_of_joining).year < YEAR - 5:
            return e.name
    return None


def cleanup():
    """Scoped to what this suite created, and to the cycle.

    §F4 — never purge by employee alone. Every row removed here is matched on
    the allocation NAME this run recorded, so a crashed run cannot take a real
    allocation with it. The belt-and-braces sweep is by description marker,
    which only `create_for` writes.
    """
    names = set(_made)
    for name in names:
        if not frappe.db.exists("Leave Allocation", name):
            continue
        doc = frappe.get_doc("Leave Allocation", name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.reload()
            doc.cancel()
        frappe.delete_doc("Leave Allocation", name,
                          ignore_permissions=True, force=True)
    _made.clear()
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    cleanup()
    alloc_before = frappe.db.count("Leave Allocation", {"docstatus": 1})

    try:
        # ================================================== the arithmetic
        # ------------------------------------------------------ LA-MONTHS
        # The part month is DROPPED. Nafiz joined 13 Apr; to 31 Dec is 8
        # completed months (to 13 Dec), not 8.6 — this is what made
        # whole-months beat exact-days, 88% to 82%.
        check("LA-MONTHS",
              completed_months(date(2026, 4, 13), date(2026, 12, 31)) == 8
              and completed_months(date(2026, 4, 13), date(2026, 12, 12)) == 7
              and completed_months(date(2027, 1, 1), date(2026, 12, 31)) == 0,
              "completed months drops the part month: 13 Apr ➜ 31 Dec = 8, "
              "13 Apr ➜ 12 Dec = 7, and a future joiner floors at 0")

        # ------------------------------------------------------- LA-FLOOR
        check("LA-FLOOR",
              floor_half(14.667) == 14.5 and floor_half(14.5) == 14.5
              and floor_half(14.4) == 14.0 and floor_half(12.0) == 12.0,
              "floor to the HALF day, not the whole: 14.667 ➜ 14.5. Both "
              "employees at 22 months hold exactly 14.5, which is how the "
              "half-day rounding was derived rather than assumed")

        # ------------------------------------------------------- LA-BANDS
        b24 = entitlement(date(2024, 12, 31), YEAR)      # 24 months at cycle end
        b23 = entitlement(date(2025, 1, 31), YEAR)       # 23 months
        b60 = entitlement(date(2021, 12, 31), YEAR)      # 60 months
        check("LA-BANDS",
              b24["rule"] == "2-5y band" and (b24["al"], b24["mc"]) == (12, 18)
              and b60["rule"] == ">5y band" and (b60["al"], b60["mc"]) == (16, 22)
              and b23["rule"] == "pro-rated",
              f"the flat bands take over exactly at 24 and 60 completed months: "
              f"23mo={b23['rule']}, 24mo={b24['al']}/{b24['mc']}, "
              f"60mo={b60['al']}/{b60['mc']}")

        # ------------------------------------------------------- LA-MCCAP
        # MG: *"MC doesn't carry over, then why does it go up to 19?"* — it
        # does not. Medical is granted EVERY year, so counting 17 months of
        # service would re-grant months last year already covered.
        raw = entitlement(date(2025, 1, 1), YEAR)
        check("LA-MCCAP",
              raw["mc"] == 14 and raw["mc_uncapped"] > 14,
              f"medical caps at one year's worth (14) below the bands — 23 "
              f"months would give {raw['mc_uncapped']} uncapped, and the cap "
              f"holds it to {raw['mc']}. Annual has NO cap, because it is "
              f"granted once and double-counts nothing")

        # ================================================== the dates
        # ------------------------------------------------ LA-ANNUAL-START
        # The under-1-year rule, and it needs no validation: stock draws leave
        # from allocations covering the requested day, so a day before
        # from_date has nothing to draw on.
        joined_prev = date(2025, 7, 21)                  # anniversary IN the cycle
        joined_this = date(2026, 4, 13)                  # anniversary AFTER it
        p1 = la.entitlement_for(joined_prev, YEAR)
        p2 = la.entitlement_for(joined_this, YEAR)
        check("LA-ANNUAL-START",
              p1[la.ANNUAL]["from_date"] == date(2026, 7, 21)
              and la.ANNUAL not in p2 and la.MEDICAL in p2,
              f"annual opens on the 1-year anniversary "
              f"({p1[la.ANNUAL]['from_date']}) — and an employee whose "
              f"anniversary falls AFTER the cycle gets no annual row at all, "
              f"while keeping medical. That IS the under-1-year rule; there is "
              f"no separate validation to write")

        # ----------------------------------------------- LA-MEDICAL-START 🔴
        # §6.15 states ONE from_date rule and applies it to "the allocation".
        # Applied to medical it fits 17/31. Reading medical as
        # `later of (joining, 1 Jan)` fits 28/31. Scored here, not asserted
        # from the register — FDR11.
        got = la.recorded(YEAR)
        s_anniv = s_join = n = 0
        for emp, held in got.items():
            row = held.get(la.MEDICAL)
            doj = frappe.db.get_value("Employee", emp, "date_of_joining")
            if not row or not doj:
                continue
            n += 1
            jan1 = date(YEAR, 1, 1)
            if getdate(row.from_date) == max(la.anniversary(doj), jan1):
                s_anniv += 1
            if getdate(row.from_date) == max(getdate(doj), jan1):
                s_join += 1
        check("LA-MEDICAL-START", s_join > s_anniv and n > 0,
              f"medical starts on the JOINING date, not the anniversary — "
              f"scored against all {n} recorded medical rows: "
              f"later-of-joining {s_join}/{n}, later-of-anniversary "
              f"{s_anniv}/{n}. The 1-year wait is an ANNUAL-leave rule; "
              f"applying it to sick leave would postpone every new joiner's "
              f"medical cover by a year")

        # ---------------------------------------------------- LA-NO-CARRY
        e = la.entitlement_for(date(2015, 1, 1), YEAR)
        check("LA-NO-CARRY",
              all(r["to_date"] == date(YEAR, 12, 31) for r in e.values())
              and len(e) == 2,
              f"every row ends 31 Dec {YEAR} and both types are planned — "
              f"§6.15's fresh grant, no carry-over at any length of service")

        # ================================================== the population
        # ------------------------------------------------------ LA-GROUP-A 🔴
        rows = la.diff(YEAR)
        ga_emp = pick_group_a()
        mine = [r for r in rows if r["employee"] == ga_emp]
        missing_anywhere = [r for r in rows if r["klass"] == "MISSING"]
        check("LA-GROUP-A",
              ga_emp and mine and all(r["klass"] == "GROUP_A" for r in mine)
              and len(missing_anywhere) > 0,
              f"{ga_emp} holds nothing for {YEAR} and is classed GROUP_A "
              f"({[r['klass'] for r in mine]}), NOT MISSING — while "
              f"{len(missing_anywhere)} genuine MISSING rows still appear "
              f"elsewhere, so the guard discriminates rather than silencing "
              f"the class. The unguarded version reported 106 MISSING")

        # ------------------------------------------------------- LA-SPLIT
        # The positive control for the line above: MISSING must mean "this
        # employee is already entitled and one type is absent", never "this
        # employee has nothing".
        holders = set(la.recorded(YEAR))
        check("LA-SPLIT",
              all(r["employee"] in holders for r in missing_anywhere),
              f"every one of the {len(missing_anywhere)} MISSING rows belongs "
              f"to an employee who ALREADY holds the other leave type — a real "
              f"gap inside group B, not an invented entitlement")

        # ================================================== the dry run
        # ------------------------------------------------------- LA-DRYRUN 🔴
        before = frappe.db.count("Leave Allocation")
        buf = io.StringIO()
        with redirect_stdout(buf):
            counts = la.plan(YEAR)
        after = frappe.db.count("Leave Allocation")
        report = buf.getvalue()
        check("LA-DRYRUN",
              before == after and "DRY RUN, NOTHING WRITTEN" in report
              and isinstance(counts, dict),
              f"plan() created nothing: Leave Allocation {before} ➜ {after}, "
              f"and the report says so on its first line. It returns counts "
              f"({sum(counts.values())} rows) rather than the rows themselves, "
              f"so `bench execute` does not bury the report in its own output")

        # ---------------------------------------------------- LA-CUMULATIVE 🔴
        # 🔴 THIS REPLACES A TEST THAT ASSERTED A DEFECT THAT DOES NOT EXIST.
        # LA-CLIFF compared SINGLE-CYCLE annual figures across two people and
        # concluded that 23 months earns more than 24 — §F1d, a red assertion
        # about the wrong thing. It is meaningless: the 23-month employee's 15
        # days is his FIRST annual grant ever, the 27-month employee's 12 is
        # her SECOND. Measured across every cycle since joining, 15 vs 22.
        # MG's question is what caught it: *"how do you get 15 at 23 months?"*
        c23 = la.cumulative_annual(date(2025, 1, 1), YEAR)   # 23 mo at cycle end
        c27 = la.cumulative_annual(date(2024, 9, 1), YEAR)   # 27 mo at cycle end
        check("LA-CUMULATIVE",
              c27 > c23,
              f"more service earns more annual leave when both cycles are "
              f"counted: 27 months ➜ {c27:g} days vs 23 months ➜ {c23:g}. The "
              f"single-cycle numbers (12 vs 15) say the opposite and are the "
              f"wrong comparison — one is a second grant, the other a first")

        # ------------------------------------------------------ LA-MONOTONIC
        # The honest version of the cliff check: sweep EVERY joining month, not
        # the employees who happen to exist, and count where less service earns
        # more. The answer is ZERO — the rule is monotonic.
        #
        # 🔴 §F2: a zero is a red flag until the check has been watched finding
        # something. The positive control is the TRUNCATED window that produced
        # my own wrong answer — counting only the last two cycles resurrects the
        # phantom inversion, so the detector is provably able to report one.
        inv = la.cumulative_inversions(YEAR)
        phantom = la.cumulative_inversions(YEAR, since=YEAR - 1)
        check("LA-MONOTONIC",
              len(inv) == 0 and len(phantom) > 0,
              f"the rule is MONOTONIC — {len(inv)} inversions across a 4-year "
              f"sweep of joining dates: no extra month of service ever earns "
              f"less annual leave. Positive control: truncating the count to "
              f"the last two cycles reports {len(phantom)} phantom inversion(s)"
              + (f" (+{phantom[0]['gap']:g} days at "
                 f"{phantom[0]['less_service']['months']}mo)" if phantom else "")
              + ", which is the error that produced the withdrawn OD-77")

        # --------------------------------------------------------- LA-LATE 🔴
        # The real consequence of no-carry-over + the anniversary start, and it
        # only appears when the two rules are applied TOGETHER.
        late = la.late_opening_grants(YEAR)
        unusable = [r for r in late if r["unusable"]]
        check("LA-LATE",
              len(unusable) > 0 and all(r["open_days"] < 60 for r in unusable)
              and min(r["open_days"] for r in late) < 40,
              f"🔴 {len(unusable)} first annual grants open too late to be "
              f"taken. Worst: {unusable[0]['name'][:24]} — "
              f"{unusable[0]['days']:g} days opening {unusable[0]['opens']}, "
              f"{unusable[0]['open_days']} days before they expire "
              f"({unusable[0]['per_open_week']:g}/week of open time). OD-79")

        # ================================================== the writer
        # --------------------------------------------------- LA-APPLY-OFF 🔴
        err = throws(la.apply, YEAR)
        check("LA-APPLY-OFF",
              "disarmed" in err and la.APPLY_ARMED is False,
              f"apply() refuses while APPLY_ARMED is False: "
              f"{frappe.utils.strip_html(err)[:80]}")

        # ------------------------------------------------------- LA-WRITE
        if not ga_emp:
            check("LA-WRITE", False, "no group-A long-service employee to test with")
            check("LA-GUARD", False, "skipped — no fixture")
        else:
            want = la.entitlement_for(
                frappe.db.get_value("Employee", ga_emp, "date_of_joining"), YEAR)
            doc = la.create_for(ga_emp, la.ANNUAL, YEAR)
            _made.append(doc.name)
            doc.reload()
            check("LA-WRITE",
                  float(doc.new_leaves_allocated) == want[la.ANNUAL]["days"]
                  and getdate(doc.from_date) == want[la.ANNUAL]["from_date"]
                  and getdate(doc.to_date) == date(YEAR, 12, 31)
                  and not doc.carry_forward and doc.docstatus == 1,
                  f"create_for() writes exactly what the plan says: "
                  f"{doc.new_leaves_allocated} days, {doc.from_date} ➜ "
                  f"{doc.to_date}, carry_forward={doc.carry_forward}, submitted")

            # ------------------------------------------------------ LA-GUARD 🔴
            # LP-GUARD's sibling. Stock allocates ON TOP of an existing row.
            n_before = frappe.db.count("Leave Allocation", {"docstatus": 1})
            err2 = throws(la.create_for, ga_emp, la.ANNUAL, YEAR)
            n_after = frappe.db.count("Leave Allocation", {"docstatus": 1})
            check("LA-GUARD",
                  "already holds" in err2 and n_before == n_after,
                  f"a second allocation for the same employee/type/cycle is "
                  f"REFUSED and nothing was created ({n_before} ➜ {n_after}). "
                  f"{frappe.utils.strip_html(err2)[:70] or '🔴 it allocated on top'}")

        # ------------------------------------------------ LA-NOT-WHITELISTED
        # Nothing here is reachable from a browser. `plan` reads every
        # employee's joining date and entitlement; `create_for` writes a
        # balance. Neither should be one URL away.
        import inspect
        src = inspect.getsource(la)
        check("LA-NOT-WHITELISTED", "@frappe.whitelist" not in src,
              "the module exposes no whitelisted method — the plan reads every "
              "employee's joining date and the writer moves a leave balance; "
              "both are bench-only by design")

    finally:
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    after_all = frappe.db.count("Leave Allocation", {"docstatus": 1})
    check("LA-CLEAN", after_all == alloc_before,
          f"submitted Leave Allocations {alloc_before} ➜ {after_all}. This "
          f"suite CREATES one; leaving it would inflate a real balance")

    print("\n=== Chunk 6a — leave allocation plan (§6.15) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:20s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
