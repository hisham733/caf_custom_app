"""Import the production role assignments (`Has Role`). MG, 2026-08-13.

Purpose : give every imported User the roles it holds in production, so the
          appraisal and leave workflows can be exercised as the RIGHT person.
Run     : bench --site <site> execute caf.scripts.role_import.plan    # DRY RUN
          bench --site <site> execute caf.scripts.role_import.apply
Needs   : /tmp/has_role.csv   (Name, Role, Parent, Parenttype)
Refs    : PROTOCOL §C1 §C5 §C6 · OD-76 · roadmap 6b · scripts/user_import.py

WHY THIS MATTERS MORE THAN IT LOOKS
-----------------------------------
PROTOCOL §C1: **Administrator bypasses every permission check**, so a suite that
runs as Administrator passes identically against a broken model. Testing as the
right ROLE is the only way the permission model is proven — and until now this
server had no faithful role data to test against. **19 users hold `Leave
Approver` in production**, which is exactly the population Chunk 6b's workflow
has to be built for.

MEASURED BEFORE BUILDING — 2026-08-13
--------------------------------------
    1,863 rows   137 distinct users   58 distinct roles
    all 137 users exist here (they did NOT before `user_import` ran)
    90 users would gain at least one role — 886 role rows
    47 users are already correct

🔴 ADDITIVE ONLY, AND DELIBERATELY
This never REMOVES a role. Two reasons. The dev server carries fixtures the
production export knows nothing about — `hr.manager.test@caffood.com`,
`hr.user.test@caffood.com` and the director accounts that Chunk R's role pass
depends on — and stripping "extra" roles would quietly dismantle the only suite
that proves the permission model. And a role removed is a permission decision;
a role added is a copy. `plan()` reports what this server holds that production
does not, so the difference is visible rather than acted on.

⚠️ FOUR ROLES DO NOT EXIST HERE, AND NONE OF THEM IS CREATED
`MG_Approve` (11 users) — **MG, 2026-08-13: *"ignore MG approve."*** It is
referenced nowhere in the CAF app code, so nothing here depends on it. And
`LMS User`, `Workspace user`, `ImportExport User` belong to apps that are not
installed on this server, so the roles would be inert even if created.

**No Role document is created by this script.** Missing roles are reported and
their assignments dropped, which is visible in `plan()` and stated again by
`apply()`. Creating an empty Role would grant nothing anyway — permissions come
from DocPerm / Custom DocPerm and none are imported — so reporting is the honest
option and leaves no half-real role behind.

⚠️ TWO FRAMEWORK BEHAVIOURS WILL EAT SOME OF THIS, BY DESIGN
- **§C5** — the `Employee` role is auto-stripped from any user with no Employee
  mapped to it. 113 rows carry it; the count afterwards will be lower, and that
  is Frappe working correctly, not the import failing.
- **§C6** — a Website User cannot hold desk roles. 7 users in the export are
  Website Users and their desk-role rows will not stick.
`plan()` predicts both so the shortfall is expected rather than investigated.

Changelog
---------
1.0  2026-08-13  Initial
"""

import csv

import frappe

CSV = "/tmp/has_role.csv"
SKIP_USERS = {"administrator", "guest"}

# 🔴 Assignments this import REFUSES, whatever the export says. MG, 2026-08-13.
#
# `telegram_bot@caffood.com` holds HR Manager in production, which resolves to
# **write + submit on Finger Log** — so a bot account can rewrite `final_ot`,
# and `final_ot` drives overtime pay. MG: *"only the 2 I mentioned are the real
# HR Manager … the rest are IT personnel + wrong role assignment at prod … if
# necessary then remove HR manager from BOT."*
#
# ⚠️ It lives here rather than being deleted by hand because this script is
# ADDITIVE: a hand-deleted row is silently restored by the next `apply()`, and
# nothing would say so. Refusing the assignment is the only form of the fix that
# survives a re-run.
#
# ⚠️ NOT a fix for production. MG is correcting the real server separately;
# that is outside this project. See OD-80.
REFUSE = {("telegram_bot@caffood.com", "HR Manager")}


