"""Fill `employee_name` on manifest rows created before the field existed.

    bench --site <site> execute caf.scripts.backfill_manifest_employee_name.run
    bench --site <site> execute caf.scripts.backfill_manifest_employee_name.run --kwargs "{'apply':1}"

MG's manual-test finding, 2026-09-01: *typing "Sutia" into the manifest's Employee
filter finds nothing.*

🔴 THE CAUSE, measured rather than guessed
------------------------------------------
Frappe's grid column filter compares the **stored** value, never the rendered one
(`frappe/public/js/frappe/form/grid.js:726`):

    } else if (fieldvalue && fieldvalue.toLowerCase().includes(value)) {

For a **Link** field `fieldvalue` is the docname. So the Employee column *displays*
`Md Harun Or Roshid` (Frappe resolves the link title for display) and *filters* on
`HR-EMP-00054`. Measured on a real 615-row manifest:

    typing "Harun"          ->   0 rows
    typing "HR-EMP-00054"   ->   7 rows

Which is the same ID-vs-name trap as `frappe.db.get_link_options` filtering on
`name`, in a different place. The column looked searchable, and was — by an
identifier nobody knows.

THE FIX
-------
`employee_name` is now a **Data** field on the row, so line 726 compares the name
itself. It takes the grid column; `employee` keeps the data and the link, one
click away in the row detail. The grid looks identical — it already showed the
name — and the filter now answers the question HR actually asks.

This script fills the field for manifests written before it existed. Without it,
every historical batch stays unsearchable and the fix looks broken on exactly the
batches HR is most likely to open.

⚠️ Uses the employee's name **as it is now**. For historical rows that is the best
available answer — the importer freezes the name at import time from here on, but
it cannot do so retrospectively for runs that never recorded it.
"""

import frappe


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")

    names = {e.name: e.employee_name for e in frappe.get_all(
        "Employee", fields=["name", "employee_name"])}

    rows = frappe.db.sql("""
        SELECT name, parent, employee, employee_name
          FROM `tabIngress Import Row`
         WHERE IFNULL(employee, '') <> '' AND IFNULL(employee_name, '') = ''
    """, as_dict=True)

    batches = sorted({r.parent for r in rows})
    missing = sorted({r.employee for r in rows if r.employee not in names})

    print(f"  manifest rows needing a name : {len(rows)}")
    print(f"  batches affected             : {len(batches)}"
          f"{' — ' + ', '.join(batches[:6]) if batches else ''}")
    if missing:
        print(f"  🔴 employees no longer present: {len(missing)} — {missing[:8]}")
        print("     (their rows keep an empty name; the Employee ID is still on "
              "the row, so nothing is lost)")

    total = frappe.db.count("Ingress Import Row")
    already = total - len(rows)
    print(f"  rows already carrying a name : {already} of {total}")

    if not apply:
        print("\n(report only — pass apply=1 to backfill)")
        return {"would_fill": len(rows), "batches": len(batches)}

    filled = 0
    for r in rows:
        who = names.get(r.employee)
        if not who:
            continue
        # `update_modified=False`: a manifest row is a historical record, and
        # touching `modified` would make every one of them look edited today.
        frappe.db.set_value("Ingress Import Row", r.name, "employee_name", who,
                            update_modified=False)
        filled += 1

    frappe.db.commit()
    frappe.clear_cache()
    print(f"\nDONE — filled {filled} row(s) across {len(batches)} batch(es).")
    return {"filled": filled, "batches": len(batches), "unresolved": missing}


def verify():
    """No row with an employee should be left without a name."""
    frappe.set_user("Administrator")
    gap = frappe.db.sql("""
        SELECT parent, COUNT(*) n FROM `tabIngress Import Row`
         WHERE IFNULL(employee, '') <> '' AND IFNULL(employee_name, '') = ''
      GROUP BY parent""", as_dict=True)
    total = frappe.db.count("Ingress Import Row")
    named = frappe.db.count("Ingress Import Row", {"employee_name": ("!=", "")})
    print(f"  {named} of {total} manifest rows carry a searchable name")
    for g in gap:
        print(f"  🔴 {g.parent}: {g.n} row(s) still blank")
    print("\n" + ("🔴 backfill incomplete" if gap else
                  "✅ every manifest row with an employee is searchable by name"))
    return {"problems": [g.parent for g in gap]}
