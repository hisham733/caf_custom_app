"""HR User is HR STAFF, not supervisors. Retire it to the two who are.

    bench --site <site> execute caf.scripts.retire_hr_user_role.run
    bench --site <site> execute caf.scripts.retire_hr_user_role.run --kwargs "{'apply':1}"

MG, 2026-08-22, after the first manual test pass: *"if Stock ERPNext intended HR
User to be HR staff, then help me to remove HR user role from everyone except for
Chen and fiza."*

⚠️ **Not test-server-only.** Production carries the same assignments (0417b73
imported them from there).

WHAT HR USER ACTUALLY GRANTS — measured, not assumed
----------------------------------------------------
32 users hold it, including every supervisor. It carries **write on 37 doctypes**.
Among them:

    Salary Structure    create · write · delete · submit · cancel
    Salary Slip         create · write · submit
    Salary Component    create · write · delete
    Additional Salary   create · write · delete · submit
    Payroll Period      create · write · delete
    Leave Allocation    create · write · delete · submit · cancel   ← allocate leave to yourself
    Employee            create · write · delete
    Attendance          create · write · delete · submit · cancel
    Leave Type          create · write · delete
    Shift Type          create · write

So a supervisor could file a salary structure, submit a salary slip, allocate
themselves leave, and edit employee master data. Six of MG's manual-test findings —
editing Shift Type, editing Employee, Mark Attendance for a director, editing Leave
Type — are not six bugs. They are this one row.

WHY REMOVING IT IS SAFE — the two things supervisors actually do
---------------------------------------------------------------
**Leave approval survives.** `Leave Approver` carries `submit`, `cancel` and
`amend` on Leave Application at permlevel 0, plus `write` at permlevel 1 — entirely
independent of HR User. Verified: all 7 named approvers hold the role, and
`chong.jin.yen@` already approves for somebody while holding **no HR User at all**.
That user is the existence proof.

**Appraisal survives.** The supervisor's step is *Submit for Review*, which moves
the workflow to `Pending HR Review` — a state whose `doc_status` is still **0**. It
is a WRITE, and the `Employee` role already carries write and create on Appraisal.
Only HR Manager's *Approve* sets docstatus 1, and only HR Managers do that.

WHAT IS DELIBERATELY *NOT* FIXED HERE
-------------------------------------
`too@` cancelling somebody else's Employee Performance Feedback is a DIFFERENT root
cause — the **Employee** role itself carries `submit` and `cancel` on EPF. Removing
HR User will not touch it. Tracked separately so it does not get lost behind a
change that looks like it should have covered it.
"""

import frappe

ROLE = "HR User"

# What a supervisor MUST still be able to do, and what they must NOT.
# Asserted as a function rather than typed into `bench console`, because piping a
# script there executes it cell by cell and silently swallows loops (quirk #27).
MUST_KEEP = [
    ("Leave Application", "write"), ("Leave Application", "submit"),
    ("Appraisal", "write"), ("Appraisal", "create"),
    ("Finger Log", "read"), ("Attendance", "read"),
]
MUST_LOSE = [
    ("Shift Type", "write"), ("Employee", "write"), ("Leave Type", "write"),
    ("Attendance", "write"), ("Attendance", "submit"),
    ("Salary Structure", "write"), ("Salary Slip", "submit"),
    ("Leave Allocation", "submit"), ("Holiday List", "write"),
]


def verify(users="too@caffood.com,production1@caffood.com"):
    """Did the supervisors keep their job and lose the rest?"""
    frappe.set_user("Administrator")
    bad = []
    for user in [u.strip() for u in users.split(",") if u.strip()]:
        frappe.set_user(user)
        for dt, ptype in MUST_KEEP:
            try:
                ok = frappe.has_permission(dt, ptype)
            except Exception as e:
                ok = f"ERR {e}"
            print(f"  KEEP  {user:26s} {dt:20s} {ptype:8s} {ok}")
            if ok is not True:
                bad.append(f"LOST {dt}.{ptype} for {user}")
        for dt, ptype in MUST_LOSE:
            try:
                ok = frappe.has_permission(dt, ptype)
            except Exception:
                ok = False
            print(f"  LOSE  {user:26s} {dt:20s} {ptype:8s} {ok}")
            if ok is True:
                bad.append(f"STILL HAS {dt}.{ptype} for {user}")
    frappe.set_user("Administrator")
    print("\n" + ("🔴 " + "; ".join(bad) if bad else
                  "✅ every supervisor kept their job and lost the rest"))
    return {"problems": bad}

# MG's two: the people who are actually HR staff.
KEEP = {
    "natalie@caffood.com": "Chen Xiao Natalie (HR-EMP-00006) — HR Manager",
    "fiza@caffood.com": "Afiza binti Mustafa (HR-EMP-00004) — HR Manager",
    "Administrator": "the system account; bypasses permissions anyway",
}


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")

    holders = sorted({r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "User"}, fields=["parent"])})
    revoke = [u for u in holders if u not in KEEP]

    # The safety question, asked every run rather than trusted: does anybody who
    # is NAMED as somebody's leave approver depend on this role to approve?
    approvers = {e.leave_approver for e in frappe.get_all(
        "Employee", filters={"status": "Active", "leave_approver": ("!=", "")},
        fields=["leave_approver"]) if e.leave_approver}
    at_risk = [a for a in approvers
               if a in revoke
               and not frappe.db.exists("Has Role", {"parent": a, "parenttype": "User",
                                                     "role": "Leave Approver"})
               and not frappe.db.exists("Has Role", {"parent": a, "parenttype": "User",
                                                     "role": "HR Manager"})]

    print(f"\n{ROLE} holders: {len(holders)}")
    print(f"\nKEEPING ({len(set(KEEP) & set(holders))}):")
    for u in sorted(set(KEEP) & set(holders)):
        print(f"  = {u:30s} {KEEP[u]}")
    print(f"\nREVOKING ({len(revoke)}):")
    for u in revoke:
        tags = []
        if u in approvers:
            tags.append("leave approver")
        if frappe.db.exists("Has Role", {"parent": u, "parenttype": "User",
                                         "role": "HR Manager"}):
            tags.append("HR Manager")
        print(f"  - {u:30s} {' · '.join(tags)}")

    if at_risk:
        print(f"\n🔴 STOP — these approve leave and would lose the ability: {at_risk}")
        print("   Grant them 'Leave Approver' first, then re-run.")
        return {"blocked": at_risk}
    print("\n✅ No named leave approver depends on this role — all hold "
          "'Leave Approver' or 'HR Manager' in their own right.")

    if not apply:
        print("\n(report only — pass apply=1 to revoke)")
        return {"revoke": len(revoke)}

    for u in revoke:
        frappe.get_doc("User", u).remove_roles(ROLE)
    frappe.db.commit()
    frappe.clear_cache()

    after = {r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "User"}, fields=["parent"])}
    print(f"\nDONE — {ROLE} now held by {len(after)}: {sorted(after)}")
    print("Affected users must RELOAD their browser.")
    return {"revoked": len(revoke), "remaining": sorted(after)}
