"""Leave Policies for FBR29, deduced from CAF's own allocations. OD-38 · P-6.

Purpose : give Chunk 6 a working Leave Policy + Leave Policy Assignment chain to
          build and test against, WITHOUT waiting for HR's table — and without
          touching the 33 employees who already hold 2026 allocations.
Refs    : framework FBR29/30/31 · OD-38 · P-6 · roadmap Chunk 6
Run     : bench --site <site> execute caf.scripts.leave_policy_seed.run

    bench ... execute caf.scripts.leave_policy_seed.report     # read-only

🔴 WHY DEDUCED AND NOT BLANK — MG's decision, 2026-08-13
--------------------------------------------------------
MG chose (b): *"build the framework that enables policy + policy assignment …
deduce from data and build using deduction, run test, then later I get the real
policy."* A blank policy cannot be tested — there is nothing to allocate, and
**FBR31 in particular needs bands to move BETWEEN**.

**The numbers live in the Leave Policy documents and NOWHERE in code.** Swapping
HR's real table in later is then editing three documents, not a rewrite. The
tests derive their expectations from the policy, the same way the June fixtures
derive dates from their constants (§F4d).

WHERE THE NUMBERS CAME FROM — measured 2026-08-13
--------------------------------------------------
CAF's own 2026 Leave Allocations, joined to `date_of_joining`:

    service at 2026-01-01     Annual        MC      n    confidence
    ------------------------------------------------------------------
    > 5 years                 16            22      9    unanimous
    2 - 5 years               12            18      8    unanimous
    < 2 years                 scattered     14     16    MC unanimous;
                              (8,11,12,13,               ANNUAL IS NOT
                               14.5,15,18)

MC is the Malaysian Employment Act table exactly (14/18/22) and Annual matches
statutory 12/16 on the two upper bands. **The `< 2 years` Annual figures are not
a policy** — 14.5 days is arithmetic (pro-rating from the joining date), and 18
days at 1.3 years is above both bands *above* it. That single cell is the one
question for HR, and it is marked below.

⚠️ **PROD USES NO LEAVE POLICY AT ALL.** Measured: `Leave Policy` is set on 0 of
113 allocation rows, and there are 0 Leave Policy and 0 Leave Policy Assignment
documents anywhere. So this introduces a mechanism CAF has never used — which is
P-6's decision, not an accident.

🔴 IT DOES NOT ALLOCATE. Submitting a Leave Policy Assignment CREATES Leave
Allocations, and 33 employees already hold 2026 ones. Assigning them would double
their entitlement and move the leave ledger. So `run()` builds the Leave Period
and the three Policies and stops; assignment is a separate, deliberate call.

Changelog
---------
1.0  2026-08-13  Initial — OD-38 / P-6, deduced from the 2026 allocations
"""

import frappe
from frappe.utils import getdate

YEAR = 2026
PERIOD = f"CAF {YEAR}"

# ⚠️ The one cell HR must supply. 12 is the statutory figure and the most common
# value in the band, so it is a defensible placeholder — but it IS a placeholder,
# and the policy is named so nobody forgets.
ANNUAL_UNDER_2 = 12

POLICIES = {
    "CAF Service under 2 years (ANNUAL PROVISIONAL)": {
        "Annual": ANNUAL_UNDER_2,
        "MC": 14,
    },
    "CAF Service 2 to 5 years": {
        "Annual": 12,
        "MC": 18,
    },
    "CAF Service over 5 years": {
        "Annual": 16,
        "MC": 22,
    },
}


def band_for(years):
    if years < 2:
        return "CAF Service under 2 years (ANNUAL PROVISIONAL)"
    if years < 5:
        return "CAF Service 2 to 5 years"
    return "CAF Service over 5 years"


def service_years(employee, on=None):
    doj = frappe.db.get_value("Employee", employee, "date_of_joining")
    if not doj:
        return None
    on = getdate(on or f"{YEAR}-01-01")
    return round((on - getdate(doj)).days / 365.25, 2)


