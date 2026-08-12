"""Shift Assignment hardening — R3 and MG's permission decision.

    bench --site <site> execute caf.scripts.shift_assignment_lockdown.setup

Framework §6.7 (R3 + R5) · §6.9. Two independent defects, both forward-looking:
D-NEW-1 excuses historical data, it does not excuse these.

R3 — `status` MUST NOT BE A HAND-OPERATED CANCEL
------------------------------------------------
Measured: `Shift Assignment.status` is a stock Select (`Active` / `Inactive`),
default `Active`, **`allow_on_submit = 1`**. `get_shift_for_date()` used to filter
on it, so flipping it to `Inactive` removed the row from resolution — but the
hooks are `on_submit` / `before_cancel` / `on_cancel` only, so **Chunk 4's
re-resolve and Chunk 5's appraisal refresh never ran**. The Finger Log kept a
stale `day_type` and the appraisal a stale number, with nothing to show for it.

MG chose to lock the field. This does **not** obstruct stock, which writes the
field through `db_set` in `on_cancel` and through `frappe.db.set_value` in the
daily expiry job — both bypass `allow_on_submit` entirely. It stops a *person*
using it as an unaudited cancel. **Cancel remains the audited path**: docstatus 2,
a Version, and both hooks fire.

PERMISSIONS — MG, 2026-08-12: "restrict write, keep read"
---------------------------------------------------------
Today, stock `DocPerm`: HR Manager full (2 users), HR User read+write+create+
**submit** but no cancel (3 users), Employee **read** (117 users). MG's rule is
that only HR Manager may create, write, submit or cancel — which closes the real
gap, since three HR Users can submit a Shift Assignment today.

⚠️ **`Employee` keeps `read = 1`, deliberately.** `frappe.get_all` returns `[]`
rather than raising, so removing read would make any shift resolution running as
that user fall back **silently** to the default shift instead of failing loudly —
a wrong `day_type` with no error anywhere. The one thing worse than a permission
gap is a permission that fails quietly.

🔴 **Custom DocPerm REPLACES DocPerm for a doctype** (`get_all_perms()` drops
every `DocPerm` row whose parent has custom perms — PROTOCOL §C-bis). So the rows
below are the COMPLETE permission set, not a delta. Omitting a role removes it.
"""

import frappe

DOCTYPE = "Shift Assignment"

# The complete set. Read the module docstring before editing — this REPLACES stock.
PERMS = [
    # role,            read, write, create, submit, cancel, delete, amend, report
    ("HR Manager",        1,     1,      1,      1,      1,      1,     1,      1),
    ("HR User",           1,     0,      0,      0,      0,      0,     0,      1),
    ("Employee",          1,     0,      0,      0,      0,      0,     0,      0),
]


def lock_status_field() -> bool:
    """R3 — `allow_on_submit = 0` on `Shift Assignment.status`."""
    frappe.make_property_setter({
        "doctype": DOCTYPE,
        "fieldname": "status",
        "property": "allow_on_submit",
        "value": 0,
        "property_type": "Check",
    }, is_system_generated=False)
    frappe.clear_cache(doctype=DOCTYPE)
    frappe.db.commit()

    now = frappe.get_meta(DOCTYPE).get_field("status").allow_on_submit
    print(f"  status.allow_on_submit = {now}  {'ok' if not now else '🔴 STILL EDITABLE'}")
    return not now


def restrict_permissions() -> int:
    """MG's rule, as Custom DocPerm — which replaces DocPerm wholesale."""
    for row in frappe.get_all("Custom DocPerm", filters={"parent": DOCTYPE},
                              fields=["name"]):
        frappe.delete_doc("Custom DocPerm", row.name, ignore_permissions=True,
                          force=True)

    made = 0
    for (role, read, write, create, submit, cancel, delete, amend, report) in PERMS:
        doc = frappe.new_doc("Custom DocPerm")
        doc.parent = DOCTYPE
        doc.parenttype = "DocType"
        doc.parentfield = "permissions"
        doc.role = role
        doc.permlevel = 0
        doc.read, doc.write, doc.create = read, write, create
        doc.submit, doc.cancel, doc.delete = submit, cancel, delete
        doc.amend, doc.report = amend, report
        doc.flags.ignore_permissions = True
        doc.insert()
        made += 1

    frappe.clear_cache(doctype=DOCTYPE)
    frappe.db.commit()

    print(f"  Custom DocPerm rows written: {made}")
    for p in frappe.get_all("Custom DocPerm", filters={"parent": DOCTYPE},
                            fields=["role", "read", "write", "create", "submit",
                                    "cancel", "delete"]):
        users = frappe.db.count("Has Role", {"role": p.role, "parenttype": "User"})
        print(f"    {p.role:14s} r={p.read} w={p.write} c={p.create} s={p.submit} "
              f"canc={p.cancel} del={p.delete}   ({users} users)")
    return made


def setup():
    lock_status_field()
    restrict_permissions()
