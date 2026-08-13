"""Chunk 6a — what every employee's leave allocation SHOULD be, and what it is.

Purpose : compute the entitlement §6.15 defines, compare it against the Leave
          Allocations actually recorded, and print every difference.
          🔴 `plan()` WRITES NOTHING. It is a dry run, by design and by MG's
          instruction. `apply()` refuses until MG arms it — see APPLY_ARMED.
Run     : bench --site <site> execute caf.caf.leave_allocation.plan
          bench --site <site> execute caf.caf.leave_allocation.summary
Refs    : framework §6.15 (the rule) · FBR29/30/31 · P-6 · roadmap §9e row 6a
          the values come from `caf.scripts.leave_formula`, which scores the
          formula against the records; this module adds the DATES and the diff.

THE RULE, AS BUILT
------------------
    value    leave_formula.entitlement()  — whole months join -> 31 Dec of the
             cycle, /12 x 8 (annual) and x 14 (medical), floored to the half
             day, with the flat bands taking over at 24 and 60 months and the
             medical figure capped at 14 below 24 months
    ANNUAL   from_date = LATER OF (1-year anniversary, 1 Jan of the cycle)
    MEDICAL  from_date = LATER OF (joining date,       1 Jan of the cycle)
    both     to_date   = 31 Dec of the cycle
             carry_forward = 0, unused_leaves = 0   (§6.15: a fresh grant)

🔴 THE TWO from_date RULES ARE DIFFERENT, AND THAT IS THE POINT
---------------------------------------------------------------
§6.15 states one rule — *"later of (1-year anniversary, 1 Jan)"* — and applies
it to "the allocation". Measured against all 56 of the 2026 rows, that reading
fits ANNUAL 20/25 but MEDICAL only **17/31**. Reading MEDICAL as
`later of (joining, 1 Jan)` fits **28/31** exactly, 30/31 within a day.

The business rule behind the anniversary is quoted in §6.15 itself: *"an
employee under one year of service may not take ANNUAL leave."* It says nothing
about medical, and the data agrees — Nurhasirah (joined 2026-01-05), Nafiz
(2026-04-13) and Khairol Izzah (2026-02-23) each hold medical leave starting on
their joining date, in the same year they joined. Applying the anniversary rule
to medical would postpone every new joiner's sick leave by a year, which is
both against the Employment Act and against what CAF already does.

⚠️ ANNUAL's own rule is NOT unanimous in the data — 3 rows fit the anniversary
and 3 fit 1 January (Rajaindran, Kavithaa, Tanisha, all joined early 2025). The
anniversary is the reading that ENFORCES the stated business rule, so it is the
one built here, and `plan()` lists those 3 as START differences rather than
hiding them. See the register row for the decision.

🔴 WHY THIS DOES NOT GO THROUGH A LEAVE POLICY ASSIGNMENT
----------------------------------------------------------
§6.15 decided *"the Leave Policy Assignment IS the record"* of who is entitled.
That decision is about the GROUP, not about the arithmetic — and stock cannot
do CAF's arithmetic. Read from
`hrms/hr/doctype/leave_policy_assignment/leave_policy_assignment.py`:

    calculate_pro_rated_leaves()
        if getdate(date_of_joining) <= getdate(period_start_date):
            return leaves               <- joined before the cycle: NO pro-rating
        leaves *= actual_period / complete_period      <- exact DAYS
        return rounded(leaves)                         <- to a WHOLE day

    CAF                              stock Leave Policy Assignment
    pro-rates anyone under 24 mo     only someone who joined DURING the cycle
    whole months, join -> 31 Dec     exact days, join -> cycle end
    floor to the half day            rounded() to a whole day
    annual starts on the anniversary from_date = effective_from (1 Jan or DOJ)
    medical capped at 14             capped at the policy's own number

Nurul Hazirah joined 2025-07-21. CAF gives her 17 months -> 11 annual days
starting 2026-07-21. A policy assignment would give her the flat band number
with no pro-rating at all, starting 1 January — a different number AND a year
of annual leave she has not earned. So the numbers are computed here and the
Leave Policy is recorded as a LINK on the allocation (the `leave_policy` field,
already populated in CAF's own exports), which keeps §6.15's intent — the band
is recorded, no custom field was invented — without the wrong arithmetic.

Changelog
---------
1.0  2026-08-13  Chunk 6a — dry run only, apply() disarmed
"""

