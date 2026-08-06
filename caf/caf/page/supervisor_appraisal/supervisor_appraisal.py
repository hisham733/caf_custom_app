"""
CAF Supervisor Bulk Appraisal Page - server-side endpoints
===========================================================
Purpose : Whitelisted endpoints for the supervisor-appraisal Frappe Page.
Doctype : Page (supervisor-appraisal)  |  Route: /app/supervisor-appraisal
Plan ref: supervisor_page_plan.md

Changelog
---------
1.1  2026-08-06  Fix: add explicit doc.check_permission("read") in
                 get_appraisal_doc - frappe.get_doc() inside a whitelisted
                 method bypasses the API-level permission gate.
1.0  2026-08-06  Initial: 4 whitelisted endpoints
"""

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow

from caf.caf.overrides.appraisal import (
    get_direct_reports,
    get_employee_for_user,
    resolve_template,
)


@frappe.whitelist()
def get_direct_reports_appraisals(appraisal_cycle):
    employee = get_employee_for_user()
    if not employee:
        frappe.throw(
            _("Your user account is not linked to any Employee record. "
              "Contact HR to set your User ID on your employee profile."),
            title=_("No employee record"),
        )

    dr_list = get_direct_reports(employee)
    if not dr_list:
        frappe.throw(
            _("No direct reports found for you."),
            title=_("No direct reports"),
        )

    doc_list = []
    templates_seen = {}

    for dr in dr_list:
        existing = frappe.db.exists(
            "Appraisal", {"employee": dr, "appraisal_cycle": appraisal_cycle}
        )

        if existing:
            name = existing
            ws = frappe.db.get_value("Appraisal", name, "workflow_state") or "Draft"
        else:
            template = resolve_template(dr)
            if not template:
                continue
            doc = frappe.get_doc({
                "doctype": "Appraisal",
                "employee": dr,
                "appraisal_cycle": appraisal_cycle,
                "appraisal_template": template,
            })
            doc.insert()
            doc.reload()
            name = doc.name
            ws = "Draft"

        emp_name = frappe.db.get_value("Employee", dr, "employee_name") or dr
        department = frappe.db.get_value("Employee", dr, "department") or ""
        template = frappe.db.get_value("Appraisal", name, "appraisal_template") or ""

        entry = {
            "name": name,
            "employee": dr,
            "employee_name": emp_name,
            "department": department,
            "workflow_state": ws,
            "appraisal_template": template,
        }
        doc_list.append(entry)

        if template and template not in templates_seen:
            templates_seen[template] = True

    doc_list.sort(key=lambda d: (
        d.get("appraisal_template") or "",
        d.get("employee_name") or "",
    ))

    return {
        "templates": [t for t in templates_seen],
        "doc_list": doc_list,
        "total": len(doc_list),
    }


@frappe.whitelist()
def get_appraisal_doc(appraisal_name):
    doc = frappe.get_doc("Appraisal", appraisal_name)

    # Explicit permission check - frappe.get_doc() inside a whitelisted
    # method does NOT trigger the API-level permission gate. Raw Frappe
    # API correctly blocked Liton (403), but our endpoint returned 200.
    # Verified: test 14e failed before this line was added.
    doc.check_permission("read")

    kra_rows = []
    for row in doc.get("appraisal_kra") or []:
        kra_rows.append({
            "name": row.name,
            "kra": row.kra or "",
            "caf_date_cell": row.caf_date_cell or "",
            "caf_description": row.caf_description or "",
            "caf_root_cause": row.caf_root_cause or "",
            "caf_corrective_action": row.caf_corrective_action or "",
            "caf_remarks": row.caf_remarks or "",
        })

    return {
        "header": {
            "name": doc.name,
            "employee": doc.employee or "",
            "employee_name": doc.employee_name or "",
            "department": doc.department or "",
            "workflow_state": doc.workflow_state or "Draft",
            "appraisal_template": doc.appraisal_template or "",
            "appraisal_cycle": doc.appraisal_cycle or "",
        },
        "kra_rows": kra_rows,
        "is_editable": (doc.workflow_state or "Draft") == "Draft",
    }


@frappe.whitelist()
def save_appraisal_kra(appraisal_name, kra_rows):
    if isinstance(kra_rows, str):
        import json
        kra_rows = json.loads(kra_rows)

    doc = frappe.get_doc("Appraisal", appraisal_name)
    state = doc.workflow_state or "Draft"

    if state != "Draft":
        frappe.throw(
            _("This appraisal is in the {0} state and cannot be edited.")
            .format(state),
            title=_("Locked for review"),
        )

    row_map = {r.name: r for r in doc.appraisal_kra}

    for incoming in kra_rows:
        existing = row_map.get(incoming.get("name"))
        if not existing:
            continue
        for field in ("caf_date_cell", "caf_description", "caf_root_cause",
                      "caf_corrective_action", "caf_remarks"):
            val = incoming.get(field)
            if val is not None and val != getattr(existing, field, ""):
                existing.set(field, val)

    doc.save()

    return {
        "success": True,
        "workflow_state": doc.workflow_state or "Draft",
    }


@frappe.whitelist()
def submit_for_review(appraisal_name):
    doc = frappe.get_doc("Appraisal", appraisal_name)
    state = doc.workflow_state or "Draft"

    if state != "Draft":
        frappe.throw(
            _("This appraisal is already in the {0} state.")
            .format(state),
            title=_("Already submitted"),
        )

    apply_workflow(doc, "Submit for Review")

    return {
        "success": True,
        "workflow_state": doc.workflow_state or "Pending HR Review",
        "message": _("Appraisal submitted for HR review."),
    }
