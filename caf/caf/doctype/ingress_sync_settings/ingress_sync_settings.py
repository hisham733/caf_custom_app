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
        # A window that runs backwards silently fetches nothing, and a silent
        # no-op is the failure mode this whole feature exists to avoid.
        if self.fetch_from_days is not None and self.fetch_to_days is not None:
            if int(self.fetch_from_days) < int(self.fetch_to_days):
                frappe.throw(_(
                    "Fetch window runs backwards: D-{0} to D-{1}. The FROM day must be "
                    "the older one — e.g. from D-4 to D-1."
                ).format(self.fetch_from_days, self.fetch_to_days))

        if self.source_mode == "Live MySQL" and not (self.host and self.db_name):
            frappe.throw(_("Live MySQL needs at least a host and a database name."))

        if self.source_mode == "Snapshot CSV" and not self.snapshot_path:
            frappe.throw(_("Snapshot CSV needs a path inside the frappe container."))


def get_settings():
    """The settings document, or a defaulted one on a site that never saved it.

    `get_single` returns a document with empty fields rather than throwing, so
    every caller would otherwise have to defend against None on nine fields.
    """
    doc = frappe.get_single("Ingress Sync Settings")
    return frappe._dict(
        enabled=bool(doc.enabled),
        source_mode=doc.source_mode or "Live MySQL",
        snapshot_path=doc.snapshot_path or "/tmp/attendance.csv.gz",
        host=doc.host or "",
        port=int(doc.port or 3306),
        db_name=doc.db_name or "ingress",
        db_user=doc.db_user or "",
        db_password=doc.get_password("db_password", raise_exception=False) or "",
        fetch_from_days=int(doc.fetch_from_days or 4),
        fetch_to_days=int(doc.fetch_to_days or 1),
        submit_target_days=int(doc.submit_target_days or 3),
        auto_submit=bool(doc.auto_submit),
        held_flag_after_days=int(doc.held_flag_after_days or 0),
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
