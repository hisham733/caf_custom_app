"""The manifest must be searchable by the name HR knows — MG's manual-test finding.

    bench --site <site> execute caf.tests.ingress.test_manifest_search.run

MG, 2026-09-01: *typing "Sutia" into the manifest's Employee filter finds nothing.*

🔴 THE CAUSE — a framework behaviour, measured not guessed
---------------------------------------------------------
Frappe's grid column filter compares the **stored** value and never the rendered
one (`frappe/public/js/frappe/form/grid.js:726`):

    } else if (fieldvalue && fieldvalue.toLowerCase().includes(value)) {

For a **Link** column `fieldvalue` is the docname. So the Employee column
*displayed* `Sutia` — Frappe resolves link titles for display — and *filtered* on
`HR-EMP-00031`. Measured on the real 615-row manifest INGB-2026-00117:

    typing "Harun"         ->  0 rows          typing "HR-EMP-00054"  ->  7 rows
    typing "Sutia"         ->  0 rows          (she has 7 rows in that batch)

Same ID-vs-name trap as `frappe.db.get_link_options` filtering on `name`, in a
different place. The column looked searchable and was — by an identifier nobody
knows.

THE FIX, AND WHY THESE ARE THE ASSERTIONS
-----------------------------------------
`employee_name` is a **Data** field on the row, so line 726 compares the name
itself. It takes the grid column and `employee` keeps the data and the link, one
click away in the row detail.

The filter itself is client-side and cannot be asserted from Python. What CAN be
asserted is the contract the fix rests on — the field exists, is Data, is in the
list view, is populated on every row, and `employee` is out of the list view so
the two do not both claim the column budget. If all of that holds, grid.js does
the rest; if any of it breaks, the search silently reverts to matching docnames
and nobody notices until HR tries again.

✅ Verified end to end in the desk UI on 2026-09-01: typing "Sutia" into the live
filter returned exactly 7 rows, one per work date 08-03..08-09.
"""

import frappe

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:26s} {'PASS' if ok else 'FAIL'}  {detail}")


def run():
    frappe.set_user("Administrator")
    meta = frappe.get_meta("Ingress Import Row")

    # ── MS1 — the searchable field exists and is the right TYPE ────────────
    f = meta.get_field("employee_name")
    check("MS1-DATA-NOT-LINK",
          bool(f) and f.fieldtype == "Data",
          f"`employee_name` is {f.fieldtype if f else 'MISSING'} — it must be Data, "
          f"because grid.js:726 compares the STORED value and a Link stores the "
          f"docname. A Link here would reintroduce the exact bug")

    # ── MS2 — it is the column HR sees and searches ───────────────────────
    check("MS2-IN-LIST-VIEW", bool(f) and f.in_list_view,
          "it carries in_list_view, so the grid renders a search box for it. "
          "Frappe only builds a filter input for columns in the list view — "
          "without this the field exists and is unreachable")

    # ── MS3 — the Link is OUT of the grid, or they fight for the budget ───
    emp = meta.get_field("employee")
    check("MS3-LINK-OUT-OF-GRID", bool(emp) and not emp.in_list_view,
          "`employee` is no longer a grid column. A Frappe grid allows 11 column "
          "units; keeping both would have cost a column and shown the same name "
          "twice — one searchable, one not, which is worse than either alone")

    # ── MS4 — …but the Link is NOT deleted ────────────────────────────────
    check("MS4-LINK-STILL-EXISTS", bool(emp) and emp.fieldtype == "Link"
          and emp.options == "Employee",
          "`employee` is still a real Link to Employee — the data, the API and "
          "the click-through from the row detail all depend on it. Only its grid "
          "column moved")

    # ── MS5 — every historical row was backfilled ─────────────────────────
    gap = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabIngress Import Row`
         WHERE IFNULL(employee, '') <> '' AND IFNULL(employee_name, '') = ''""")[0][0]
    total = frappe.db.count("Ingress Import Row")
    check("MS5-NO-BLANK-NAMES", gap == 0,
          f"{total - gap} of {total} manifest rows carry a searchable name "
          f"({gap} blank). Manifests written before the field existed had to be "
          f"backfilled — otherwise the fix looks broken on exactly the batches HR "
          f"is most likely to open")

    # ── MS6 — 🔴 the name matches the employee it claims to describe ──────
    wrong = frappe.db.sql("""
        SELECT r.name, r.employee, r.employee_name, e.employee_name
          FROM `tabIngress Import Row` r
          JOIN `tabEmployee` e ON e.name = r.employee
         WHERE IFNULL(r.employee_name, '') <> IFNULL(e.employee_name, '')
         LIMIT 5""", as_dict=True)
    check("MS6-NAME-MATCHES-EMPLOYEE", not wrong,
          f"every stored name equals its employee's own ({wrong or 'no mismatch'}). "
          f"A manifest is a record of what happened, so the name is written at "
          f"import time rather than fetched live — this asserts the two have not "
          f"silently diverged")

    # ── MS7 — the importer populates it on NEW rows ───────────────────────
    # Exercised without touching the machine: `Batch.row()` is the single place
    # every manifest row is created, so calling it directly is the real path.
    # ⚠️ `_Batch.__init__` INSERTS the document — it is not an in-memory builder.
    # Found the hard way: the first version of this suite left INGB-2026-00126
    # sitting in the list at status Running. Hence the try/finally.
    from caf.caf.ingress.sync import _Batch
    emp_row = frappe.get_all("Employee", filters={"status": "Active"},
                             fields=["name", "employee_name"], limit=1)[0]
    b = None
    try:
        b = _Batch("Manual", "Test", "2026-08-01", "2026-08-01", None,
                   "unit-test manifest search")
        b.row("Skipped", emp_row.name, "2026-08-01", None, "999", 0, "unit test")
        made = b.doc.rows[-1]
        check("MS7-IMPORTER-FILLS-IT", made.employee_name == emp_row.employee_name,
              f"a row built by the importer carries {made.employee_name!r} for "
              f"{emp_row.name} — set explicitly from a per-batch lookup, not left "
              f"to fetch_from, so ~600 rows cost one query rather than 600")

        # ── MS8 — a row with no employee is blank, not broken ────────────
        b.row("Skipped", None, "2026-08-01", None, "1234", 0, "no employee")
        blank = b.doc.rows[-1]
        check("MS8-NO-EMPLOYEE-IS-BLANK", (blank.employee_name or "") == "",
              "a row with no employee gets an empty name rather than a lookup "
              "error — the importer does write such rows for locked days, and a "
              "KeyError here would abort a whole import over a cosmetic field")
    finally:
        if b is not None and b.doc.name and frappe.db.exists(
                "Ingress Import Batch", b.doc.name):
            frappe.delete_doc("Ingress Import Batch", b.doc.name,
                              force=True, ignore_permissions=True)
            frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
