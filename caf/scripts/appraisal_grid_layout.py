"""
CAF Appraisal - KRA grid layout
================================
Purpose : Makes the "KRA vs Goal" grid show the CAF text columns and hide the
          stock score columns AS SCHEMA, and takes away the grid's Add Row
          button. Both were previously attempted from appraisal.js on every
          refresh, which is why the columns came and went (D90).
Doctype : Appraisal, Appraisal KRA (Property Setter + Custom Field only)
Plan ref: CAF_appraisal_implementation_plan.md section 1 D90, D93; D2/BR5

Run:
    bench --site <site> execute caf.scripts.appraisal_grid_layout.run

Then re-export so the change reaches git and, through it, production:

    bench --site <site> export-fixtures --app caf

Why this is not a JS concern
----------------------------
`in_list_view` decides which docfields the grid paints as columns. appraisal.js
used to flip it at runtime, inside the `.then()` of a
`frappe.db.get_single_value` call - so the grid had always rendered at least once
before the answer came back, showing Weightage / Goal Completion / Goal Score and
none of the CAF columns. Whether the tester saw the right grid came down to
whether a later re-render happened to land after the promise resolved, which is
why clicking Save appeared to "bring the columns back".

It also mutated the docfield objects handed out by `grid.get_docfield()`. Those
are shared per-meta and outlive the form, so the mutation leaked into every other
Appraisal opened in the same browser session.

Setting it in the schema means the grid is correct on first paint, with no
network round-trip and nothing to race. appraisal.js now only has to act in the
rare case where an HR Manager turns scoring ON.

Idempotent - safe to re-run.

Changelog
---------
1.0  2026-08-06  Initial - fixes the "columns not displayed" report
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

# Stock hrms ships these with in_list_view=1. CAF does not score today (D2/BR5),
# so they are noise that crowds out the columns supervisors actually fill in.
SCORE_COLUMNS = ("per_weightage", "goal_completion", "goal_score")

# The CAF text columns, in the order they should read across the grid, with the
# grid width (out of 10) each one gets. `kra` keeps its stock 2 columns, leaving
# 8 to share.
CAF_COLUMNS = (
    ("caf_date_cell", 1),
    ("caf_description", 3),
    ("caf_root_cause", 2),
    ("caf_corrective_action", 2),
    # Remarks is populated by the auto-fill (e.g. "23 working days") and is
    # readable in the row form; leaving it out of the list view keeps the
    # editable columns wide enough to type in.
    ("caf_remarks", 0),
)


def _set_property(doctype, fieldname, prop, value, prop_type, applied, ok):
    """make_property_setter is idempotent per (doctype, field, property)."""
    existing = frappe.db.get_value(
        "Property Setter",
        {"doc_type": doctype, "field_name": fieldname, "property": prop},
        "value",
    )
    if existing is not None and str(existing) == str(value):
        ok.append(f"{doctype}.{fieldname}.{prop} = {value}")
        return

    make_property_setter(
        doctype,
        fieldname,
        prop,
        value,
        prop_type,
        for_doctype=False,
        validate_fields_for_doctype=False,
    )
    applied.append(f"{doctype}.{fieldname}.{prop} = {value}")


def run():
    applied, ok, missing = [], [], []

    # --- D90: score columns out of the grid list view --------------------
    for fieldname in SCORE_COLUMNS:
        if not frappe.get_meta("Appraisal KRA").get_field(fieldname):
            missing.append(f"Appraisal KRA.{fieldname} does not exist")
            continue
        _set_property("Appraisal KRA", fieldname, "in_list_view", "0", "Check", applied, ok)

    # --- D90: CAF text columns into the grid list view --------------------
    for fieldname, columns in CAF_COLUMNS:
        cf = frappe.db.get_value(
            "Custom Field",
            {"dt": "Appraisal KRA", "fieldname": fieldname},
            ["name", "in_list_view", "columns"],
            as_dict=True,
        )
        if not cf:
            missing.append(f"Custom Field Appraisal KRA.{fieldname} does not exist")
            continue

        want_in_list = 1 if columns else 0
        if cf.in_list_view == want_in_list and (cf.columns or 0) == columns:
            ok.append(f"Appraisal KRA.{fieldname} in_list_view={want_in_list} columns={columns}")
            continue

        doc = frappe.get_doc("Custom Field", cf.name)
        doc.in_list_view = want_in_list
        doc.columns = columns
        doc.save()
        applied.append(f"Appraisal KRA.{fieldname} in_list_view={want_in_list} columns={columns}")

    # --- D93: no Add Row button on the KRA grid ---------------------------
    # The rows come from the Appraisal Template (set_kras_and_rating_criteria).
    # A hand-added row has no KRA behind it and nothing server-side fills its
    # auto-fill cells, so it can only ever be wrong.
    #
    # NOTE: this hides the button and blocks GridRow.add_new_row(), which is the
    # only path the button drives - but like every docfield property it is a UI
    # control, NOT a security control (same caveat as D57). The server-side
    # validate() is what actually decides which rows are legitimate.
    _set_property("Appraisal", "appraisal_kra", "cannot_add_rows", "1", "Check", applied, ok)

    frappe.clear_cache(doctype="Appraisal")
    frappe.clear_cache(doctype="Appraisal KRA")
    frappe.db.commit()

    print("APPLIED:")
    print("\n".join(f"  {line}" for line in applied) or "  (nothing - already correct)")
    print("\nALREADY OK:")
    print("\n".join(f"  {line}" for line in ok) or "  (none)")
    if missing:
        print("\nMISSING - these fields were not found, check the Custom Field fixtures:")
        print("\n".join(f"  {line}" for line in missing))

    print("\nNow run:  bench --site <site> export-fixtures --app caf")
    return {"applied": applied, "ok": ok, "missing": missing}
