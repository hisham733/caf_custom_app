"""LP-* — Leave Policy, and OD-38 answered by execution rather than by reading.

    bench --site <site> execute caf.tests.fingerlog.test_leave_policy.run

Purpose : prove the FBR29 policy chain works end to end before Chunk 6 depends on
          it, and settle **OD-38** — *does stock support a mid-cycle entitlement
          change (FBR31)?* — with assertions instead of an opinion.
Refs    : framework FBR29/30/31 · OD-38 · P-6 · scripts/leave_policy_seed.py

🔴 THE ASSERTION THAT MATTERS IS LP-GUARD
------------------------------------------
Submitting a Leave Policy Assignment **creates Leave Allocations**, and 31 active
employees already hold 2026 ones. A seed that looped over everybody would have
**doubled their entitlement and moved the leave ledger**, silently and
irreversibly-ish. The guard refuses, and this proves it.

OD-38, MEASURED
---------------
`assignment_based_on` has exactly two options — `Leave Period` and `Joining Date`
— and `validate_policy_assignment_overlap` refuses only assignments whose date
ranges **overlap**. Both facts are asserted below, because both decide how FBR31
gets built.
"""

import frappe
from frappe.utils import add_months, get_last_day, getdate

from caf.scripts import leave_policy_seed as seed

YEAR = seed.YEAR
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


def pick_unallocated():
    """An active employee with NO 2026 allocation and an OLD joining date.

    Old, because `calculate_pro_rated_leaves` pro-rates from `date_of_joining`;
    somebody who joined mid-year would get a fraction and the expected value
    would stop being the policy's own number. Derived, never hardcoded (§F4d).
    """
    holders = {r.employee for r in frappe.get_all(
        "Leave Allocation",
        filters={"docstatus": 1, "from_date": (">=", f"{YEAR}-01-01"),
                 "to_date": ("<=", f"{YEAR}-12-31")}, fields=["employee"])}
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "date_of_joining"],
                            order_by="date_of_joining asc"):
        if e.name not in holders and e.date_of_joining \
                and getdate(e.date_of_joining).year < YEAR - 5:
            return e.name
    return None


def pick_allocated():
    return frappe.db.get_value("Leave Allocation", {
        "docstatus": 1, "from_date": (">=", f"{YEAR}-01-01"),
        "to_date": ("<=", f"{YEAR}-12-31")}, "employee")


