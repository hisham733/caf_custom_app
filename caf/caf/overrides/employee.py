"""
CAF Appraisal - Employee validation
====================================
Purpose : Enforces that every employee has a supervisor, which is what the
          whole appraisal permission layer rests on - with a per-employee
          exemption for the org roots.
Doctype : Employee (stock)  |  Hook: doc_events -> Employee.validate
Reads   : Employee.reports_to, Employee.caf_reports_to_nobody
Plan ref: CAF_appraisal_implementation_plan.md D15/D51/D53, Appendix D;
          build_brief_chunk2.md 4.3

Why the exemption exists (Appendix D, short version)
----------------------------------------------------
Employee is a NestedSet keyed on reports_to, so the org root MUST have it
empty: self-reference is blocked by stock validate_reports_to(), and pointing
the root downward raises NestedSetRecursionError. D15's original "no fallback,
everyone must have reports_to" was therefore unimplementable. An empty
reports_to already IS "reports to nobody" in Frappe - the only thing forbidding
it was CAF's own rule, so the fix is to scope our rule, not to override the
framework.

CAF has TWO org roots (two Managing Directors, D53), which means two
disconnected trees. That is intended, not a bug.

Changelog
---------
1.0  2026-08-05  Initial - Chunk 2
"""

import frappe
from frappe import _


def ensure_reports_to(doc, method=None):
    """Throw when reports_to is empty unless the org-root checkbox is ticked."""
    if doc.get("reports_to"):
        return

    if doc.get("caf_reports_to_nobody"):
        return

    frappe.throw(
        _(
            "{0} must have a value in <b>Reports To</b>. Every employee is appraised by their "
            "supervisor, and that link is what decides who may appraise whom.<br><br>"
            "If this person genuinely reports to nobody (a company director), tick "
            "<b>Reports To Nobody (Org Root)</b> instead."
        ).format(frappe.bold(doc.get("employee_name") or doc.get("name") or _("This employee"))),
        title=_("Supervisor required"),
    )


def warn_no_attendance_device(doc, method=None):
    """Caution — never a throw — when an active employee has no device id.

    MG, 2026-09-01, after the import-manifest work: *"every emp must have
    erp.attendance_device_id (except the director)."*

    🔴 **What a blank field actually costs.** `active_by_device()` maps Ingress
    `userid` → Employee, and it is the ONLY link between the two systems. An
    employee absent from that map is never matched by any Ingress row, so they
    receive **no Finger Log and no Attendance, ever** — and nothing reports it,
    because there is no row to report. **FBR41.** The correct case (a director who
    does not clock) and a typo look identical: both are simply an empty field.

    So the flag is what separates them. `caf_no_clocking` means *somebody
    decided*; blank-and-unflagged means *nobody has looked*, and that is what this
    says out loud.

    ⚠️ **A message, not a throw, and that is deliberate.** HR creates an employee
    before the person is enrolled on the fingerprint machine — the device id
    genuinely does not exist yet. Refusing the save would make the normal order of
    work impossible, which is the same reasoning as
    `shift_type.warn_on_mixed_population`. The loud version lives where it can be
    acted on in bulk: the readiness audit, and the note on every import batch.
    """
    if doc.get("status") != "Active":
        return
    if (doc.get("attendance_device_id") or "").strip():
        return
    if doc.get("caf_no_clocking"):
        return

    frappe.msgprint(
        _("{0} has no <b>Attendance Device ID</b>, so they will receive no "
          "attendance at all — no Finger Log, no Attendance record, and no line "
          "in any import."
          "<br><br>That is fine if they have not been enrolled on the fingerprint "
          "machine <i>yet</i>. If they genuinely never clock in, tick <b>Does Not "
          "Clock In</b> so this stops being reported as a gap."
          ).format(frappe.bold(doc.get("employee_name") or doc.get("name")
                               or _("This employee"))),
        title=_("No fingerprint device linked"), indicator="orange")