from datetime import date

import frappe
from frappe.utils import getdate

from caf.scripts.leave_formula import entitlement

CYCLE = 2026

ANNUAL = "Annual"
MEDICAL = "MC"

# 🔴 apply() refuses while this is False. Flip it ONLY on MG's explicit
# instruction, and only after `plan()` has been read and the open decision in
# the module header is closed. `create_for()` is the unit the tests exercise;
# it is callable without arming, so the writer is proven without a bulk run.
APPLY_ARMED = False

# The band -> Leave Policy title map, so the allocation records WHICH band it
# came from. Titles are matched, not names: the names are site-generated.
POLICY_TITLE = {
    ">5y band": "CAF Service over 5 years",
    "2-5y band": "CAF Service 2 to 5 years",
    "pro-rated": "CAF Service under 2 years (ANNUAL PROVISIONAL)",
}


# --------------------------------------------------------------------- dates
def anniversary(doj):
    """The 1-year anniversary. 29 February joiners fall back to the 28th."""
    doj = getdate(doj)
    try:
        return doj.replace(year=doj.year + 1)
    except ValueError:
        return doj.replace(year=doj.year + 1, day=28)


def cycle_bounds(cycle):
    return date(int(cycle), 1, 1), date(int(cycle), 12, 31)


def start_for(leave_type, doj, cycle):
    """When the allocation opens. Returns None if it does not open this cycle."""
    jan1, dec31 = cycle_bounds(cycle)
    base = anniversary(doj) if leave_type == ANNUAL else getdate(doj)
    start = max(base, jan1)
    return None if start > dec31 else start


# ------------------------------------------------------------------ the plan
def entitlement_for(doj, cycle=CYCLE):
    """Every allocation row this employee should hold for the cycle.

    Returns {leave_type: {"days", "from_date", "to_date", "rule", "months"}}.
    A leave type is ABSENT when it does not open this cycle — an employee whose
    first anniversary falls after 31 December has no annual row at all, which
    is how the under-1-year rule shows up in the plan rather than as a zero.
    """
    jan1, dec31 = cycle_bounds(cycle)
    doj = getdate(doj)
    if doj > dec31:
        return {}

    want = entitlement(doj, cycle)
    out = {}
    for leave_type, days in ((ANNUAL, want["al"]), (MEDICAL, want["mc"])):
        start = start_for(leave_type, doj, cycle)
        if start is None or not days:
            continue
        out[leave_type] = {
            "days": float(days),
            "from_date": start,
            "to_date": dec31,
            "rule": want["rule"],
            "months": want["months"],
        }
    return out


def recorded(cycle=CYCLE):
    """{employee: {leave_type: row}} from the SUBMITTED allocations."""
    jan1, dec31 = cycle_bounds(cycle)
    out = {}
    for a in frappe.get_all(
            "Leave Allocation",
            filters={"docstatus": 1, "from_date": (">=", jan1), "to_date": ("<=", dec31)},
            fields=["name", "employee", "leave_type", "new_leaves_allocated",
                    "total_leaves_allocated", "from_date", "to_date",
                    "carry_forward", "unused_leaves", "leave_policy"]):
        out.setdefault(a.employee, {})[a.leave_type] = a
    return out