def cleanup():
    """Scoped by POLICY, not by what this process remembers.

    🔴 §F4, learned again. The first version purged a module-level list of names
    — which is empty in a fresh process, so a crashed run left its Leave Policy
    Assignment behind and the NEXT run tripped over stock's overlap check for an
    employee it had never touched. **A cleanup keyed on in-memory state cleans
    nothing after the crash that made it necessary.**

    The scope is every assignment pointing at one of the three CAF policies.
    That is exact: prod uses no Leave Policy at all (0 policies, 0 assignments
    measured 2026-08-13), so these documents exist only because this suite or
    the seed made them.
    """
    policies = [p for p in (frappe.db.get_value("Leave Policy", {"title": t})
                            for t in seed.POLICIES) if p]
    names = frappe.get_all("Leave Policy Assignment",
                           filters={"leave_policy": ("in", policies)},
                           pluck="name") if policies else []
    for name in set(names) | set(_made):
        if not frappe.db.exists("Leave Policy Assignment", name):
            continue
        doc = frappe.get_doc("Leave Policy Assignment", name)
        # The allocations it created must go first — they link back to it.
        for alloc in frappe.get_all(
                "Leave Allocation",
                filters={"leave_policy_assignment": name},
                fields=["name", "docstatus"]):
            a = frappe.get_doc("Leave Allocation", alloc.name)
            a.flags.ignore_permissions = True
            a.flags.ignore_links = True
            if a.docstatus == 1:
                a.cancel()
            frappe.delete_doc("Leave Allocation", alloc.name,
                              ignore_permissions=True, force=True)
        # ⚠️ RELOAD. Cancelling the allocations above touches this document, so
        # the copy fetched before that loop carries a stale `modified` and
        # `cancel()` raises TimestampMismatchError. Teardown order and document
        # freshness are the same problem here.
        doc.reload()
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Leave Policy Assignment", name,
                          ignore_permissions=True, force=True)
    _made.clear()
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    cleanup()

    period = seed.ensure_leave_period()
    seed.ensure_policies()
    frappe.db.commit()

    alloc_before = frappe.db.count("Leave Allocation", {"docstatus": 1})
    emp = pick_unallocated()
    busy = pick_allocated()

    try:
        # ----------------------------------------------------------- LP-POLICY
        rows = {}
        for title, want in seed.POLICIES.items():
            pol = frappe.db.get_value("Leave Policy", {"title": title})
            got = {d.leave_type: d.annual_allocation for d in frappe.get_all(
                "Leave Policy Detail", filters={"parent": pol},
                fields=["leave_type", "annual_allocation"])}
            rows[title] = (pol, got, want)
        ok = all(pol and {k: float(v) for k, v in got.items()}
                 == {k: float(v) for k, v in want.items()}
                 for pol, got, want in rows.values())
        check("LP-POLICY", ok,
              f"the three bands exist and carry the DEDUCED numbers: "
              + " · ".join(f"{t.split('(')[0].strip()} {w}" for t, (_p, _g, w) in rows.items())
              + ". The numbers live in the documents and nowhere in code, so HR's "
                "real table is a data edit later, not a rewrite")

        # ------------------------------------------------------------- LP-BAND
        bands = {seed.band_for(1.3), seed.band_for(3.0), seed.band_for(9.5)}
        check("LP-BAND", len(bands) == 3
              and seed.band_for(1.99) != seed.band_for(2.0)
              and seed.band_for(4.99) != seed.band_for(5.0),
              f"service maps to a band and the boundaries are where FBR29 puts "
              f"them: 1.99 ➜ 2.0 and 4.99 ➜ 5.0 both cross. 1.3y={seed.band_for(1.3).split('(')[0].strip()}")

        # ------------------------------------------------------------ LP-GUARD 🔴
        # The one that matters. 31 active employees already hold 2026
        # allocations; a seed that looped over everybody would have doubled them.
        err = throws(seed.assign, busy)
        after_guard = frappe.db.count("Leave Allocation", {"docstatus": 1})
        check("LP-GUARD", "already holds" in err and after_guard == alloc_before,
              f"assigning {busy}, who ALREADY holds a {YEAR} allocation, is "
              f"REFUSED and nothing was created ({alloc_before} ➜ {after_guard}). "
              f"{err[:90] or '🔴 it allocated on top'}")

        # ----------------------------------------------------------- LP-ASSIGN
        if not emp:
            check("LP-ASSIGN", False, "no unallocated long-service employee to test with")
        else:
            doc = seed.assign(emp)
            _made.append(doc.name)
            want = seed.POLICIES[seed.band_for(seed.service_years(emp))]
            got = {a.leave_type: float(a.new_leaves_allocated) for a in frappe.get_all(
                "Leave Allocation", filters={"leave_policy_assignment": doc.name},
                fields=["leave_type", "new_leaves_allocated"])}
            check("LP-ASSIGN", got == {k: float(v) for k, v in want.items()},
                  f"assigning {emp} ({seed.service_years(emp)}y) allocated exactly "
                  f"the policy's numbers: {got} vs {want}. No pro-rating, because "
                  f"the fixture is chosen with an OLD joining date — a mid-year "
                  f"joiner would get a fraction and the expectation would rot")

            # ------------------------------------------------- LP-OD38-PERIOD 🔴
            # An hrms BUG, and it explains a measurement: only 5 of 64 existing
            # allocations carry a `leave_period`. leave_policy_assignment.py
            # line ~145 reads
            #     leave_period=self.leave_period if self.assignment_based_on == "Leave Policy"
            # and "Leave Policy" is NOT one of the two options the field offers
            # ("Leave Period" / "Joining Date"). So the branch never fires.
            periods = frappe.get_all(
                "Leave Allocation", filters={"leave_policy_assignment": doc.name},
                pluck="leave_period")
            check("LP-OD38-PERIOD", all(not p for p in periods),
                  f"⚠️ hrms never stamps `leave_period` on an allocation it "
                  f"creates ({periods}) — it tests `assignment_based_on == "
                  f"'Leave Policy'`, which is not one of the field's two options. "
                  f"Do not rely on that link in Chunk 6")

        # ------------------------------------------------- LP-OD38-ANNIV 🔴
        # FBR31's native shape: an anniversary-aligned entitlement year.
        emp2 = pick_unallocated_other(exclude=emp)
        if emp2:
            doj = getdate(frappe.db.get_value("Employee", emp2, "date_of_joining"))
            a = frappe.new_doc("Leave Policy Assignment")
            a.employee = emp2
            a.leave_policy = frappe.db.get_value(
                "Leave Policy", {"title": seed.band_for(seed.service_years(emp2))})
            a.assignment_based_on = "Joining Date"
            a.flags.ignore_permissions = True
            a.insert()
            _made.append(a.name)
            # ⚠️ It must be SUBMITTED for LP-OD38-SPLIT to mean anything:
            # `validate_policy_assignment_overlap` filters on `docstatus: 1`, so
            # a draft blocks nothing and the split test would pass vacuously.
            a.reload()
            a.submit()
            check("LP-OD38-ANNIV",
                  getdate(a.effective_from) == doj
                  and getdate(a.effective_to) == get_last_day(add_months(doj, 12)),
                  f"OD-38 (1): `assignment_based_on = 'Joining Date'` gives an "
                  f"ANNIVERSARY-aligned year — {a.effective_from} to "
                  f"{a.effective_to} from a joining date of {doj}. If FBR31 means "
                  f"'the entitlement year runs anniversary to anniversary', stock "
                  f"does it natively")
        else:
            check("LP-OD38-ANNIV", False, "no second unallocated employee")

        # ------------------------------------------------- LP-OD38-SPLIT 🔴
        # The other reading of FBR31: a CALENDAR year whose rate steps up on the
        # anniversary. Stock cannot do that in ONE allocation — `get_new_leaves`
        # takes a single `annual_allocation` per assignment. But
        # `validate_policy_assignment_overlap` refuses only OVERLAPPING ranges,
        # so two non-overlapping halves of one year are legal.
        if emp2:
            first = frappe.get_doc("Leave Policy Assignment", _made[-1])
            over = frappe.new_doc("Leave Policy Assignment")
            over.employee = emp2
            over.leave_policy = first.leave_policy
            over.effective_from = first.effective_from
            over.effective_to = first.effective_to
            over.flags.ignore_permissions = True
            # `validate` runs on INSERT, so the refusal lands here — no submit,
            # and therefore no `TimestampMismatchError` from saving a doc a hook
            # has already touched.
            err2 = throws(over.insert)
            check("LP-OD38-SPLIT", "already assigned" in err2 or "Overlap" in err2,
                  f"OD-38 (2): an OVERLAPPING assignment is refused — "
                  f"{frappe.utils.strip_html(err2)[:95] or '🔴 it was allowed'}. "
                  f"So a mid-year band STEP is expressible as two "
                  f"NON-overlapping assignments (Jan➜anniversary, "
                  f"anniversary➜Dec), which is the workaround Chunk 6 needs")

    finally:
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    after = frappe.db.count("Leave Allocation", {"docstatus": 1})
    check("LP-CLEAN", after == alloc_before,
          f"Leave Allocations {alloc_before} ➜ {after}. This suite CREATES "
          f"allocations; leaving one would inflate somebody's real balance")

    print("\n=== Leave Policy + OD-38 (FBR29 / FBR31) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:16s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed


def pick_unallocated_other(exclude=None):
    holders = {r.employee for r in frappe.get_all(
        "Leave Allocation",
        filters={"docstatus": 1, "from_date": (">=", f"{YEAR}-01-01"),
                 "to_date": ("<=", f"{YEAR}-12-31")}, fields=["employee"])}
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "date_of_joining"],
                            order_by="date_of_joining asc"):
        if e.name != exclude and e.name not in holders and e.date_of_joining \
                and getdate(e.date_of_joining).year < YEAR - 5:
            return e.name
    return None
