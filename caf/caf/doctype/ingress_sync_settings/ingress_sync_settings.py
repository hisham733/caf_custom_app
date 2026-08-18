# Copyright (c) 2026, CAF and contributors
# For license information, please see license.txt

"""Ingress Sync Settings — where the connection and the policy live.

FBR3 is the reason this is a document and not a set of module constants: *"all OT
policy and calculation lives in ERPNext, never in the Ingress app or the Ingress
DB"*. The same argument applies to the import policy — the window, the submit
target, whether the passes run at all. Staff can be shown an ERPNext record; they
cannot be shown a literal in a .py file.

⚠️ Single-doctype trap (protocol §7 / quirks): `frappe.db.get_value` on a Single
bypasses permlevel. `db_password` is therefore protected by DOCTYPE permission
only, and carries no permlevel — nothing about this document implies a
field-level guarantee it cannot keep.

WHO MAY SEE IT — MG, 2026-08-17: **HR Manager only.** Not HR User, not Employee,
and deliberately not System Manager either: this document holds the machine's
database password, and HR owns the machine relationship. Administrator still
reaches it, because Administrator bypasses every permission check in Frappe — so
there is no lock-out, only a narrower door.

The read-only DIAGNOSTICS (`test_connection`, and `ingress.inspect`) stay open to
System Manager as well. They expose reachability and punch data, never the
password, and somebody technical has to be able to answer "is the machine up?"
without holding an HR role.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class IngressSyncSettings(Document):
    def validate(self):
        if self.source_mode == "Live MySQL" and not (self.host and self.db_name):
            frappe.throw(_("Live MySQL needs at least a host and a database name."))

        if self.source_mode == "Snapshot CSV" and not self.snapshot_path:
            frappe.throw(_("Snapshot CSV needs a path inside the frappe container."))


def get_settings():
    """The settings document, or a defaulted one on a site that never saved it.

    `get_single` returns a document with empty fields rather than throwing, so
    every caller would otherwise have to defend against None.

    Every field here is READ BY CODE. Six that were not — `enabled`,
    `fetch_from_days`, `fetch_to_days`, `submit_target_days`, `auto_submit`,
    `held_flag_after_days`, plus the two run-stamps — were removed on 2026-08-18
    (MG). They were the constants for the scheduled passes, and **FBR44 cancelled
    those passes**: importing is a human act, so there is no window to sweep and no
    pass to auto-submit. A settings page that shows controls doing nothing teaches
    people to disbelieve the ones that work.

    What replaced them, and does something: `reminder_enabled` /
    `reminder_recipients` (the daily nudge) and `last_amendment_check` (the
    watermark for revision checking).
    """
    doc = frappe.get_single("Ingress Sync Settings")
    return frappe._dict(
        source_mode=doc.source_mode or "Live MySQL",
        snapshot_path=doc.snapshot_path or "/tmp/attendance.csv.gz",
        host=doc.host or "",
        port=int(doc.port or 3306),
        db_name=doc.db_name or "ingress",
        db_user=doc.db_user or "",
        db_password=doc.get_password("db_password", raise_exception=False) or "",
        reminder_enabled=bool(doc.reminder_enabled),
        reminder_recipients=doc.reminder_recipients or "",
        last_amendment_check=doc.last_amendment_check,
    )


@frappe.whitelist()
def test_connection():
    """Desk button — prove the machine is reachable before anyone schedules a run.

    Returns a dict rather than throwing on failure: an unreachable machine is a
    normal operational state (§6.5 blocker 7) and the point is to SAY so, not to
    produce a traceback.
    """
    frappe.only_for(("System Manager", "HR Manager"))

    from caf.caf.ingress.source import get_source

    try:
        src = get_source()
        return {"ok": True, "detail": src.describe()}
    except Exception as e:
        return {"ok": False, "detail": frappe.utils.strip_html(str(e))[:300]}
