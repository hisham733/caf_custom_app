"""Import the production User list onto the test server. MG, 2026-08-13.

Purpose : appraisal and Leave Application only work for an employee who has a
          User account of type System User. This brings prod's user list across.
Run     : bench --site <site> execute caf.scripts.user_import.plan     # DRY RUN
          bench --site <site> execute caf.scripts.user_import.apply
Needs   : /tmp/user_from_server.csv   (docker cp it in)
Refs    : PROTOCOL §C5 §C6 §C7 · OD-76 · roadmap 6b

🔴 FOUR THINGS THIS REFUSES TO DO, EACH FOUND BY MEASURING THE FILE FIRST
------------------------------------------------------------------------
1. **It keys on `Name`, never on `Email`.** Two rows disagree — `Administrator`
   carries `admin@example.com` and `Guest` carries `guest@example.com`. Keyed on
   email, the import would have created a SECOND Administrator and a second
   Guest. Both are on SKIP below regardless.

2. **It never writes a welcome email.** 23 rows carry `Send Welcome Email = 1`
   and every address is a real `@caffood.com` mailbox. A dev-server import that
   mails 23 real people is not a dev-server import.

3. **It never carries a credential.** 106 rows hold a live `Reset Password Key`
   and 3 hold an `Api Key`/`Api Secret`. A reset key is a working credential for
   that account; it has no business being copied anywhere.

4. **It sets NO ROLES, because the export contains none.** There is no `Roles`
   column — roles live in the `Has Role` child table, which was not exported.
   21 rows name a `Role Profile`, and 6 of the 7 profiles do not exist on this
   server either. See `roles_gap()`: this is reported, never guessed.

WHAT THE FILE ACTUALLY CONTAINS — measured 2026-08-13
-----------------------------------------------------
    143 rows   115 already exist here   28 would be created
    30 disabled (leavers)   7 Website Users   136 System Users

⚠️ **AND THE THING THAT MATTERS MOST: this import does NOT give the 31 active
employees who lack a `user_id` an account.** Not one of them matches a CSV row,
by email or by name — 28 carry no email on the Employee record at all, and their
names are not in the file. They have no user in PRODUCTION either. Of the 28
users this would create, **2** map to an Employee here and one of those has
status `Left`. So the gap is not "the test server is missing users"; it is that
those employees have never had a login anywhere. That is a business question,
not an import.

Changelog
---------
1.0  2026-08-13  Initial
"""

import csv

import frappe
from frappe.utils import cint

CSV = "/tmp/user_from_server.csv"

# Framework-owned. Never touch, whatever the file says.
SKIP = {"administrator", "guest"}

# Copied across. Everything NOT in this list is deliberately left behind —
# credentials, session history, UI state and anything host-specific.
FIELDS = ["email", "first_name", "middle_name", "last_name", "username",
          "language", "time_zone", "gender", "phone", "mobile_no",
          "user_type", "enabled"]

CSV_TO_FIELD = {
    "Email": "email", "First Name": "first_name", "Middle Name": "middle_name",
    "Last Name": "last_name", "Username": "username", "Language": "language",
    "Time Zone": "time_zone", "Gender": "gender", "Phone": "phone",
    "Mobile No": "mobile_no", "User Type": "user_type", "Enabled": "enabled",
}

# 🔴 Never imported. Listed explicitly so the omission is a decision, not an
# oversight somebody "fixes" later.
NEVER = ["Reset Password Key", "Api Key", "Api Secret", "New Password",
         "Last Login", "Last Active", "Last IP", "Last Known Versions",
         "Send Welcome Email", "Home Settings", "Onboarding Status"]