def rows():
    try:
        fh = open(CSV, newline="", encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        frappe.throw(f"{CSV} not found — docker cp the export in first")
    with fh:
        return list(csv.DictReader(fh))


def wanted():
    """{user: {role, ...}} from the export, for User rows only."""
    out = {}
    for r in rows():
        if (r.get("Parenttype") or "User").strip() not in ("", "User"):
            continue
        u = (r.get("Parent") or "").strip()
        role = (r.get("Role") or "").strip()
        if not u or not role or u.lower() in SKIP_USERS:
            continue
        if (u.lower(), role) in {(a.lower(), b) for a, b in REFUSE}:
            continue
        out.setdefault(u, set()).add(role)
    return out


def strip_refused():
    """Remove the REFUSE assignments that are already on this server.

    Separate from `apply()` on purpose: `apply()` only ever adds, and a function
    that removes a permission should be one you have to call by name.
    """
    gone = []
    for user, role in REFUSE:
        for r in frappe.get_all("Has Role",
                                filters={"parent": user, "parenttype": "User",
                                         "role": role}, pluck="name"):
            frappe.delete_doc("Has Role", r, ignore_permissions=True, force=True)
            gone.append((user, role))
    frappe.db.commit()
    for user, role in gone:
        frappe.get_doc("User", user).add_comment(
            "Comment",
            f"`{role}` removed by caf.scripts.role_import.strip_refused — a bot "
            f"account resolving to write+submit on Finger Log can rewrite "
            f"final_ot, which drives overtime pay. MG, 2026-08-13. OD-80.")
    print(f"removed {len(gone)}: {gone or '(nothing to remove)'}")
    return gone


def current(user):
    return {r.role for r in frappe.get_all(
        "Has Role", filters={"parent": user, "parenttype": "User"},
        fields=["role"])}


def classify():
    want = wanted()
    have_user = {u.lower(): u for u in frappe.get_all("User", pluck="name")}
    have_role = {r.lower(): r for r in frappe.get_all("Role", pluck="name")}

    missing_roles, missing_users = set(), []
    add, extra, ok = {}, {}, []
    for u, roles in want.items():
        for role in roles:
            if role.lower() not in have_role:
                missing_roles.add(role)
        if u.lower() not in have_user:
            missing_users.append(u)
            continue
        real = have_user[u.lower()]
        cur = current(real)
        new = {r for r in roles if r not in cur}
        gone = {r for r in cur if r not in roles}
        if new:
            add[real] = sorted(new)
        else:
            ok.append(real)
        if gone:
            extra[real] = sorted(gone)
    return {"add": add, "extra": extra, "ok": ok,
            "missing_roles": sorted(missing_roles),
            "missing_users": sorted(missing_users), "want": want}


def predict_shortfall(c):
    """§C5 / §C6 — what the framework will refuse to keep, and why."""
    no_emp, website = [], []
    for user, roles in c["add"].items():
        if "Employee" in roles and not frappe.db.exists("Employee", {"user_id": user}):
            no_emp.append(user)
        if frappe.db.get_value("User", user, "user_type") == "Website User":
            website.append(user)
    return {"employee_role_will_be_stripped": no_emp, "website_users": website}


def plan():
    """🔴 DRY RUN. Writes nothing."""
    c = classify()
    s = predict_shortfall(c)
    total = sum(len(v) for v in c["add"].values())

    print("ROLE IMPORT — 🔴 DRY RUN, NOTHING WRITTEN")
    print("=" * 84)
    print(f"   users in the export        {len(c['want']):>5}")
    print(f"   users gaining a role       {len(c['add']):>5}")
    print(f"   already correct            {len(c['ok']):>5}")
    print(f"   role rows to ADD           {total:>5}")
    print(f"   users not on this server   {len(c['missing_users']):>5}")

    print(f"\n🔴 ROLES THAT DO NOT EXIST HERE — NOT created, assignments dropped "
          f"({len(c['missing_roles'])})")
    for r in c["missing_roles"]:
        n = len([1 for roles in c["want"].values() if r in roles])
        why = ("MG: ignore" if r == "MG_Approve" else "app not installed here")
        print(f"   {r:24s} {n:>3} users   {why}")

    print(f"\n⚠️ PREDICTED SHORTFALL — the framework will refuse these, correctly")
    print(f"   §C5 `Employee` role will be auto-stripped (no Employee maps to "
          f"the user): {len(s['employee_role_will_be_stripped'])}")
    print(f"   §C6 Website Users cannot hold desk roles: "
          f"{len(s['website_users'])}  {s['website_users'][:6]}")

    if c["extra"]:
        print(f"\n⚠️ THIS SERVER HOLDS ROLES PRODUCTION DOES NOT ({len(c['extra'])} users)")
        print("   NOT removed — the Chunk R fixtures live here and stripping them")
        print("   would dismantle the only suite that proves the permission model.")
        for u, roles in sorted(c["extra"].items())[:12]:
            print(f"   {u[:34]:34s} {', '.join(roles)[:60]}")

    print(f"\nADD — first 15 of {len(c['add'])} users")
    for u, roles in sorted(c["add"].items())[:15]:
        print(f"   {u[:34]:34s} + {', '.join(roles)[:62]}")

    print(f"\n🔴 Nothing was written. Run `apply` to make the changes above.")
    return {"users": len(c["add"]), "rows": total,
            "missing_roles": len(c["missing_roles"])}


def apply():
    """Assign roles that EXIST here. Creates no Role document — see the header."""
    c = classify()
    have_role = {r.lower() for r in frappe.get_all("Role", pluck="name")}

    touched, added, dropped = 0, 0, 0
    for user, roles in c["add"].items():
        real = [r for r in roles if r.lower() in have_role]
        dropped += len(roles) - len(real)
        if not real:
            continue
        doc = frappe.get_doc("User", user)
        before = {r.role for r in doc.roles}
        for role in real:
            if role in before:
                continue
            doc.append("roles", {"role": role})
        doc.flags.ignore_permissions = True
        doc.save()
        added += len(current(user) - before)
        touched += 1
    frappe.db.commit()

    print(f"updated {touched} users, {added} role rows actually stuck")
    print(f"dropped {dropped} assignments for roles that do not exist here: "
          f"{', '.join(c['missing_roles'])} — none was created, by decision")
    print(f"⚠️ Fewer rows stick than were offered — §C5 strips `Employee` from a "
          f"user with no Employee, and §C6 refuses desk roles on a Website User. "
          f"`plan()` predicts both.")
    return {"users": touched, "rows_added": added}


def verify():
    """Re-read and report what actually landed, per role."""
    c = classify()
    still = {u: r for u, r in classify()["add"].items()}
    print(f"users still missing a role after import : {len(still)}")
    for u, roles in sorted(still.items())[:20]:
        ut = frappe.db.get_value("User", u, "user_type")
        emp = frappe.db.exists("Employee", {"user_id": u})
        print(f"   {u[:34]:34s} {ut:12s} employee={'yes' if emp else 'no':3s} "
              f"missing: {', '.join(roles)[:48]}")
    for role in ("Leave Approver", "HR User", "HR Manager", "Employee"):
        n = frappe.db.count("Has Role", {"role": role, "parenttype": "User"})
        print(f"   users holding {role:16s} : {n}")
    return still
