"""Restore pre-session data deleted by the workflow-gaps cleanups on 2026-08-14.

Only restores rows that existed BEFORE this session (creation < 2026-08-14 or
owner not one of the session's fixture users). Session fixtures stay deleted.
No validation runs, no hooks fire, original docstatus is restored via db_set.

    bench --site development.localhost execute caf.tests.workflow_gaps.restore_damage.run
"""

import json

import frappe

MY_USERS = {
    "hr.manager.test@caffood.com",
    "mohd@caffood.com",
    "mursyid@caffood.com",
    "production.c.caf@gmail.com",
    "quality@caffood.com",
}
CUTOFF = "2026-08-14"
DOCTYPES = ["Leave Application", "Attendance", "Finger Log", "OT Approval",
            "Shift Assignment"]


def run():
    rows = frappe.get_all(
        "Deleted Document",
        filters={
            "deleted_doctype": ["in", DOCTYPES],
            "creation": [">=", CUTOFF + " 08:40:00"],
            "restored": 0,
        },
        fields=["name", "deleted_name", "deleted_doctype", "data"],
        order_by="creation",
    )
    print(f"candidate deleted docs: {len(rows)}")
    restored, skipped = [], []

    for r in rows:
        try:
            blob = json.loads(r["data"])
        except Exception:
            skipped.append((r["deleted_name"], "bad-blob"))
            continue
        owner = blob.get("owner", "")
        created = str(blob.get("creation", ""))[:10]
        is_mine = owner in MY_USERS and created >= CUTOFF
        if is_mine:
            skipped.append((r["deleted_name"], "mine"))
            continue
        if frappe.db.exists(r["deleted_doctype"], r["deleted_name"]):
            skipped.append((r["deleted_name"], "exists"))
            continue

        doc = frappe.get_doc(blob)
        original_ds = int(doc.docstatus or 0)
        wf_field = None
        wf = frappe.db.get_value(
            "Workflow", {"document_type": doc.doctype, "is_active": 1},
            "workflow_state_field",
        )
        if wf:
            wf_field = wf
        original_state = doc.get(wf_field) if wf_field else None
        doc.docstatus = 0
        if wf_field and original_state:
            doc.set(wf_field, None)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        doc.flags.ignore_validate = True
        doc.flags.ignore_mandatory = True
        try:
            doc.insert(
                ignore_permissions=True,
                ignore_links=True,
                ignore_mandatory=True,
                ignore_if_duplicate=True,
            )
        except Exception as e:
            frappe.db.rollback()
            skipped.append((r["deleted_name"], f"insert-failed: {str(e)[:80]}"))
            continue

        # children back to their original docstatus (insert normalised them to 0)
        for table in doc.meta.get_table_fields():
            cdt = table.options
            for row in blob.get(table.fieldname) or []:
                if frappe.db.exists(cdt, row.get("name")):
                    frappe.db.set_value(
                        cdt, row["name"], "docstatus",
                        int(row.get("docstatus", original_ds) or 0),
                        update_modified=False,
                    )

        # parent back to its original docstatus + workflow state - no hooks
        set_values = {"docstatus": original_ds}
        if wf_field and original_state:
            set_values[wf_field] = original_state
        frappe.db.set_value(
            doc.doctype, doc.name, set_values,
            update_modified=False,
        )
        frappe.db.set_value(
            "Deleted Document", r["name"],
            {"restored": 1, "new_name": doc.name},
            update_modified=False,
        )
        frappe.db.commit()
        restored.append(f"{r['deleted_doctype']}:{r['deleted_name']} ds={original_ds}")

    print(f"\nRESTORED {len(restored)}:")
    for s in restored:
        print("  ", s)
    print(f"\nSKIPPED {len(skipped)}:")
    for n, why in skipped:
        print(f"   {n} ({why})")
    return {"restored": restored, "skipped": skipped}