def rows():
    try:
        fh = open(CSV, newline="", encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        frappe.throw(f"{CSV} not found — docker cp the export in first")
    with fh:
        return [r for r in csv.DictReader(fh) if (r.get("Name") or "").strip()]


def employee_for(user):
    return frappe.db.get_value("Employee", {"user_id": user},
                               ["name", "status", "employee_name"], as_dict=True)


def enabled_for(name, csv_enabled):
    """🔴 MG: *"be mindful for emp already left."*

    The CSV's `enabled` flag is NOT taken at face value. Measured 2026-08-13:
    **38 users are enabled in production and every single one belongs to an
    employee whose status here is `Left`.** Production has simply never disabled
    their logins — which is worth telling CAF about, and is certainly not a
    thing to copy onto another server.

    So a linked Employee who is not Active forces `enabled = 0`, whatever the
    file says. An account with no Employee at all (service and shared accounts
    like `production.a.caf@gmail.com`) keeps the file's value, because there is
    no employment status to check it against.
    """
    e = employee_for(name)
    if e and e.status != "Active":
        return 0, f"employee {e.name} is {e.status}"
    return cint(csv_enabled), ""


def classify():
    out = {"create": [], "update": [], "skip": [], "unchanged": [], "held": []}
    for r in rows():
        name = (r.get("Name") or "").strip()
        if name.lower() in SKIP:
            out["skip"].append((name, "framework account"))
            continue
        want = {f: (r.get(c) or "").strip() for c, f in CSV_TO_FIELD.items()}
        csv_enabled = cint(want["enabled"])
        want["enabled"], why = enabled_for(name, csv_enabled)
        if why and csv_enabled != want["enabled"]:
            out["held"].append((name, csv_enabled, want["enabled"], why))
        if not frappe.db.exists("User", name):
            out["create"].append((name, want))
            continue
        cur = frappe.db.get_value("User", name, FIELDS, as_dict=True) or {}
        diff = {f: (cur.get(f), want[f]) for f in ("enabled", "user_type")
                if str(cur.get(f) or "") != str(want[f] or "")}
        (out["update"] if diff else out["unchanged"]).append((name, diff))
    return out


def roles_gap():
    """What we CANNOT set, and why. §F2 — say the zero out loud."""
    src = rows()
    has_roles_col = "Roles" in (src[0].keys() if src else [])
    profiles = {}
    for r in src:
        p = (r.get("Role Profile Name") or "").strip()
        if p:
            profiles[p] = profiles.get(p, 0) + 1
    missing = {p: n for p, n in profiles.items()
               if not frappe.db.exists("Role Profile", p)}
    return {"has_roles_column": has_roles_col, "profiles": profiles,
            "missing_profiles": missing,
            "rows_with_no_role_information": len(src) - sum(profiles.values())}


def plan():
    """🔴 DRY RUN. Writes nothing."""
    c = classify()
    g = roles_gap()
    print("USER IMPORT — 🔴 DRY RUN, NOTHING WRITTEN")
    print("=" * 84)
    print(f"   would CREATE   {len(c['create']):>4}")
    print(f"   would UPDATE   {len(c['update']):>4}   (enabled / user_type only)")
    print(f"   unchanged      {len(c['unchanged']):>4}")
    print(f"   skipped        {len(c['skip']):>4}   {[n for n, _ in c['skip']]}")

    print(f"\nCREATE — {len(c['create'])}")
    print(f"   {'user':34s} {'type':13s} enabled")
    for name, w in sorted(c["create"]):
        print(f"   {name[:34]:34s} {w['user_type']:13s} {w['enabled']}")

    if c["update"]:
        print(f"\nUPDATE — {len(c['update'])}")
        for name, diff in sorted(c["update"]):
            for f, (was, now) in diff.items():
                print(f"   {name[:34]:34s} {f}: {was} ➜ {now}")

    if c["held"]:
        print(f"\n🔴 HELD DISABLED — the file says enabled, the employee has LEFT "
              f"({len(c['held'])})")
        print("   Production has never disabled these logins. That is a finding")
        print("   about production, and not a thing to copy onto another server.")
        for name, was, now, why in sorted(c["held"]):
            e = employee_for(name)
            print(f"   {name[:34]:34s} csv={was} ➜ {now}   {why}"
                  f"   {(e.employee_name or '')[:24] if e else ''}")

    print(f"\n🔴 ROLES — NOT IMPORTED, BECAUSE THE EXPORT HAS NONE")
    print(f"   'Roles' column in the file      : {g['has_roles_column']}")
    print(f"   rows with NO role information   : {g['rows_with_no_role_information']} of {len(rows())}")
    print(f"   rows naming a Role Profile      : {sum(g['profiles'].values())}")
    for p, n in sorted(g["profiles"].items(), key=lambda x: -x[1]):
        print(f"      {p:26s} {n:>3} users   "
              f"{'🔴 profile MISSING here' if p in g['missing_profiles'] else 'profile exists'}")
    print(f"   ➜ a second export of the `Has Role` child table is needed before "
          f"roles can be set at all.")

    print(f"\nNEVER IMPORTED (by design): {', '.join(NEVER)}")
    print(f"\n🔴 Nothing was written. Run `apply` to make the changes above.")
    return {k: len(v) for k, v in c.items()}


def apply():
    """Create and update Users. Sets no roles and sends no email."""
    c = classify()
    made, changed = [], []

    for name, want in c["create"]:
        doc = frappe.new_doc("User")
        doc.name = name
        for f, v in want.items():
            setattr(doc, f, v)
        if not doc.first_name:
            doc.first_name = name.split("@")[0]
        # 🔴 The two that must never be left to the defaults.
        doc.send_welcome_email = 0
        doc.flags.no_welcome_mail = True
        doc.flags.ignore_permissions = True
        doc.insert()
        made.append(name)

    for name, diff in c["update"]:
        for f, (_was, now) in diff.items():
            frappe.db.set_value("User", name, f, now)
        changed.append(name)

    frappe.db.commit()
    print(f"created {len(made)}, updated {len(changed)}")
    print(f"⚠️ NO ROLES were set — the export contains none. Every created user "
          f"has only the framework defaults until a `Has Role` export arrives.")
    return {"created": made, "updated": changed}
