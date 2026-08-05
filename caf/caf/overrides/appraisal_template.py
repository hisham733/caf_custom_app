"""
CAF Appraisal - Appraisal Template validation
==============================================
Purpose : Warns when a template omits one of the three KRAs the system fills in
          automatically, because the consequence is silent.
Doctype : Appraisal Template (stock)  |  Hook: doc_events -> validate
Plan ref: CAF_appraisal_implementation_plan.md BR8/BR9/BR10, D28, D68, D83;
          build_brief_chunk3.md 4.1

Why this exists
---------------
refresh_auto_fill() matches grid rows BY KRA NAME (Attendance, Punctuality,
OT Hours) and writes the computed cell into caf_date_cell. A template that does
not include one of those three produces an appraisal with no row to write into -
so that measurement simply disappears for every employee in the departments
using that template, with no error anywhere.

Raised by the user while designing the second department template: "both still
has to evaluate OT hours / punctuality / absent". Correct, and worth enforcing
rather than remembering.

A warning rather than a throw: a template legitimately might not want all three
(a department with no overtime, say), and blocking the save would be heavier
than the risk warrants. The message names exactly what will go missing.

Changelog
---------
1.0  2026-08-05  Initial - Chunk 3
"""

import frappe
from frappe import _

from caf.caf.overrides.appraisal import AUTO_FILLED_KRAS


def warn_on_missing_auto_fill_kras(doc, method=None):
    present = {row.key_result_area for row in (doc.get("goals") or [])}
    missing = [kra for kra in AUTO_FILLED_KRAS if kra not in present]
    if not missing:
        return

    frappe.msgprint(
        _(
            "This template does not include: <b>{0}</b>.<br><br>"
            "Those rows are filled in automatically from Finger Log data. Without them, "
            "appraisals using this template will simply not report {1} - there will be no "
            "row to write the values into, and no error to tell you so."
        ).format(", ".join(missing), ", ".join(m.lower() for m in missing)),
        title=_("Auto-filled KRA missing"),
        indicator="orange",
    )
