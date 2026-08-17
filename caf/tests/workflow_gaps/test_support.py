"""Test-only setup helpers, reachable over REST so the .ps1 suites can use them.

Why this exists: FBR39's window is anchored to the Version row recording
`docstatus 0 → 1`, and there is no way to test the CLOSED side of that window
without an appraisal that looks like it was submitted months ago. Nothing in the
fixture is old enough, and time cannot be moved.

So `age_appraisal_submission` rewrites the `creation` of that one Version row.
That is exactly the input `appraisal_refresh.submitted_on()` reads, so the rest of
the system then behaves as it would in October without anybody waiting until
October.

⚠️ **Administrator only, and it touches nothing but `tabVersion.creation`.** It
cannot alter an appraisal, an attendance record or a leave application. Kept in
`caf/tests/` so it is obvious this is scaffolding and not part of the product.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime


@frappe.whitelist()
def age_appraisal_submission(appraisal: str, months: int = 3):
    """Make a submitted appraisal look `months` old, by aging its submit Version.

    Returns the datetime now recorded, so the caller can assert against it rather
    than trust this worked.
    """
    if frappe.session.user != "Administrator":
        frappe.throw(_("Test scaffolding — Administrator only."))

    months = int(months)
    target = add_to_date(now_datetime(), months=-months)

    rows = frappe.get_all("Version",
                          filters={"ref_doctype": "Appraisal", "docname": appraisal},
                          fields=["name", "creation", "data"],
                          order_by="creation desc", limit_page_length=0)
    for row in rows:
        try:
            data = json.loads(row.data or "{}")
        except ValueError:
            continue
        for change in data.get("changed") or []:
            if change[0] == "docstatus" and int(change[2] or 0) == 1:
                # db_set on `creation` needs raw SQL — Frappe guards the column.
                frappe.db.sql("UPDATE `tabVersion` SET creation = %s WHERE name = %s",
                              (target, row.name))
                frappe.db.commit()
                return {"version": row.name, "submitted_on": str(target),
                        "aged_months": months}

    frappe.throw(_("No submit (docstatus 0→1) Version row found for {0}. Was it "
                   "actually submitted?").format(appraisal))


@frappe.whitelist()
def fbr39_state(appraisal: str):
    """What FBR39 currently thinks — so a test can assert the gate, not guess."""
    if frappe.session.user != "Administrator":
        frappe.throw(_("Test scaffolding — Administrator only."))
    from caf.caf.appraisal_refresh import window_closed
    closed, submitted, deadline = window_closed(appraisal)
    return {"closed": bool(closed), "submitted_on": str(submitted),
            "deadline": str(deadline),
            "docstatus": frappe.db.get_value("Appraisal", appraisal, "docstatus")}
