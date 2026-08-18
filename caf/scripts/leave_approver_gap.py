"""Every active employee must have a working leave approver. Find and fix the gaps.

    bench --site <site> execute caf.scripts.leave_approver_gap.run              # report
    bench --site <site> execute caf.scripts.leave_approver_gap.run --kwargs "{'apply':1}"

MG, 2026-08-18: *"all emp should already have approver at test server ... and in
future in prod server as well."*

⚠️ **This is NOT test-server-only.** Unlike `test_server_hr_roles.py`, the gap this
fixes is a real data defect that production almost certainly shares — the test
server's employee data was imported from production (commit 0417b73). Run the
report there before go-live.

TWO HALVES, AND THE SECOND IS THE ONE THAT BITES
------------------------------------------------
A blank `leave_approver` is the obvious half. The subtle half is an approver who
holds no **Leave Approver role** — the Chunk 6b workflow restricts every transition
to `Leave Approver` or `HR Manager`, so naming somebody who holds neither produces
a leave application **nobody can act on**. It looks configured and is not.

Found exactly that on 2026-08-18: `HR-EMP-00128` Ow Yong Suit Chun had no approver,
and their supervisor `chong.jin.yen@caffood.com` held only `Employee`. Filling the
field alone would have created a dead end.

The two organisation ROOTS are exempt by definition — nobody is above them. HR
approves on their behalf (FBR50).
"""

import frappe
from frappe import _

APPROVER_ROLE = "Leave Approver"


def _roots():
    return {e.name for e in frappe.get_all(
        "Employee", filters={"status": "Active", "reports_to": ("in", ["", None])},
        fields=["name"])}


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")
    roots = _roots()

    missing, roleless = [], []
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "employee_name", "reports_to",
                                    "leave_approver"]):
        if e.name in roots:
            continue
        if not e.leave_approver:
            sup_user = frappe.db.get_value("Employee", e.reports_to, "user_id") \
                if e.reports_to else None
            missing.append((e, sup_user))
        else:
            has = frappe.db.exists("Has Role", {"parent": e.leave_approver,
                                                "parenttype": "User",
                                                "role": APPROVER_ROLE})
            hrm = frappe.db.exists("Has Role", {"parent": e.leave_approver,
                                                "parenttype": "User",
                                                "role": "HR Manager"})
            if not (has or hrm):
                roleless.append(e)

    print(f"\nActive employees: {frappe.db.count('Employee', {'status': 'Active'})}"
          f"  ·  organisation roots (exempt): {len(roots)}")

    print(f"\n🔴 NO leave_approver ({len(missing)}):")
    for e, sup_user in missing:
        fix = sup_user or "⚠️ supervisor has no user_id — cannot auto-fix"
        print(f"  {e.name}  {e.employee_name:34s} reports_to={e.reports_to or '—'}"
              f"  → {fix}")

    print(f"\n🔴 approver holds NEITHER '{APPROVER_ROLE}' NOR 'HR Manager' ({len(roleless)}):")
    for e in roleless:
        print(f"  {e.name}  {e.employee_name:34s} approver={e.leave_approver}")
    if not roleless:
        print("  (none — every named approver can actually act)")

    if not apply:
        print("\n(report only — pass apply=1 to fill the gaps)")
        return {"missing": len(missing), "roleless": len(roleless)}

    fixed = 0
    for e, sup_user in missing:
        if not sup_user:
            print(f"  SKIP {e.name}: supervisor has no user_id, nothing to point at")
            continue
        # The role first — a leave approver who cannot act on the workflow is
        # worse than a blank field, because the blank one is visible.
        if not frappe.db.exists("Has Role", {"parent": sup_user,
                                             "parenttype": "User",
                                             "role": APPROVER_ROLE}):
            frappe.get_doc("User", sup_user).add_roles(APPROVER_ROLE)
            print(f"  + granted {APPROVER_ROLE} to {sup_user}")
        frappe.db.set_value("Employee", e.name, "leave_approver", sup_user,
                            update_modified=False)
        print(f"  ✓ {e.name} leave_approver = {sup_user}")
        fixed += 1

    for e in roleless:
        frappe.get_doc("User", e.leave_approver).add_roles(APPROVER_ROLE)
        print(f"  + granted {APPROVER_ROLE} to {e.leave_approver} "
              f"(named approver for {e.name})")
        fixed += 1

    frappe.db.commit()
    print(f"\nDONE — {fixed} fixed.")
    return {"fixed": fixed}
