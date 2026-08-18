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
def employee_options(txt=None):
    """Employees the importer can actually act on, searched by NAME or by id.

    🔴 Two failed attempts preceded this, both reported by MG:
      · `frappe.db.get_link_options` filters on `name`, which for Employee is the
        id — typing "rohit" searched for an ID containing "rohit" and matched
        nothing. It looked permission-filtered; it was not.
      · `frappe.desk.search.search_link` finds people, but writes its results to
        `frappe.response["results"]` rather than `message`, so the dialog still
        saw an empty list.

    A method of our own ends the guessing, and lets the list say something the
    generic helpers cannot: it returns ONLY employees with an Attendance Device
    ID. Offering somebody with no device id would be offering a choice the
    importer is about to refuse (`manual_import` throws on exactly that), which is
    a worse experience than not offering them.
    """
    frappe.only_for("HR Manager")
    txt = (txt or "").strip()

    conditions = ["e.status = 'Active'", "IFNULL(e.attendance_device_id,'') <> ''"]
    values = {}
    if txt:
        conditions.append("(e.employee_name LIKE %(txt)s OR e.name LIKE %(txt)s "
                          "OR e.attendance_device_id LIKE %(txt)s)")
        values["txt"] = f"%{txt}%"

    rows = frappe.db.sql(f"""
        SELECT e.name, e.employee_name, e.attendance_device_id
          FROM `tabEmployee` e
         WHERE {' AND '.join(conditions)}
      ORDER BY e.employee_name
         LIMIT 50
    """, values, as_dict=True)

    return [{"value": r.name,
             "description": f"{r.employee_name} · device {r.attendance_device_id}"}
            for r in rows]


@frappe.whitelist()
def run_manual_import(from_date, to_date, employees=None, submit=0,
                      purpose="Test", allow_recreate=0):
    """Desk dialog entry point. See `caf.caf.ingress.sync.manual_import`.

    🔴 EVERY ARGUMENT HERE ARRIVES AS A STRING, and one of them arrives EMPTY.

    Found by MG in the desk on 2026-08-18: leaving *Limit to* blank produced
    `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` — so the MAIN
    path, import everyone, was broken while every narrower one worked.

    The dialog does send `null`, correctly. Frappe's form-encoded transport turns
    that into the empty string `""` on the way, and `frappe.parse_json("")` is
    `json.loads("")`, which raises. The guard belongs here rather than in the JS
    because this endpoint is whitelisted — anything may call it.

    Why no test caught it: the suites pass `employees` as a real list, or omit the
    key so the value is `None` and the branch never runs. Neither reproduces the
    DESK's actual payload. `test_desk_payloads` now does exactly that.
    """
    from frappe.utils import cint

    from caf.caf.ingress.sync import manual_import

    employees = _as_employee_list(employees)

    return manual_import(
        from_date=from_date,
        to_date=to_date,
        employees=employees,
        # cint, not int(): a checkbox can arrive as "1", 1, True, "true", "" or
        # None depending on caller, and int("") raises just as loudly as the above.
        submit=bool(cint(submit)),
        purpose=purpose,
        allow_recreate=bool(cint(allow_recreate)),
    )


def _as_employee_list(employees):
    """Whatever the caller sent, return a list of employee ids or None.

    Shapes seen in the wild: a real list (tests), `None` (omitted), `""` (the desk
    with the field left blank), `"[]"`, a JSON array string, and a single bare id
    typed by hand or sent by a script.
    """
    if employees is None:
        return None
    if isinstance(employees, (list, tuple)):
        cleaned = [str(e).strip() for e in employees if str(e).strip()]
        return cleaned or None

    text = str(employees).strip()
    if not text or text in ("null", "[]"):
        return None
    if text.startswith("["):
        parsed = frappe.parse_json(text) or None
        return _as_employee_list(parsed)
    # A single id, unwrapped — accepted so a one-employee call does not have to
    # know it should have been a list.
    return [text]