def diff(cycle=CYCLE, include_inactive=False):
    """One row per (employee, leave_type) where plan and record disagree.

    🔴 THE POPULATION IS NOT "EVERY ACTIVE EMPLOYEE". FBR29 says there are two
    entitlement groups, and §6.15 says group A *"simply has no assignment"* —
    58 of the 89 active employees hold no 2026 allocation at all. Planning for
    them produces a table of 106 "missing" allocations and invites somebody to
    create entitlement HR never granted. So membership of group B is read from
    the data — an employee is in it if they hold ANY allocation for the cycle —
    and group A is listed separately, with the formula's answer shown but
    marked for HR to confirm rather than to act on.

    Classes — within group B
        OK        the record matches the plan on days AND on from_date
        VALUE     the number differs
        START     the number agrees, the from_date does not
        BOTH      both differ
        MISSING   entitled under the rule, and the OTHER type IS held — a real
                  gap in somebody HR has already decided is entitled
        EXTRA     recorded, but the plan produces no such row
    Classes — outside group B
        GROUP_A       holds nothing for the cycle. NOT an error; HR confirms
        NOT_IN_CYCLE  joined after the cycle ended, or nothing opens in it
        NO_JOIN_DATE  cannot be computed at all
    """
    emps = frappe.get_all(
        "Employee",
        filters={} if include_inactive else {"status": "Active"},
        fields=["name", "employee_name", "date_of_joining", "status"],
        order_by="employee_name")
    got = recorded(cycle)
    rows = []
    for e in emps:
        if not e.date_of_joining:
            rows.append({"employee": e.name, "name": e.employee_name, "status": e.status,
                         "leave_type": "-", "klass": "NO_JOIN_DATE", "joined": None,
                         "plan_days": None, "got_days": None,
                         "plan_start": None, "got_start": None, "rule": "-", "months": None})
            continue
        plan_rows = entitlement_for(e.date_of_joining, cycle)
        held = got.get(e.name, {})

        if not held:
            # Group A, or nothing opens this cycle. Either way there is nothing
            # to reconcile — show what the rule WOULD give and let HR decide.
            klass = "GROUP_A" if plan_rows else "NOT_IN_CYCLE"
            for leave_type in sorted(plan_rows) or ["-"]:
                p = plan_rows.get(leave_type)
                rows.append({
                    "employee": e.name, "name": e.employee_name, "status": e.status,
                    "joined": getdate(e.date_of_joining), "leave_type": leave_type,
                    "klass": klass,
                    "plan_days": p["days"] if p else None, "got_days": None,
                    "plan_start": p["from_date"] if p else None, "got_start": None,
                    "rule": (p or {}).get("rule") or "-",
                    "months": (p or {}).get("months"), "allocation": None,
                })
            continue

        for leave_type in sorted(set(plan_rows) | set(held)):
            p = plan_rows.get(leave_type)
            g = held.get(leave_type)
            if p and not g:
                klass = "MISSING"
            elif g and not p:
                klass = "EXTRA"
            else:
                dv = abs(float(g.new_leaves_allocated or 0) - p["days"]) > 0.01
                ds = getdate(g.from_date) != p["from_date"]
                klass = "BOTH" if (dv and ds) else ("VALUE" if dv else ("START" if ds else "OK"))
            rows.append({
                "employee": e.name,
                "name": e.employee_name,
                "status": e.status,
                "joined": getdate(e.date_of_joining),
                "leave_type": leave_type,
                "klass": klass,
                "plan_days": p["days"] if p else None,
                "got_days": float(g.new_leaves_allocated or 0) if g else None,
                "plan_start": p["from_date"] if p else None,
                "got_start": getdate(g.from_date) if g else None,
                "rule": (p or {}).get("rule") or "-",
                "months": (p or {}).get("months"),
                "allocation": g.name if g else None,
            })
    return rows


def band_discontinuity(cycle=CYCLE):
    """🔴 Where one MORE month of service produces FEWER annual days.

    Found by running the plan over everybody rather than over the eight people
    the formula was fitted to. The pro-rated annual figure is months/12 x 8, so
    at 19 months it is 12.67 -> 12.5 days, and it keeps climbing to 15.33 -> 15
    at 23 months. At 24 months the 2-5y band takes over at a flat **12**.

        18 mo -> 12.0      23 mo -> 15.0      <- the peak
        19 mo -> 12.5      24 mo -> 12.0      <- the cliff, -3 days

    Everyone between 19 and 23 completed months is therefore entitled to MORE
    annual leave than a colleague with two full years. Medical has no such
    cliff, because the MC cap at 14 holds the pro-rated figure below the 18-day
    band. Annual has no cap, and that asymmetry is what produces this.

    Returns the affected employees so the size of the problem is a number, not
    an impression.
    """
    jan1, dec31 = cycle_bounds(cycle)
    out = []
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "employee_name", "date_of_joining"],
                            order_by="date_of_joining"):
        if not e.date_of_joining:
            continue
        w = entitlement(e.date_of_joining, cycle)
        if w["rule"] != "pro-rated" or w["months"] < 19:
            continue
        out.append({"name": e.employee_name, "joined": str(e.date_of_joining),
                    "months": w["months"], "al": w["al"], "band_above": 12,
                    "excess": round(w["al"] - 12, 2)})
    return out


