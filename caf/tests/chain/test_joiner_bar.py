"""Annual leave under one year of service — WHICH guard speaks, and what it says.

    bench --site <site> execute caf.tests.chain.test_joiner_bar.run

🔴 WHY THIS EXISTS — the L5 climb, 2026-09-12
----------------------------------------------
FBR68 / §6.15, **option B as MG chose it**: allocate at the start of the cycle so
the employee *sees* the days they have earned, and refuse the **application**
until their anniversary. `caf/caf/leave_service_bar.py` is the second half of that
choice.

**Measured: it cannot fire on this data.** 28 active employees are under a year of
service and **not one holds an Annual allocation**, so stock refuses first —
*"Application period cannot be outside leave allocation period"*, a message about a
document the employee has never seen, naming no person, no date, no rule and no
remedy. ⭐ **CAF is running option A's data behind option B's guard**, and the
allocation run (T-14 / T-20 / T-30) is what makes the rule explain itself.

🔴 AND THIS IS WHY THE CHAIN SUITES EXIST AT ALL.
`test_leave_service_bar` is **9/9 green** — because it **creates an allocation
first**, which is precisely the state production lacks. **A suite that builds its
own precondition can never discover that the precondition is missing.** This one
asks the question in the state the site is actually in, and reports which guard
answered.

WHAT IS ASSERTED
----------------
    JB1  SOMETHING refuses annual leave under a year — and WHICH is reported,
         not assumed. It fails only if the leave is ALLOWED.
    JB2  given an allocation (option B's state, built and removed here), the
         refusal is CAF's and names the anniversary
    JB3  medical is untouched — the anniversary rule is about annual alone
    JB4  the leave ledger moves by exactly the recounted span
    JB5  the control: over two years of service, annual is allowed
"""

import traceback

import frappe
from frappe.utils import strip_html

from caf.tests.chain import dataset

RESULTS = []
TEMP = "chain.test_joiner_bar TEMPORARY — option B's state, removed by the suite"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<26}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _apply(emp, leave_type, day):
    try:
        la = frappe.new_doc("Leave Application")
        la.employee = emp
        la.leave_type = leave_type
        la.from_date = la.to_date = day
        la.description = "chain.test_joiner_bar"
        la.status = "Approved"
        if la.meta.has_field("leave_approver"):
            la.leave_approver = frappe.db.get_value("Employee", emp,
                                                    "leave_approver")
        la.flags.ignore_permissions = True
        la.insert()
        la.submit()
        return la.name, ""
    except Exception as e:
        frappe.db.rollback()
        return None, strip_html(str(e)).strip()


def _balance(emp, leave_type):
    return frappe.db.sql(
        """SELECT IFNULL(SUM(leaves), 0) FROM `tabLeave Ledger Entry`
            WHERE employee = %s AND leave_type = %s AND docstatus = 1""",
        (emp, leave_type))[0][0]


