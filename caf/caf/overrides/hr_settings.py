"""
CAF Appraisal - HR Settings validation
=======================================
Purpose : Validates the CAF attendance leave codes against live Finger Log
          data, so a typo cannot silently switch the Attendance cell off.
Doctype : HR Settings (stock)  |  Hook: doc_events -> HR Settings.validate
Reads   : Finger Log.leave_taken
Plan ref: CAF_appraisal_implementation_plan.md D69/D70, BR8, 4.3;
          build_brief_chunk2.md 4.6

Why validate against live data rather than a hardcoded constant
----------------------------------------------------------------
The codes are DATA, not logic - HR edits the field, no code change (BR8). But a
free-text field fails silently: "UPl" or "0.5 UPL" simply matches nothing, and
the Attendance cell comes out blank on every appraisal with no error anywhere.
Checking each code against the values actually present in tabFinger Log is
self-maintaining and catches both typos and codes that do not exist.

D70 recorded that HRMS has no existing home for these: Leave Type's 23 fields
are all about entitlement and payroll, and CAF's codes (UPL / 0.5UPL / MC / AL)
exist only as free text in Finger Log.leave_taken.

Changelog
---------
1.0  2026-08-05  Initial - Chunk 2
"""

import frappe
from frappe import _

FIELD = "caf_attendance_leave_codes"


def get_known_leave_codes():
    """Distinct non-empty leave_taken values currently in Finger Log."""
    rows = frappe.db.sql(
        """
        SELECT DISTINCT leave_taken
        FROM `tabFinger Log`
        WHERE leave_taken IS NOT NULL AND leave_taken != ''
        """,
        as_dict=True,
    )
    return {r.leave_taken.strip() for r in rows if r.leave_taken}


def validate_leave_codes(doc, method=None):
    raw = (doc.get(FIELD) or "").strip()
    if not raw:
        # Empty is allowed and means "nothing counts as an attendance issue".
        # get_upl_dates() returns a blank cell in that case rather than guessing.
        return

    codes = [c.strip() for c in raw.split(",") if c.strip()]
    if not codes:
        return

    duplicates = {c for c in codes if codes.count(c) > 1}
    if duplicates:
        frappe.throw(
            _("Duplicate leave code(s) in Attendance Leave Codes: {0}").format(
                ", ".join(sorted(duplicates))
            ),
            title=_("Duplicate codes"),
        )

    known = get_known_leave_codes()
    if not known:
        # No Finger Log data to check against - a fresh site. Do not block setup.
        return

    unknown = [c for c in codes if c not in known]
    if unknown:
        frappe.throw(
            _(
                "These leave codes do not appear anywhere in Finger Log: {0}.<br><br>"
                "Codes currently in use: {1}.<br>"
                "Enter them comma-separated and exactly as they appear in the fingerprint "
                "import, e.g. <b>UPL, 0.5UPL</b>."
            ).format(
                frappe.bold(", ".join(unknown)),
                ", ".join(sorted(known)),
            ),
            title=_("Unknown leave code"),
        )