# ------------------------------------------------------------------- reports
def _fmt(v):
    return "-" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


def plan(cycle=CYCLE):
    """🔴 DRY RUN. Prints what would change and writes nothing."""
    rows = diff(cycle)
    got = recorded(cycle)
    holders = set(got)

    # Listed = needs somebody to act. Counted only = correct as it stands, or
    # not this build's business.
    LISTED = ["MISSING", "VALUE", "BOTH", "START", "EXTRA"]
    COUNTED = ["OK", "GROUP_A", "NOT_IN_CYCLE", "NO_JOIN_DATE"]
    by_class = {}
    for r in rows:
        by_class.setdefault(r["klass"], []).append(r)

    def header():
        print(f"   {'employee':32s} {'joined':11s} {'mo':>3s} {'type':7s} "
              f"{'plan':>6s} {'is':>6s}   {'plan from':11s} {'is from':11s}")

    def show(rs):
        for r in sorted(rs, key=lambda x: (x["leave_type"], x["joined"] or date.min)):
            print(f"   {r['name'][:32]:32s} {_fmt(r['joined']):11s} "
                  f"{_fmt(r['months']):>3s} {r['leave_type']:7s} "
                  f"{_fmt(r['plan_days']):>6s} {_fmt(r['got_days']):>6s}   "
                  f"{_fmt(r['plan_start']):11s} {_fmt(r['got_start']):11s}")

    print(f"CHUNK 6a — LEAVE ALLOCATION PLAN FOR {cycle}    🔴 DRY RUN, NOTHING WRITTEN")
    print(f"{'=' * 104}")
    print("Population is FBR29 GROUP B ONLY — an employee who holds at least one")
    print(f"{cycle} allocation. Group A is counted, never planned for.")

    for klass in LISTED:
        rs = by_class.get(klass)
        if not rs:
            continue
        print(f"\n{klass}  ({len(rs)})")
        header()
        show(rs)

    ga = by_class.get("GROUP_A", [])
    if ga:
        crossed = [r for r in ga if r["leave_type"] == ANNUAL]
        print(f"\nGROUP_A — hold NOTHING for {cycle}  "
              f"({len({r['employee'] for r in ga})} employees)")
        print("   Not an error, and NOT to be created. Shown so HR can confirm the")
        print("   group is right. These are the ones the rule would entitle:")
        header()
        show(sorted(crossed, key=lambda x: x["joined"] or date.min)[:12])
        if len(crossed) > 12:
            print(f"   ... and {len(crossed) - 12} more")

    cliff = band_discontinuity(cycle)
    if cliff:
        print(f"\n🔴 RULE DEFECT — the annual band cliff at 24 months  ({len(cliff)} affected)")
        print("   Pro-rated annual keeps climbing to 15 days at 23 months, then the")
        print("   2-5y band drops it to a flat 12. One more month of service costs")
        print("   these people up to 3 days. See band_discontinuity().")
        print(f"   {'employee':32s} {'joined':11s} {'mo':>3s} {'gets':>6s} "
              f"{'2-5y band':>10s} {'excess':>7s}")
        for c in cliff:
            print(f"   {c['name'][:32]:32s} {c['joined']:11s} {c['months']:>3} "
                  f"{c['al']:>6g} {c['band_above']:>10} {c['excess']:>7g}")

    print(f"\n{'=' * 104}")
    print("SUMMARY")
    for klass in LISTED + COUNTED:
        n = len(by_class.get(klass, []))
        if n:
            tag = "  <- needs action" if klass in LISTED else ""
            print(f"   {klass:14s} {n:>4} rows{tag}")
    actives = set(frappe.get_all("Employee", filters={"status": "Active"}, pluck="name"))
    print(f"\n   active employees                    {len(actives):>4}")
    print(f"   holding any {cycle} allocation        {len(holders & actives):>4}   (FBR29 group B)")
    print(f"   holding none                        {len(actives - holders):>4}   (FBR29 group A — HR confirms)")
    print(f"   allocations held by NON-active      {len(holders - actives):>4}")
    print(f"\n🔴 Nothing was written. `apply()` is disarmed (APPLY_ARMED = "
          f"{APPLY_ARMED}) and refuses until MG closes the open decisions in the "
          f"module header.")
    # Counts, not the rows — `bench execute` prints whatever is returned, and
    # returning ~160 dicts buries the report under 49 KB of its own output.
    # Tests call diff() directly.
    return {k: len(v) for k, v in sorted(by_class.items())}