def _cleanup(emp, days):
    for day in days:
        for dt, field in (("Leave Application", "from_date"),
                          ("Attendance", "attendance_date")):
            for r in frappe.get_all(dt, filters={"employee": emp, field: day},
                                    fields=["name", "docstatus"]):
                doc = frappe.get_doc(dt, r.name)
                if doc.docstatus == 1:
                    doc.flags.ignore_permissions = True
                    doc.flags.caf_skip_leave_guard = True
                    doc.cancel()
                frappe.delete_doc(dt, r.name, force=True, ignore_permissions=True)
    for r in frappe.get_all("Leave Allocation",
                            filters={"employee": emp, "description": TEMP},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Leave Allocation", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Leave Allocation", r.name, force=True,
                          ignore_permissions=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    new = dataset.employee("NEW", required=False)
    old = dataset.employee("OLD", required=False)
    if not new or not old:
        print("SKIPPED — the cast does not resolve on this site (dataset.CAST)")
        return True

    from caf.caf.leave_allocation import ANNUAL, anniversary
    when = anniversary(frappe.db.get_value("Employee", new, "date_of_joining"))
    days = dataset.free_workdays(old, 1)
    day = days[0]
    if str(when) <= day:
        print(f"SKIPPED — {new} reaches their anniversary on {when}, which is on "
              f"or before the test date {day}, so the bar would not apply. "
              f"Re-pick the NEW cast member (dataset.CAST).")
        return True

    try:
        _cleanup(new, [day])
        _cleanup(old, [day])

        # ── JB1 — the LIVE state: which guard actually answers? ────────────
        held = frappe.db.count("Leave Allocation",
                               {"employee": new, "leave_type": ANNUAL,
                                "docstatus": 1})
        name, err = _apply(new, ANNUAL, day)
        ours = "one year of service" in err.lower()
        under_a_year = frappe.db.sql(
            """SELECT COUNT(*) FROM `tabEmployee` e
                WHERE e.status = 'Active'
                  AND TIMESTAMPDIFF(MONTH, e.date_of_joining, %s) < 12
                  AND NOT EXISTS (SELECT 1 FROM `tabLeave Allocation` la
                                   WHERE la.employee = e.name AND la.docstatus = 1
                                     AND la.leave_type = %s
                                     AND la.from_date <= %s AND la.to_date >= %s)
            """, (day, ANNUAL, day, day))[0][0]
        check("JB1-REFUSED-UNDER-A-YEAR", name is None,
              f"annual leave under a year is REFUSED — by "
              f"{'CAF (the service bar)' if ours else 'STOCK'}: {err[:120]!r}. "
              f"⚠️ {new} holds {held} annual allocation(s). 🔴 **{under_a_year} "
              f"active employees are under a year AND hold none**, so on today's "
              f"data stock answers first and CAF's own explanation never runs — "
              f"option A's data behind option B's guard. It is the ALLOCATION RUN "
              f"(T-14/T-20/T-30) that makes the rule explain itself")

        # ── JB2 — build option B's state and ask again ─────────────────────
        alloc = frappe.new_doc("Leave Allocation")
        alloc.employee = new
        alloc.leave_type = ANNUAL
        alloc.from_date = day[:4] + "-01-01"
        alloc.to_date = day[:4] + "-12-31"
        alloc.new_leaves_allocated = 6
        alloc.description = TEMP
        alloc.flags.ignore_permissions = True
        alloc.insert()
        alloc.submit()
        frappe.db.commit()

        name, err = _apply(new, ANNUAL, day)
        who = frappe.db.get_value("Employee", new, "employee_name")
        # ⚠️ The anniversary is matched through `dataset.names_date`, which accepts
        # EITHER form: the message is written for a reader and formats it
        # `01-08-2026`, not in ISO. An ISO-only check failed here on the first run.
        facts = {who: who in err, str(when): dataset.names_date(err, when)}
        check("JB2-CAF-EXPLAINS-ITSELF",
              name is None and "one year of service" in err.lower()
              and all(facts.values()),
              f"with a VISIBLE balance the refusal is CAF's own and it names the "
              f"person and the date the bar lifts {facts}: {err[:150]!r}. ⭐ This "
              f"is the state option B was chosen to produce — the employee sees "
              f"the days they have earned and is told exactly when they become "
              f"usable, instead of being told they have run out")

        # ── JB3/JB4 — medical is untouched, and the ledger moves ───────────
        before = _balance(new, dataset.LEAVE_TYPE)
        name, err = _apply(new, dataset.LEAVE_TYPE, day)
        after = _balance(new, dataset.LEAVE_TYPE)
        check("JB3-MEDICAL-UNTOUCHED", bool(name),
              f"{dataset.LEAVE_TYPE} for the same person on the same day is "
              f"ALLOWED ({name or err[:90]}). §6.15's sentence is about annual "
              f"leave alone; applying the anniversary to medical would postpone "
              f"every new joiner's sick leave by a year")
        check("JB4-LEDGER-MOVES-BY-ONE", round(before - after, 2) == 1.0,
              f"and the leave ledger moved by exactly the recounted span — "
              f"{before} ➜ {after}, delta {round(after - before, 2)}. ⭐ Predicted "
              f"before the action and found on the record after: a balance that "
              f"moves by the wrong amount is the failure nobody notices")

        # ── JB5 — the control ──────────────────────────────────────────────
        name, err = _apply(old, ANNUAL, day)
        check("JB5-CONTROL-ALLOWED", bool(name),
              f"over two years of service the SAME application on the SAME day is "
              f"allowed ({name or err[:90]}). ⚠️ Without this the suite would pass "
              f"identically against a system where nobody can take annual leave "
              f"at all")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        _cleanup(new, [day])
        _cleanup(old, [day])
        left = frappe.db.count("Leave Allocation",
                               {"employee": new, "description": TEMP,
                                "docstatus": ("<", 2)})
        check("JB-RESTORE", left == 0,
              f"the temporary allocation is gone ({left} left, must be 0). It "
              f"exists only to show the state CAF is migrating towards; leaving "
              f"one behind would hand a real employee an entitlement")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