def ensure_leave_period():
    """🔴 There is no 2026 Leave Period — only `HR-LPR-2025-00001`. Stock's
    allocation wants one, and OD-17 explains the gap: most staff have no
    entitlement, so nobody ever created it."""
    existing = frappe.db.get_value(
        "Leave Period", {"from_date": f"{YEAR}-01-01", "to_date": f"{YEAR}-12-31"})
    if existing:
        return existing
    doc = frappe.new_doc("Leave Period")
    doc.from_date = f"{YEAR}-01-01"
    doc.to_date = f"{YEAR}-12-31"
    doc.company = frappe.db.get_value("Employee", {"status": "Active"}, "company")
    doc.is_active = 1
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name


def ensure_policies():
    made = {}
    for name, rows in POLICIES.items():
        if frappe.db.exists("Leave Policy", {"title": name}):
            made[name] = frappe.db.get_value("Leave Policy", {"title": name})
            continue
        doc = frappe.new_doc("Leave Policy")
        doc.title = name
        for leave_type, days in rows.items():
            if not frappe.db.exists("Leave Type", leave_type):
                frappe.throw(f"Leave Type '{leave_type}' does not exist")
            doc.append("leave_policy_details",
                       {"leave_type": leave_type, "annual_allocation": days})
        doc.flags.ignore_permissions = True
        doc.insert()
        made[name] = doc.name
    return made


def assign(employee, policy=None, leave_period=None, submit=True):
    """Assign ONE employee. Deliberately not a loop over everybody.

    ⚠️ Submitting this CREATES Leave Allocations. 33 employees already hold 2026
    ones; assigning them would double their entitlement and move the ledger.
    """
    if frappe.db.exists("Leave Allocation", {
            "employee": employee, "docstatus": 1,
            "from_date": (">=", f"{YEAR}-01-01"), "to_date": ("<=", f"{YEAR}-12-31")}):
        frappe.throw(f"{employee} already holds a {YEAR} Leave Allocation. "
                     f"Assigning a policy would allocate on top of it.")

    policy = policy or frappe.db.get_value(
        "Leave Policy", {"title": band_for(service_years(employee))})
    doc = frappe.new_doc("Leave Policy Assignment")
    doc.employee = employee
    doc.leave_policy = policy
    doc.assignment_based_on = "Leave Period"
    doc.leave_period = leave_period or ensure_leave_period()
    doc.flags.ignore_permissions = True
    doc.insert()
    if submit:
        doc.submit()
    return doc


def report():
    """Read-only. What exists, and what each band would give."""
    print(f"Leave Period {YEAR}      : "
          f"{frappe.db.get_value('Leave Period', {'from_date': f'{YEAR}-01-01'}) or 'MISSING'}")
    print(f"Leave Policies           : {frappe.db.count('Leave Policy')}")
    print(f"Leave Policy Assignments : {frappe.db.count('Leave Policy Assignment')}")
    print(f"{YEAR} Leave Allocations   : "
          f"{frappe.db.count('Leave Allocation', {'docstatus': 1, 'from_date': ('>=', f'{YEAR}-01-01'), 'to_date': ('<=', f'{YEAR}-12-31')})}")

    print("\nband                                             Annual  MC")
    for name, rows in POLICIES.items():
        print(f"  {name:46s} {rows['Annual']:>5}  {rows['MC']:>3}")

    holders = {r.employee for r in frappe.get_all(
        "Leave Allocation",
        filters={"docstatus": 1, "from_date": (">=", f"{YEAR}-01-01"),
                 "to_date": ("<=", f"{YEAR}-12-31")}, fields=["employee"])}
    active = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")
    print(f"\nactive employees          : {len(active)}")
    print(f"  with a {YEAR} allocation  : {len(holders & set(active))}   (FBR29 group B)")
    print(f"  with none               : {len(set(active) - holders)}   (FBR29 group A)")


def run():
    period = ensure_leave_period()
    made = ensure_policies()
    frappe.db.commit()
    print(f"Leave Period : {period}")
    for name, doc in made.items():
        print(f"  policy     : {doc}  ({name})")
    print()
    report()
    print("\n⚠️ No Leave Policy Assignment was created. 33 employees already hold "
          f"{YEAR} allocations; assigning them would allocate on top. Use "
          f"`assign(employee)` deliberately, one at a time.")
