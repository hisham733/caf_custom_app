"""Name a Leave Period by the year it COVERS, and show a Leave Policy by its title.

    bench --site <site> execute caf.scripts.leave_naming_fix.run
    bench --site <site> execute caf.scripts.leave_naming_fix.run --kwargs "{'apply':1}"
    bench --site <site> execute caf.scripts.leave_naming_fix.verify

MG approved both, 2026-09-01. **FBR64.**

🔴 WHY THE RENAME IS NOT COSMETIC
---------------------------------
`Leave Period` autonames `HR-LPR-.YYYY.-.#####`, where `YYYY` is the year the
record was **created**. So this site holds:

    HR-LPR-2026-00001  ->  2026-01-01 … 2026-12-31
    HR-LPR-2026-00002  ->  2027-01-01 … 2027-12-31     ← still says "2026"

Choosing `…-00002` for a 2026 allocation run offers **all 89** employees instead
of the 58 unallocated — because stock's "skip anyone already allocated" filter
compares against the *period's* dates, and no 2026 allocation overlaps a 2027
period. **Click through and 31 people receive a second allocation.**

Found by falling into it while driving the Leave Control Panel on 2026-09-01.

MG proposed dropping the year and using a plain index. Named by COVERAGE instead,
because an index removes the wrong information without adding any: the problem is
not that the name carries a year, it is that it carries the **wrong** year.
`CAF 2026` also matches what CAF's own periodic doctypes already do —
`Appraisal Cycle` is `2027-12`, `Holiday List` is `CAF Mon-Sat 2027`.

⚠️ **Renaming is safe here**: `allow_rename: 1`, and `frappe.rename_doc` repoints
every Link that references the old name. The references are counted BEFORE and
AFTER and the run refuses if the totals do not match.

WHY THE PROPERTY SETTER
-----------------------
`Leave Policy` has `title_field: "title"` and does NOT set
`show_title_field_in_link`, so every Link field shows `HR-LPOL-2026-00001` rather
than *"CAF Service under 2 years"*. HR picks the entitlement band for 89 people
from an opaque id.

The **fourth** appearance of the name-vs-id family (FBR61), after
`get_link_options` filtering on `name`, the employee picker, and the import
manifest's grid filter.

⚠️ The Leave Policy NAME is left alone. Unlike a Leave Period it covers no period,
so `HR-LPOL-2026-00003` is noise rather than deception — and renaming a submittable
doctype's records buys nothing once the title is visible.
"""

import frappe

# The Link fields that point at a Leave Period. Counted before and after so a
# rename that failed to repoint something is caught rather than assumed.
REFERENCES = (
    ("Leave Allocation", "leave_period"),
    ("Leave Policy Assignment", "leave_period"),
)


def _plan():
    """(old, new) per Leave Period, named by the year it actually covers."""
    out = []
    for p in frappe.get_all("Leave Period",
                            fields=["name", "from_date", "to_date"],
                            order_by="from_date"):
        year = frappe.utils.getdate(p.from_date).year
        want = f"CAF {year}"
        # A period that does not span one calendar year gets its full span, so
        # the name never claims more than it covers.
        if (frappe.utils.getdate(p.from_date).month,
                frappe.utils.getdate(p.from_date).day) != (1, 1) \
                or frappe.utils.getdate(p.to_date).year != year:
            want = f"CAF {p.from_date} to {p.to_date}"
        out.append((p.name, want, p.from_date, p.to_date))
    return out


