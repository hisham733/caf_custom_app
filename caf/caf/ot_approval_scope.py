"""An OT Approval must reach the days it covers. T-48.

Hooks : doc_events["OT Approval"]["on_submit"] and ["on_cancel"]
Refs  : T-48 · T-46 · FBR71 (special supersedes normal) · FBR11 · OD-62

🔴 WHY THIS EXISTS — MG's own side quest, 2026-09-13
-----------------------------------------------------
*"check if this workflow is feasible: FL submitted with an OT_approval, then weeks
later HR submits OT_approval (type = special) with more OT / less OT."*

**It was feasible and it broke.** Measured both directions:

    submit   a log with 2.5 h OT under a NORMAL approval for 3.0   -> final_ot 2.5
    later    HR files a SPECIAL approval for 1.0 h                 -> accepted,
             and FBR71 correctly cancels the earlier normal ROW
    result   the SUBMITTED log still read final_ot = 2.5, still pointing at the
             row that had just been cancelled, caf_hr_review = 0, note empty
    and      a re-resolve WOULD have decided 1.0

**1.5 hours would have been paid that nobody approved, silently.**

⭐ THE ROOT CAUSE WAS ONE MISSING WIRE, NOT A BROKEN RULE
---------------------------------------------------------
`Leave Application`, `Shift Assignment` and `Finger Log` each reach back into the
days they affect. **`OT Approval` had no `doc_events` entry at all** — an approval
could be filed, superseded or withdrawn and no day ever heard about it. Every
individual part was behaving as designed; nothing connected them.

🔴 IT FLAGS. IT DOES NOT REWRITE.
----------------------------------
**`final_ot` is what somebody is paid**, and rewriting it from a hook would be the
same silence in the other direction — a number changing behind a submitted
document with nobody told. So this puts the day **in front of a person**, on the
report HR already reads (`Attendance Follow-Up` shows `caf_hr_review`), with the
old figure, the new figure and the approval named.

⚠️ It never throws. A flag that cannot be written must not stop HR approving
overtime — the approval is the business act, the flag is bookkeeping.

⚠️ `caf_hr_review` / `caf_hr_review_note` are written with `db_set`, which leaves
no Version (OD-26), so a **comment** carries the trail. They are also the two
`allow_on_submit` fields OD-62 deliberately leaves unguarded, precisely so a human
can clear a flag they have dealt with.

⭐ THE SAME COMPARISON CLOSES T-46
-----------------------------------
T-46 is a backdated Shift Assignment silently taking `final_ot` to 0. That path
already re-resolves the log, so `_ot_coverage` runs — but it only ever asks
*"is the clocked overtime COVERED?"*, and zero always is. `divergence()` below
asks the other question, *"does the stored figure still match what the approvals
say?"*, and `re_resolve` calls it too.
"""

import frappe
from frappe import _


def divergence(log_name):
    """(stored, computed, approval, note) — or None when they still agree.

    ⭐ THE QUESTION NOBODY WAS ASKING. `_ot_coverage()` asks whether the CLOCKED
    overtime is covered by an approval, and 0 is always covered — so it is blind
    in the one direction that costs money. This asks whether the figure the
    document is carrying still matches what the approvals now say, which catches
    both directions with one comparison.
    """
    from caf.caf.re_resolve import _ot_coverage

    doc = frappe.get_doc("Finger Log", log_name)
    if doc.docstatus != 1:
        return None                       # a draft re-derives itself on save

    stored = float(doc.final_ot or 0)
    computed, approval, _overwrite, _problem = _ot_coverage(doc)
    computed = float(computed or 0)
    if abs(stored - computed) < 0.001:
        return None

    direction = _("MORE") if stored > computed else _("LESS")
    note = _(
        "Overtime no longer matches its approval: this log carries <b>{0} h</b> "
        "and the approvals now in force come to <b>{1} h</b> — {2} than is "
        "approved. {3} Check the day and amend the log, or correct the approval."
    ).format(stored, computed, direction,
             _("The covering approval is now {0}.").format(frappe.bold(approval))
             if approval else _("No submitted approval covers it any more."))
    return stored, computed, approval, note


def flag(log_name, why=""):
    """Mark one submitted log for HR. Returns True when it wrote a flag."""
    d = divergence(log_name)
    if not d:
        return False
    _stored, _computed, _approval, note = d

    doc = frappe.get_doc("Finger Log", log_name)
    doc.db_set("caf_hr_review", 1, update_modified=False)
    doc.db_set("caf_hr_review_note", note, update_modified=False)
    # db_set writes no Version (OD-26), so the comment IS the trail on a field
    # that feeds somebody's overtime pay.
    doc.add_comment("Comment", _("Flagged for review: {0}{1}").format(
        frappe.utils.strip_html(note), f" ({why})" if why else ""))
    return True


def _days(doc):
    """The (employee, date) pairs this approval speaks for.

    ⚠️ The CHILD row's date, not the header's. Measured 2026-09-01: **77 submitted
    child rows carry a work_date that differs from their parent's**, and genuine
    multi-date approvals exist — the header date is the day the approval was
    RAISED, the row's date is the day being approved.
    """
    seen = set()
    for row in (doc.get("emp_list") or []):
        if row.emp_id and row.work_date:
            seen.add((row.emp_id, str(row.work_date)))
    return sorted(seen)


def refresh_affected_logs(doc, method=None):
    """`OT Approval` on_submit / on_cancel — T-48. Flags, never rewrites, never throws."""
    if frappe.flags.get("in_import") or frappe.flags.get("in_patch"):
        return
    try:
        flagged = []
        for employee, day in _days(doc):
            for row in frappe.get_all(
                    "Finger Log",
                    filters={"employee": employee, "work_date": day,
                             "docstatus": 1},
                    fields=["name"]):
                if flag(row.name, why=_("OT Approval {0} was {1}").format(
                        doc.name, _("cancelled") if method == "on_cancel"
                        else _("submitted"))):
                    flagged.append(row.name)

        if flagged:
            frappe.msgprint(
                _("<p><b>{0} submitted Finger Log(s)</b> on the day(s) this "
                  "approval covers no longer agree with it, and have been "
                  "flagged for review: {1}.</p><p>They are on <b>Attendance "
                  "Follow-Up</b>. ⚠️ Their overtime figures were <b>not</b> "
                  "changed — a number somebody is paid is not altered behind a "
                  "submitted document.</p>").format(
                      len(flagged), ", ".join(flagged)),
                title=_("Overtime needs checking"), indicator="orange")
    except Exception:
        # The approval is the business act; the flag is bookkeeping. A failure
        # here must never stop HR approving somebody's overtime.
        frappe.log_error(title="T-48: flagging affected Finger Logs failed",
                         message=frappe.get_traceback())
