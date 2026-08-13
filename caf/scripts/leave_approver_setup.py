"""Chunk 6b groundwork — give every employee a leave approver. MG, 2026-08-13.

Run   : bench --site <site> execute caf.scripts.leave_approver_setup.plan
        bench --site <site> execute caf.scripts.leave_approver_setup.apply
Refs  : OD-76 · spec §4 · roadmap 6b · framework §6

WHY THIS EXISTS
---------------
**OD-76: `leave_approver` is the authority for Leave Application; `report_to` is
the authority for Appraisal.** They are two structures by decision, and the
measurement that forced it was decisive — `leave_approver` matched the
`report_to` manager on **114 of 606** historical applications, and of the seven
people who have ever approved leave, only one manages anybody.

⚠️ **But the authority field is barely populated: 10 of 89 active employees.**
A workflow cannot route what it cannot address, so 6b needs this first.

MG, 2026-08-13: *"as for this test server, make both structures by the same
person … later will put in real data."* So on `development.localhost` only, this
points each employee's `leave_approver` at their `report_to` manager's user —
which makes the fixtures legible while the CODE still reads the right field. On
production HR supplies the real chain and this script is never run.

🔴 IT CANNOT REACH EVERYBODY, AND THAT IS THE POINT
Measured 2026-08-13:

    already set                 10
    fillable from report_to     56
    manager has NO ERPNext user 21   <- Chan Wai Khong (12), Chong Jin Yen (10)
    no report_to at all          2   <- Ow Yong Mian Fatt, Yow Kwee Chin
                                        (the top of the tree — nobody above them)

The 21 are **OD-76's second defect**, still open with HR: a manager with no login
cannot approve anything, and no amount of data cleaning here creates one. The 2
at the top need a rule, not a lookup. `plan()` names all 23 rather than quietly
leaving them unroutable.

⚠️ AND SEVEN APPROVERS WOULD NEED THE ROLE
Being named in `leave_approver` is not enough — hrms shares the document with
that user and the workflow gates transitions on the **Leave Approver** role.
Seven of the nine implied approvers do not hold it. `apply()` grants it and says
so; it is additive, like `role_import`.

Changelog
---------
1.0  2026-08-13  Chunk 6b groundwork
"""

import frappe

ROLE = "Leave Approver"


def classify():
    out = {"already": [], "fill": [], "no_user": [], "no_manager": []}
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "employee_name", "leave_approver",
                                    "reports_to"], order_by="employee_name"):
        if e.leave_approver:
            out["already"].append(e)
            continue
        if not e.reports_to:
            out["no_manager"].append(e)
            continue
        mgr = frappe.db.get_value("Employee", e.reports_to,
                                  ["employee_name", "user_id"], as_dict=True)
        user = mgr.user_id if mgr else None
        if user and frappe.db.get_value("User", user, "enabled"):
            out["fill"].append({"employee": e.name, "name": e.employee_name,
                                "approver": user,
                                "manager": mgr.employee_name})
        else:
            out["no_user"].append({"name": e.employee_name,
                                   "manager": mgr.employee_name if mgr else "?"})
    return out


def role_gap(c):
    need = {r["approver"] for r in c["fill"]}
    have = {r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "User"},
        fields=["parent"])}
    return sorted(need - have), sorted(need & have)


def plan():
    """🔴 DRY RUN."""
    c = classify()
    missing_role, has_role = role_gap(c)
    total = sum(len(v) for v in c.values())

    print("CHUNK 6b — LEAVE APPROVER ROUTING    🔴 DRY RUN, NOTHING WRITTEN")
    print("=" * 78)
    print(f"   active employees            {total:>4}")
    print(f"   already have an approver    {len(c['already']):>4}")
    print(f"   would be FILLED             {len(c['fill']):>4}")
    print(f"   🔴 manager has NO user      {len(c['no_user']):>4}")
    print(f"   🔴 no report_to at all      {len(c['no_manager']):>4}")

    print(f"\n   WOULD FILL — first 12 of {len(c['fill'])}")
    for r in c["fill"][:12]:
        print(f"      {r['name'][:30]:30s} -> {r['approver'][:30]:30s} "
              f"({r['manager'][:22]})")

    print(f"\n🔴 UNROUTABLE — a workflow cannot address these ({len(c['no_user']) + len(c['no_manager'])})")
    print("   These are OD-76's second defect and the top of the tree. Neither is")
    print("   fixable by data cleaning here: a manager with no login cannot")
    print("   approve, and nobody sits above the top.")
    seen = {}
    for r in c["no_user"]:
        seen[r["manager"]] = seen.get(r["manager"], 0) + 1
    for m, n in sorted(seen.items(), key=lambda x: -x[1]):
        print(f"      manager {m[:30]:30s} has no user — blocks {n} employee(s)")
    for e in c["no_manager"]:
        print(f"      {e.employee_name[:30]:30s} has no report_to (top of tree)")

    print(f"\n   APPROVERS NEEDING THE `{ROLE}` ROLE ({len(missing_role)})")
    for u in missing_role:
        n = len([r for r in c["fill"] if r["approver"] == u])
        print(f"      {u[:34]:34s} would approve {n}")
    print(f"   already hold it: {len(has_role)}")

    print(f"\n🔴 Nothing was written.")
    return {"fill": len(c["fill"]), "unroutable": len(c["no_user"]) + len(c["no_manager"]),
            "role_grants": len(missing_role)}


def apply():
    c = classify()
    missing_role, _have = role_gap(c)

    for r in c["fill"]:
        frappe.db.set_value("Employee", r["employee"], "leave_approver",
                            r["approver"])
    for user in missing_role:
        doc = frappe.get_doc("User", user)
        doc.append("roles", {"role": ROLE})
        doc.flags.ignore_permissions = True
        doc.save()
    frappe.db.commit()

    after = classify()
    print(f"filled {len(c['fill'])} leave_approver values")
    print(f"granted `{ROLE}` to {len(missing_role)} users")
    print(f"still unroutable: {len(after['no_user']) + len(after['no_manager'])} "
          f"— OD-76's second defect ({len(after['no_user'])}) plus the top of the "
          f"tree ({len(after['no_manager'])})")
    return {"filled": len(c["fill"]), "granted": len(missing_role),
            "unroutable": len(after["no_user"]) + len(after["no_manager"])}
