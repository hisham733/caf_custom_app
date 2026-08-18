"""An HR Manager must not be scoped to their own Employee record.

    bench --site <site> execute caf.scripts.hr_manager_user_permissions.run
    bench --site <site> execute caf.scripts.hr_manager_user_permissions.run --kwargs "{'apply':1}"

⚠️ **Not test-server-only.** Production shares this — the data came from there.

FOUND BY MG IN THE DESK, 2026-08-18
-----------------------------------
Logged in as `natalie@caffood.com` (HR Manager), the Finger Log list showed **only
her own rows**. Report view showed a partial set. The held-draft worklist — the
whole point of importing as drafts — was invisible to the person who works it.

The scope code was innocent. `finger_log_scope.get_permission_query_conditions`
correctly returns `""` (no restriction) for an HR Manager. What restricted her was
a **User Permission** row:

    user=natalie@  allow=Employee  for_value=HR-EMP-00006  apply_to_all_doctypes=1

`Finger Log.employee` is a **Link to Employee** (D-6 converted it from Data), so
Frappe applies that match-filter on top of the hook. Two mechanisms, and the one
nobody was thinking about wins.

WHY NOT JUST DELETE THE CONVENTION
----------------------------------
97 users carry an Employee User Permission and for the other 94 it is **correct** —
it is how an ordinary employee is scoped to themselves across every doctype with an
Employee link. Removing it wholesale would open everyone's records to everyone.

The defect is narrower: **three HR Managers carry a self-restricting row they
should not** — `natalie@`, `fiza@`, `mg@`. Their job is to see everybody.

Nothing is lost by removing it: all three rows have `is_default = 0`, so no field
default depends on them. A User Permission only ever RESTRICTS; it grants nothing.

⚠️ Note for whoever adds an HR Manager later: granting the role is not enough. If
that person already has an Employee User Permission from being an ordinary employee
first, they will silently see only themselves. Run this after any role change.
"""

import frappe

ROLE = "HR Manager"


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")

    holders = {r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "User"}, fields=["parent"])}

    rows = frappe.get_all(
        "User Permission",
        filters={"allow": "Employee", "user": ("in", list(holders) or [""])},
        fields=["name", "user", "for_value", "apply_to_all_doctypes", "is_default"])

    print(f"\n{ROLE} holders: {len(holders)}")
    print(f"Self-scoping Employee User Permissions among them: {len(rows)}\n")
    for r in rows:
        flag = " ⚠️ IS DEFAULT — check before removing" if r.is_default else ""
        print(f"  {r.user:30s} → {r.for_value}  "
              f"apply_to_all={r.apply_to_all_doctypes}{flag}")

    if not rows:
        print("  (none — every HR Manager can see the whole workforce)")
        return {"found": 0}

    if not apply:
        print("\n(report only — pass apply=1 to remove them)")
        return {"found": len(rows)}

    removed = 0
    for r in rows:
        if r.is_default:
            print(f"  SKIP {r.user}: is_default=1, removing it would change field "
                  f"defaults. Decide this one by hand.")
            continue
        frappe.delete_doc("User Permission", r.name, ignore_permissions=True,
                          force=True, delete_permanently=True)
        print(f"  ✓ removed {r.user} → {r.for_value}")
        removed += 1

    frappe.db.commit()
    frappe.clear_cache()
    print(f"\nDONE — {removed} removed. Affected users must RELOAD their browser.")
    return {"removed": removed}
