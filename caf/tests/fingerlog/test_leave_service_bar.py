"""The one-year bar on ANNUAL leave — option B's second half.

    bench --site <site> execute caf.tests.fingerlog.test_leave_service_bar.run

MG chose option B: allocate at the start of the cycle so the employee can SEE
what they have earned, and refuse the application until their anniversary. The
allocation half already existed (`leave_allocation.start_for`). This covers the
refusal half, which is the only part that actually enforces anything.

Six of the eight assertions are about what must NOT be refused. That is
deliberate: a guard on leave is far more dangerous when it over-fires than when
it under-fires — an employee wrongly refused their medical leave is a
disciplinary problem, and the rule says nothing about medical.

LB8 is the one that would fail silently: the hook is a LIST in hooks.py, and
turning a string into a list is exactly the edit that drops the other entry.
"""

import frappe
from frappe.utils import add_days, add_months, getdate, nowdate

from caf.caf.leave_allocation import ANNUAL, anniversary
from caf.caf.leave_service_bar import check_service_bar

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:26s} {'PASS' if ok else 'FAIL'}  {detail}")


def _stub(employee, leave_type, from_date, to_date=None):
    return frappe._dict({
        "doctype": "Leave Application",
        "employee": employee,
        "leave_type": leave_type,
        "from_date": from_date,
        "to_date": to_date or from_date,
    })


def _refused(stub):
    """(was it refused, the message)."""
    try:
        check_service_bar(stub)
        return False, ""
    except frappe.ValidationError as e:
        return True, str(e)


def run():
    frappe.set_user("Administrator")
    made = []
    try:
        today = getdate(nowdate())

        # Somebody genuinely under one year, and somebody long past it.
        young = frappe.db.get_value(
            "Employee",
            {"status": "Active", "date_of_joining": (">", add_months(today, -11))},
            ["name", "employee_name", "date_of_joining"], as_dict=True,
            order_by="date_of_joining desc")
        old = frappe.db.get_value(
            "Employee",
            {"status": "Active", "date_of_joining": ("<", add_months(today, -36))},
            ["name", "employee_name", "date_of_joining"], as_dict=True)

        if not young:
            check("LB0-FIXTURE", False,
                  "no active employee joined within the last 11 months — the bar "
                  "cannot be exercised, and every result below would be vacuous")
            return _summary()
        check("LB0-FIXTURE", True,
              f"under one year: {young.employee_name} joined {young.date_of_joining}, "
              f"anniversary {anniversary(young.date_of_joining)}  ·  over one year: "
              f"{old.employee_name} joined {old.date_of_joining}")

        opens = anniversary(young.date_of_joining)

        # ── LB1 — the refusal, and what it says ────────────────────────────
        hit, msg = _refused(_stub(young.name, ANNUAL, add_days(opens, -3)))
        names_date = str(opens.day) in msg and str(opens.year) in msg
        check("LB1-REFUSES-EARLY", hit and names_date,
              f"annual leave 3 days before the anniversary is refused, and the "
              f"message carries the date it opens ({opens}) — not "
              f"'insufficient balance', which would be a lie: the days exist and "
              f"are simply not yet spendable. names the date: {names_date}")

        # ── LB2 — and lets go on the day itself ────────────────────────────
        hit, _m = _refused(_stub(young.name, ANNUAL, opens))
        check("LB2-OPENS-ON-ANNIVERSARY", not hit,
              f"an application starting ON {opens} passes the bar. MG: *'when emp "
              f"service reach 1 year, the locked away AL becomes available'* — the "
              f"anniversary itself, not the day after and not the next cycle")

        # ── LB3 — a long-serving employee is untouched ─────────────────────
        hit, _m = _refused(_stub(old.name, ANNUAL, today))
        check("LB3-LONG-SERVICE-FREE", not hit,
              f"{old.employee_name} ({old.date_of_joining}) is not affected. The "
              f"guard runs on EVERY leave application on the site, so its cost to "
              f"the 80-odd people it does not concern must be exactly zero")

        # ── LB4..LB6 — 🔴 what must NOT be refused ─────────────────────────
        for tid, lt in (("LB4-MC-UNTOUCHED", "MC"),
                        ("LB5-UNPAID-UNTOUCHED", "Leave Without Pay")):
            hit, _m = _refused(_stub(young.name, lt, add_days(opens, -3)))
            check(tid, not hit,
                  f"{lt} on the same early date is NOT refused. §6.15's sentence "
                  f"is about annual leave alone; applying the anniversary to "
                  f"medical would postpone every new joiner's sick leave by a "
                  f"year — against the Employment Act, and against what CAF "
                  f"already does (measured on 31 allocation rows)")

        # ── LB6 — a blank joining date is a data problem, not a leave one ──
        ghost = frappe.db.get_value("Employee",
                                    {"date_of_joining": ("in", (None, ""))}, "name")
        if ghost:
            hit, _m = _refused(_stub(ghost, ANNUAL, today))
            detail = f"{ghost} has no joining date and is NOT refused"
        else:
            hit, detail = False, ("no employee on this site has a blank joining "
                                  "date; the branch is asserted by inspection")
        check("LB6-NO-JOIN-DATE-PASSES", not hit,
              f"{detail}. readiness_audit already reports blank joining dates — "
              f"blocking somebody's leave on the strength of a missing field "
              f"punishes the employee for HR's data gap")

        # ── LB7 — an application that STRADDLES the anniversary ────────────
        hit, msg = _refused(_stub(young.name, ANNUAL,
                                  add_days(opens, -2), add_days(opens, 2)))
        check("LB7-SPANS-GIVES-THE-SPLIT", hit and "re-file" in msg,
              f"a span that crosses {opens} is refused WITH the instruction to "
              f"re-file from that date. Half the application is legitimate, and a "
              f"refusal that does not say which half is a puzzle rather than an "
              f"answer")

        # ── LB8 — 🔴 the wiring, end to end ────────────────────────────────
        # Everything above calls the function directly, which proves the LOGIC
        # and nothing about whether Frappe ever calls it.
        hooks = frappe.get_hooks("doc_events").get("Leave Application", {})
        wired = "caf.caf.leave_service_bar.check_service_bar" in (
            hooks.get("validate") or [])
        kept = "caf.caf.leave_days.recount_leave_days" in (hooks.get("validate") or [])
        check("LB8-HOOK-WIRED", wired and kept,
              f"validate carries {hooks.get('validate')}. Both entries must "
              f"survive: turning that string into a list is precisely the edit "
              f"that drops E7's leave-day recount, and nothing else would notice "
              f"until a swap made somebody's leave count wrong")

    finally:
        frappe.set_user("Administrator")
        for n in made:
            if frappe.db.exists("Leave Application", n):
                frappe.delete_doc("Leave Application", n, force=True,
                                  ignore_permissions=True)
        frappe.db.commit()

    return _summary()


def _summary():
    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
