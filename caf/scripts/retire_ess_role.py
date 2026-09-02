"""`Employee Self Service` is a STANDING ZERO at CAF. Retire it from everyone.

    bench --site <site> execute caf.scripts.retire_ess_role.run
    bench --site <site> execute caf.scripts.retire_ess_role.run --kwargs "{'apply':1}"
    bench --site <site> execute caf.scripts.retire_ess_role.verify

MG, 2026-09-02 (OD-84): *"CAF does not practise self attendance (even a long
distance driver has to physically log via the finger print machine)… note CAF
does not use Employee Self Service role or mobile check-in attendance. Log this,
no user should have this role of Employee Self Service."*

⚠️ **Not test-server-only.** Production carries the same assignments.

WHY IT IS A ZERO AND NOT A SMALL NUMBER
---------------------------------------
ESS is the HRMS self-service surface: the mobile PWA check-in, Attendance
Request, and a self-service view of the employee record. CAF uses none of it —
FBR69 makes the **Finger Log the single source of attendance**, and the escape
hatch for a machine-down day is in **Ingress** (attendance on paper, then HR keys
it in), not in ERPNext.

So the role is not "mostly harmless". It is the one role whose entire purpose is
the workflow CAF decided against, which is why the target is zero rather than a
short list: any number above zero is somebody able to reach a surface nobody
intends to use.

WHAT WAS MEASURED, 2026-09-02
-----------------------------
    4 users hold it — nazifa1@, mimi1@, hisham@, and fiza@, an HR MANAGER
    D42 / T22 said the number must be 0, and the PowerShell suite (T-J25) has
    been red on this for weeks. It is live drift, not a stale assertion.

⚠️ `Has Role` is the child table of BOTH `User` and `Role Profile`, so an
unfiltered query returns profiles as if they were people — the first version of
the readiness check reported "held by 9" including *Income Tax Deductions*, a
Role Profile. Both are handled here: a profile granting ESS is how the role would
come back after this script has run, so it is reported even though it is not a
person.

WHY REMOVING IT IS SAFE
-----------------------
Nothing CAF built reads the role. `caf_permission_matrix` already reduced its two
remaining grants to read-only, and T-24 closed `Attendance Request` and
`Employee Checkin` to it entirely. The employees' own surfaces — the `My
Attendance` report (OD-63), Leave Application, the appraisal — are all reached
through the `Employee` role, which nobody loses here.

⚠️ Removing a role writes no Version, so each affected User gets a **Comment**
naming the role and the reason (OD-26).
"""

import frappe

ROLE = "Employee Self Service"


def _holders():
    return sorted({r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "User"},
        fields=["parent"])})


def _profiles():
    return sorted({r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "Role Profile"},
        fields=["parent"])})


def run(apply=0):
    apply = int(apply or 0)
    frappe.set_user("Administrator")

    holders, profiles = _holders(), _profiles()

    print(f"{ROLE}")
    print(f"  target : 0 users (OD-84 — CAF does not use self-service attendance)")
    print(f"  holders: {len(holders)}")
    for u in holders:
        roles = set(frappe.get_roles(u))
        tag = "  ⚠️ HR MANAGER" if "HR Manager" in roles else ""
        enabled = frappe.db.get_value("User", u, "enabled")
        print(f"    - {u:30s} enabled={enabled}{tag}")

    if profiles:
        print(f"\n  ⚠️ Role Profiles that GRANT it ({len(profiles)}): {profiles}")
        print("     Removing the role from a user does not stop a profile from "
              "re-granting it. These need a person's decision, and this script "
              "does NOT touch them — a Role Profile is shared configuration.")

    # The safety question, asked every run rather than trusted.
    still_employee = [u for u in holders
                      if frappe.db.exists("Has Role", {"parent": u,
                                                       "parenttype": "User",
                                                       "role": "Employee"})]
    lost = [u for u in holders if u not in still_employee]
    if lost:
        print(f"\n🔴 STOP — these hold ESS but NOT the `Employee` role: {lost}")
        print("   Removing ESS would leave them with no employee surface at all. "
              "Grant `Employee` first, then re-run.")
        return {"blocked": lost}
    print(f"\n✅ All {len(holders)} also hold the `Employee` role, which is what "
          f"actually carries their attendance, leave and appraisal surfaces.")

    if not apply:
        print("\n(report only — pass apply=1 to revoke)")
        return {"revoke": len(holders), "profiles": profiles}

    for u in holders:
        doc = frappe.get_doc("User", u)
        doc.remove_roles(ROLE)
        # OD-26 — remove_roles writes no Version, so the reason goes on the record.
        doc.add_comment(
            "Comment",
            f"Removed the `{ROLE}` role (OD-84, 2026-09-02). CAF does not use "
            f"self-service attendance: attendance comes from the fingerprint "
            f"machine via Ingress, and the escape hatch for a machine-down day is "
            f"in Ingress too. The `Employee` role is unchanged and carries this "
            f"person's attendance, leave and appraisal surfaces.")
    frappe.db.commit()
    frappe.clear_cache()

    after = _holders()
    print(f"\nDONE — {ROLE} now held by {len(after)}: {after or 'nobody'}")
    print("Affected users must RELOAD their browser.")
    return {"revoked": len(holders), "remaining": after}


def verify():
    """Both directions: nobody holds it, and nobody lost what they needed."""
    holders, profiles = _holders(), _profiles()

    # The doctypes ESS existed to reach must also be shut.
    open_rows = []
    for dt in ("Attendance Request", "Employee Checkin"):
        for role in ("Employee", ROLE):
            r = frappe.get_all("Custom DocPerm",
                               filters={"parent": dt, "role": role, "permlevel": 0},
                               fields=["`create`", "`write`", "`delete`"])
            if r and (r[0].create or r[0].write or r[0].delete):
                open_rows.append(f"{dt}/{role}")

    # And the people who had it must still be able to do their jobs.
    had = ["nazifa1@caffood.com", "mimi1@caffood.com",
           "hisham@caffood.com", "fiza@caffood.com"]
    still_working = [u for u in had
                     if frappe.db.exists("User", u)
                     and "Employee" in frappe.get_roles(u)]

    checks = [
        ("ESS-1", not holders,
         f"no USER holds `{ROLE}` ({len(holders)} found: {holders}). D42/T22 says "
         f"this must be 0, and T-J25 has been red on it for weeks"),
        ("ESS-2", not profiles,
         f"no Role Profile grants it either ({profiles or 'none'}) — a profile is "
         f"how the role comes back after this script has run"),
        ("ESS-3", not open_rows,
         f"the surfaces it existed to reach are shut: {open_rows or 'both closed'} "
         f"(T-24). Removing the role without closing these would leave the door "
         f"open to the `Employee` role instead"),
        ("ESS-4", len(still_working) == len([u for u in had if frappe.db.exists("User", u)]),
         f"{len(still_working)} of the former holders still hold `Employee` and "
         f"have lost nothing they use — attendance, leave and appraisal are all "
         f"on that role, never on ESS"),
    ]

    fails = 0
    for cid, ok, why in checks:
        print(f"{cid} {'PASS' if ok else 'FAIL'}  {why}")
        fails += 0 if ok else 1
    print(f"\n{len(checks) - fails}/{len(checks)} passed")
