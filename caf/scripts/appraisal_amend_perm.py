"""OD-81b — let an HR Manager amend a submitted Appraisal. MG, 2026-08-13.

Run   : bench --site <site> execute caf.scripts.appraisal_amend_perm.plan
        bench --site <site> execute caf.scripts.appraisal_amend_perm.apply
Refs  : OD-81 · OD-48 · test plan **AM4** · PROTOCOL §C-bis

THE PROBLEM, MEASURED
---------------------
Amend is the sanctioned route for correcting a submitted record (OD-48), and on
Appraisal **two different gates block two different roles**:

    role          DocPerm                 CAF has_permission hook      result
    HR Manager    cancel = 0, amend = 0   is_hr_manager -> True        BLOCKED
    HR User       cancel = 1, amend = 1   may_appraise -> not their    BLOCKED
                                          supervisor

So nobody who should be correcting appraisals can. MG chose **B1**: grant HR
Manager `cancel` + `amend`. That is sufficient on its own, because CAF's own
hook (`caf.caf.overrides.appraisal.has_permission`) already returns True for
`is_hr_manager` — the DocPerm row is the only thing in the way.

🔴 WHY THIS IS A SCRIPT AND NOT A HAND EDIT — PROTOCOL §C-bis
--------------------------------------------------------------
**A `Custom DocPerm` REPLACES `DocPerm` for that doctype entirely.**
`frappe.permissions.get_all_perms()` keeps a DocPerm row only
`if p.parent not in doctypes_with_custom_perms`. Appraisal currently has **0**
Custom DocPerm rows and **4** DocPerm rows (HR User, HR Manager, Employee,
System Manager). Creating one Custom DocPerm row by hand would silently DELETE
the other three roles' access — including the `Employee` row that 117 people
rely on to see their own appraisal.

`update_permission_property()` is the safe API precisely because it calls
`setup_custom_perms()` first, which copies **every** existing DocPerm into
Custom DocPerm before changing anything. `plan()` prints the before/after of all
four roles so the replacement is visible rather than assumed.

⚠️ Custom DocPerm must then be EXPORTED to fixtures, or the change is invisible
to git and absent on the next site (§D6). `plan()` says whether it is in the
fixtures list.

Changelog
---------
1.0  2026-08-13  OD-81b
"""

import frappe

DOCTYPE = "Appraisal"
ROLE = "HR Manager"
GRANT = ("cancel", "amend")


def snapshot():
    """Every role's effective permissions on the doctype, from whichever table
    is authoritative right now."""
    custom = frappe.get_all("Custom DocPerm", filters={"parent": DOCTYPE},
                            fields=["role", "read", "write", "create", "submit",
                                    "cancel", "amend", "permlevel"])
    src = "Custom DocPerm"
    if not custom:
        custom = frappe.get_all("DocPerm", filters={"parent": DOCTYPE},
                                fields=["role", "read", "write", "create",
                                        "submit", "cancel", "amend", "permlevel"])
        src = "DocPerm"
    return src, sorted(custom, key=lambda r: r.role)


def _show(label):
    src, rows = snapshot()
    print(f"   {label} — source: {src} ({len(rows)} rows)")
    for r in rows:
        print(f"      {r.role:18s} r{r.read} w{r.write} c{r.create} s{r.submit} "
              f"x{r.cancel} a{r.amend} lvl{r.permlevel}")
    return src, rows


def plan():
    """🔴 DRY RUN."""
    print(f"OD-81b — grant {ROLE} {' + '.join(GRANT)} on {DOCTYPE}")
    print("=" * 72)
    src, rows = _show("BEFORE")
    print(f"\n   ⚠️ Custom DocPerm REPLACES DocPerm for a doctype. Applying this "
          f"converts all {len(rows)} rows above into Custom DocPerm — that is "
          f"what `update_permission_property` does, and it is why it must not be "
          f"done by hand.")
    fixtures = frappe.get_hooks("fixtures") or []
    named = any("Custom DocPerm" in str(f) for f in fixtures)
    print(f"\n   'Custom DocPerm' in the app's fixtures list: {named}"
          f"{'' if named else '   🔴 the change will be invisible to git (§D6)'}")
    print(f"\n🔴 Nothing was written.")
    return {"source": src, "roles": [r.role for r in rows], "in_fixtures": named}


def apply():
    from frappe.permissions import update_permission_property

    before_src, before = _show("BEFORE")
    for ptype in GRANT:
        update_permission_property(DOCTYPE, ROLE, 0, ptype, 1)
    frappe.clear_cache(doctype=DOCTYPE)
    frappe.db.commit()
    after_src, after = _show("AFTER")

    # 🔴 The assertion that matters is NOT "HR Manager gained two flags" — it is
    # "nobody LOST anything". §C-bis's trap is silent removal, so prove absence
    # of loss rather than presence of the grant.
    lost = []
    for b in before:
        a = next((x for x in after if x.role == b.role), None)
        if not a:
            lost.append((b.role, "ROW GONE"))
            continue
        for p in ("read", "write", "create", "submit", "cancel", "amend"):
            if b[p] and not a[p]:
                lost.append((b.role, p))
    print(f"\n   permissions LOST by any role: {lost or 'none'}")
    if lost:
        frappe.throw(f"🔴 the conversion dropped {lost} — roll back")
    print(f"   source moved {before_src} ➜ {after_src}")
    print(f"\n⚠️ Run `bench --site <site> export-fixtures` if 'Custom DocPerm' is "
          f"in the fixtures list, or this is invisible to git (§D6).")
    return {"lost": lost, "source": after_src}