def summary(cycle=CYCLE):
    """The counts only — for a quick check that nothing drifted."""
    rows = diff(cycle)
    counts = {}
    for r in rows:
        counts[r["klass"]] = counts.get(r["klass"], 0) + 1
    for k in sorted(counts):
        print(f"   {k:14s} {counts[k]:>4}")
    return counts


# -------------------------------------------------------------------- writer
def create_for(employee, leave_type, cycle=CYCLE, submit=True):
    """Write ONE allocation, exactly as the plan describes it.

    Callable without arming — this is the unit the tests exercise, so the writer
    is proven on a fixture without ever running a bulk pass. `apply()` is the
    thing that is gated, because a loop is what moves the ledger.

    Refuses if an allocation for the same employee/type/cycle already exists:
    stock would allocate ON TOP of it (LP-GUARD), which is how 31 people's
    entitlement gets silently doubled.
    """
    doj = frappe.db.get_value("Employee", employee, "date_of_joining")
    if not doj:
        frappe.throw(f"{employee} has no joining date — cannot compute an entitlement")

    want = entitlement_for(doj, cycle).get(leave_type)
    if not want:
        frappe.throw(f"{employee} is not entitled to {leave_type} in {cycle} "
                     f"under §6.15 — nothing to create")

    jan1, dec31 = cycle_bounds(cycle)
    if frappe.db.exists("Leave Allocation", {
            "employee": employee, "leave_type": leave_type, "docstatus": 1,
            "from_date": (">=", jan1), "to_date": ("<=", dec31)}):
        frappe.throw(f"{employee} already holds a {cycle} {leave_type} allocation. "
                     f"Creating another allocates on top of it.")

    doc = frappe.new_doc("Leave Allocation")
    doc.employee = employee
    doc.leave_type = leave_type
    doc.from_date = want["from_date"]
    doc.to_date = want["to_date"]
    doc.new_leaves_allocated = want["days"]
    doc.carry_forward = 0            # §6.15 — no carry-over at any length of service
    policy = frappe.db.get_value("Leave Policy", {"title": POLICY_TITLE.get(want["rule"])})
    if policy:
        doc.leave_policy = policy    # records the BAND without a custom field
    doc.flags.ignore_permissions = True
    doc.insert()
    if submit:
        doc.submit()
    # B4 / OD-26 — say where the number came from, on the document itself.
    doc.add_comment(
        "Comment",
        f"Allocated by CAF's entitlement rule (framework §6.15): "
        f"{want['months']} completed months of service to 31 Dec {cycle}, "
        f"rule '{want['rule']}' -> {want['days']} days from {want['from_date']}.")
    return doc


def apply(cycle=CYCLE):
    """🔴 DISARMED. Refuses by design."""
    if not APPLY_ARMED:
        frappe.throw(
            "apply() is disarmed. Chunk 6a is a DRY RUN until MG says otherwise.\n"
            "Read `plan()` first. Two things must be settled before this may run:\n"
            "  1. the ANNUAL from_date for people who joined the previous cycle "
            "(anniversary vs 1 January — the records hold 3 of each)\n"
            "  2. whether FBR29 group A is correct, or is 58 people missing an "
            "entitlement HR never recorded\n"
            "Then set APPLY_ARMED = True in caf/caf/leave_allocation.py.")
    raise NotImplementedError(
        "The bulk pass is deliberately unwritten. When MG arms this, it loops "
        "create_for() over the rows plan() classes as MISSING — and nothing else.")
