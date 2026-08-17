# Copyright (c) 2026, CAF and contributors
# For license information, please see license.txt

"""Ingress Import Batch — the record of one run, and the thing that makes a run undoable.

WHY A DOCUMENT PER RUN
----------------------
The Chunk 3 importer printed its summary to a terminal. That is fine for a
one-shot backfill and useless for everything else: you cannot say afterwards
which rows a run produced, so you cannot undo one, and a test import therefore
becomes permanent. Dev carries 2,568 July rows for exactly that reason.

A batch fixes both halves at once — it is the audit record AND the manifest that
`revert_batch` walks.

THE REVERT CONTRACT
-------------------
🔴 A revert may only remove what the batch itself created, and only while it is
still the batch's. Two refusals enforce that, and both are deliberate:

  1. a row whose Finger Log has been modified by somebody other than the import
     user is NOT deleted — somebody is working against it;
  2. a `Production` batch is not reverted at all without an explicit force — the
     undo button exists for test fixtures, not for last week's payroll input.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class IngressImportBatch(Document):
    def on_trash(self):
        # Deleting the batch would orphan every `caf_import_batch` back-pointer
        # on the Finger Logs it created, and those are the provenance trail.
        # Revert first (which clears them), or keep the record.
        live = frappe.get_all("Finger Log",
                              filters={"caf_import_batch": self.name},
                              fields=["name"], limit=1)
        if live:
            frappe.throw(_(
                "Finger Logs still point at batch {0} (e.g. {1}). Revert the batch "
                "first — deleting it would leave those rows claiming a provenance "
                "that no longer exists."
            ).format(frappe.bold(self.name), live[0].name), title=_("Batch in use"))


@frappe.whitelist()
def revert(batch_name: str, force: int = 0):
    """Desk button. Thin wrapper so the form does not need the module path."""
    from caf.caf.ingress.sync import revert_batch

    return revert_batch(batch_name, force=bool(int(force or 0)))


@frappe.whitelist()
def run_manual_import(from_date, to_date, employees=None, submit=0,
                      purpose="Test", allow_recreate=0):
    """Desk dialog entry point. See `caf.caf.ingress.sync.manual_import`."""
    from caf.caf.ingress.sync import manual_import

    if isinstance(employees, str):
        employees = frappe.parse_json(employees) or None

    return manual_import(
        from_date=from_date,
        to_date=to_date,
        employees=employees,
        submit=bool(int(submit or 0)),
        purpose=purpose,
        allow_recreate=bool(int(allow_recreate or 0)),
    )