def _ref_counts():
    return {f"{dt}.{field}": frappe.db.count(dt, {field: ("!=", "")})
            for dt, field in REFERENCES}


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")
    before = _ref_counts()

    print("  Leave Period renames (named by the year COVERED):")
    plan = _plan()
    todo = []
    for old, new, f, t in plan:
        if old == new:
            print(f"    =  {old:22s} already correct  ({f} … {t})")
            continue
        clash = frappe.db.exists("Leave Period", new)
        flag = "🔴 NAME TAKEN" if clash and clash != old else \
               ("RENAME" if apply else "would rename")
        print(f"    -> {old:22s} ➜ {new:14s} ({f} … {t})  {flag}")
        if not (clash and clash != old):
            todo.append((old, new))

    ps_exists = frappe.db.exists("Property Setter",
                                 {"doc_type": "Leave Policy",
                                  "property": "show_title_field_in_link"})
    print(f"\n  Leave Policy show_title_field_in_link: "
          f"{'set' if ps_exists else '🔴 NOT SET — HR picks a policy by its id'}")
    for p in frappe.get_all("Leave Policy", fields=["name", "title"]):
        print(f"    {p.name}  would display as  {p.title!r}")

    print(f"\n  Link references before: {before}")

    if not apply:
        print("\n(report only — pass apply=1 to rename and add the property setter)")
        return {"renames": len(todo), "property_setter_missing": not ps_exists}

    # ⚠️ `frappe.rename_doc` (the top-level wrapper in frappe/__init__.py) does NOT
    # accept `ignore_permissions` — only the model-level function does, and the
    # wrapper makes the rest keyword-only. Passing it to the wrapper raises
    # `TypeError: unexpected keyword argument`, which `bench execute` then masks
    # behind its own fake NameError (quirks §18).
    from frappe.model.rename_doc import rename_doc

    for old, new in todo:
        rename_doc("Leave Period", old, new, force=True, ignore_permissions=True)
        print(f"    renamed {old} ➜ {new}")

    if not ps_exists:
        frappe.make_property_setter({
            "doctype": "Leave Policy",
            "doctype_or_field": "DocType",
            "property": "show_title_field_in_link",
            "value": 1,
            "property_type": "Check",
        }, is_system_generated=False)
        print("    added Property Setter: Leave Policy.show_title_field_in_link = 1")

    frappe.db.commit()
    frappe.clear_cache()

    after = _ref_counts()
    print(f"\n  Link references after:  {after}")
    if before != after:
        print("  🔴 REFERENCE COUNT CHANGED — a link was lost, investigate")
    else:
        print("  ✅ every Link reference survived the rename")

    print(f"\nDONE — renamed {len(todo)}, property setter "
          f"{'added' if not ps_exists else 'already present'}")
    return {"renamed": todo, "refs_ok": before == after}


def verify():
    frappe.set_user("Administrator")
    bad = []
    # 🔴 Asserted against the EXACT name `_plan()` would produce, not "does the
    # year appear somewhere in the string". The looser test passed by luck on two
    # of the three — `HR-LPR-2025-00001` contains "2025" and covers 2025 — which
    # is precisely the kind of accidental green this project keeps being bitten by.
    for old, want, f, t in _plan():
        ok = old == want
        if not ok:
            bad.append(f"{old} covers {f}…{t} and should be named {want!r}")
        print(f"  {'ok  ' if ok else '🔴 '} {old:16s} {f} … {t}"
              f"{'' if ok else f'   want {want!r}'}")

    ps = frappe.db.exists("Property Setter", {"doc_type": "Leave Policy",
                                              "property": "show_title_field_in_link"})
    if not ps:
        bad.append("Leave Policy still shows its docname in Link fields")
    print(f"\n  Leave Policy shows its title in Link fields: {'yes' if ps else '🔴 no'}")

    # Nothing may point at a Leave Period that no longer exists.
    for dt, field in REFERENCES:
        orphan = frappe.db.sql(f"""
            SELECT COUNT(*) FROM `tab{dt}` t
             WHERE IFNULL(t.`{field}`, '') <> ''
               AND NOT EXISTS (SELECT 1 FROM `tabLeave Period` lp
                                WHERE lp.name = t.`{field}`)""")[0][0]
        if orphan:
            bad.append(f"{dt}.{field} has {orphan} row(s) pointing at a missing period")
        print(f"  {dt}.{field}: {orphan} orphaned reference(s)")

    print("\n" + ("🔴 " + "; ".join(bad) if bad else
                  "✅ every Leave Period names the year it covers, Leave Policy "
                  "shows its title, and no reference was lost"))
    return {"problems": bad}
