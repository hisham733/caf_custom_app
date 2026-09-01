"""RDY-* — the pre-go-live readiness audit, and proof that it can actually fire.

    bench --site <site> execute caf.tests.fingerlog.test_readiness.run

Purpose : assert the audit's checks DETECT, not merely that they run clean.
Refs    : scripts/readiness_audit.py · OD-75 · OD-76 · framework §6

🔴 WHY RDY-DETECT IS THE WHOLE POINT
-------------------------------------
The naming-series audit, written the same day, reported **a clean bill on the
exact counter that was 54 short** — its filter missed the doctype that started
it. A check that finds nothing is indistinguishable from a check that cannot
find anything, and both print the same reassuring zero.

So this suite **breaks something on purpose**, confirms the check goes red,
restores it, and confirms it goes green again. Anything less is asserting that
`0 == 0`.

⚠️ It mutates live configuration — a Shift Type's holiday list and an Employee's
default shift. Both are restored in a `finally`, and `RDY-RESTORE` compares
against a snapshot rather than trusting it.
"""

import frappe

from caf.scripts import readiness_audit as ra

RESULTS = []
SEVERITIES = {"BLOCK", "WARN", "note", "ok"}


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def by_name(rows, needle):
    return next((r for r in rows if needle in r["check"]), None)


def run():
    frappe.set_user("Administrator")

    base = ra.audit()["rows"]
    shift = frappe.db.get_value("Shift Type", {"holiday_list": ("!=", "")}, "name")
    shift_list = frappe.db.get_value("Shift Type", shift, "holiday_list")
    emp = frappe.db.get_value("Employee", {"status": "Active",
                                           "default_shift": ("!=", ""),
                                           "name": ("!=", "HR-EMP-00002")}, "name")
    emp_shift = frappe.db.get_value("Employee", emp, "default_shift")

    try:
        # ----------------------------------------------------------- RDY-SHAPE
        check("RDY-SHAPE",
              len(base) == len(ra.CHECKS)
              and all(set(r) == {"severity", "check", "count", "detail"} for r in base)
              and all(r["severity"] in SEVERITIES for r in base),
              f"all {len(base)} checks return a well-formed row with a known "
              f"severity. Severities in use: "
              f"{sorted({r['severity'] for r in base})}")

        # ----------------------------------------------------------- RDY-KNOWN
        # The audit must already be finding the two things measured by hand
        # today, or it is not reading what I read.
        #
        # 🔴 BASELINE MOVED 2026-09-01, and it moved the RIGHT WAY. This asserted
        # `mgr["count"] == 22` from the 2026-08-14 hand count. The true figure is
        # now **0**: verified independently by SQL over all 87 active employees who
        # have a manager, every one of those managers can log in. **OD-76 is
        # resolved on this site** — MG imported and corrected `reports_to` and
        # `leave_approver` for the whole workforce (FBR56).
        #
        # Asserting 0 is not a weaker test than asserting 22. It now fails the
        # moment a new employee is given a manager with no user account, which is
        # exactly the condition OD-76 cares about; RDY-DETECT separately proves the
        # check can still find its own target when one exists.
        #
        # ⚠️ Production is NOT in this state — GO_LIVE_TODO T-10 records that its
        # role and org-chart data is the copy still needing correction.
        mgr = by_name(base, "manager has no login")
        mc = by_name(base, "NO medical entitlement")
        check("RDY-KNOWN", mgr and mgr["count"] == 0 and mgr["severity"] == "ok"
              and mc and mc["count"] == 2 and mc["severity"] == "BLOCK",
              f"it finds what was measured by hand: {mgr['count'] if mgr else '?'} "
              f"employees whose manager cannot log in (OD-76 — was 22, now clear "
              f"after MG's org-chart import), and "
              f"{mc['count'] if mc else '?'} holding leave with no medical "
              f"entitlement — the one the HR document still names")

        # -------------------------------------------------------- RDY-SEVERITY
        # 🔴 The distinction that keeps the list readable. 8 people have MC and
        # no Annual, which for a new joiner may be correct; 2 have Annual and no
        # MC, which is statutory and blocking. Reporting both as BLOCK would
        # bury the two who are actually stuck.
        ann = by_name(base, "no annual")
        check("RDY-SEVERITY", ann and ann["severity"] == "note" and ann["count"] > 0
              and mc["severity"] == "BLOCK",
              f"missing ANNUAL is a note ({ann['count'] if ann else '?'} people, "
              f"may be correct for a new joiner) while missing MC is a BLOCK "
              f"({mc['count']}). A list that cries wolf is one nobody reads")

        # ---------------------------------------------------------- RDY-DETECT 🔴
        frappe.db.set_value("Shift Type", shift, "holiday_list", "",
                            update_modified=False)
        frappe.db.commit()
        broken = by_name(ra.audit()["rows"], "shift types with no holiday list")
        frappe.db.set_value("Shift Type", shift, "holiday_list", shift_list,
                            update_modified=False)
        frappe.db.commit()
        healed = by_name(ra.audit()["rows"], "shift types with no holiday list")
        check("RDY-DETECT", broken and broken["count"] == 1
              and broken["severity"] == "BLOCK"
              and healed and healed["count"] == 0,
              f"clearing {shift}'s holiday list turned the check RED "
              f"({broken['count'] if broken else 0} found) and restoring it "
              f"turned it green again ({healed['count'] if healed else '?'}). "
              f"The check can find its own target — which the naming audit, "
              f"written the same day, could not")

        # ---------------------------------------------------------- RDY-EXEMPT 🔴
        # OD-24's exemption is BY NAME, so a second employee with no default
        # shift must still block. An exemption written as "expect 1" would
        # absorb a real one silently.
        frappe.db.set_value("Employee", emp, "default_shift", "",
                            update_modified=False)
        frappe.db.commit()
        extra = by_name(ra.audit()["rows"], "no default shift")
        frappe.db.set_value("Employee", emp, "default_shift", emp_shift,
                            update_modified=False)
        frappe.db.commit()
        check("RDY-EXEMPT", extra and extra["count"] == 1
              and extra["severity"] == "BLOCK",
              f"OD-24's exemption is by NAME, not by count: emptying a SECOND "
              f"employee's shift still blocks ({extra['count'] if extra else 0} "
              f"found). Written as 'expect 1 empty', a real one would have been "
              f"absorbed in silence")

    finally:
        frappe.set_user("Administrator")
        frappe.db.set_value("Shift Type", shift, "holiday_list", shift_list,
                            update_modified=False)
        frappe.db.set_value("Employee", emp, "default_shift", emp_shift,
                            update_modified=False)
        frappe.db.commit()

    end = ra.audit()["rows"]
    check("RDY-RESTORE",
          [(r["check"], r["count"], r["severity"]) for r in end]
          == [(r["check"], r["count"], r["severity"]) for r in base],
          f"the audit reads exactly as it did before this suite bent two live "
          f"records. {shift}.holiday_list and {emp}.default_shift are back")

    print("\n=== Pre-go-live readiness audit ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:14s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
