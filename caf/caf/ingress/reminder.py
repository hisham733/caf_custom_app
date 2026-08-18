# Copyright (c) 2026, CAF and contributors
# For license information, please see license.txt

""""Did anyone import yesterday?" — the safety net FBR44 leaves open.

FBR44 makes importing a human act, and its stated fallback is that employees will
notice the gap in their Finger Log calendar and complain. That is a real feedback
loop but a SLOW one: an employee notices days later, and by then the gap has to be
reconstructed rather than simply filled.

This closes it cheaply. Once a day, ask one question — *is there a completed batch
covering yesterday?* — and if not, tell the people who can fix it.

🔴 It never touches the Ingress machine. That is the entire point of putting the
check on this side: Natalie is a desktop that sleeps, so anything requiring her to
answer would be unreliable exactly when it matters. Nothing here reads the machine,
so the reminder works whether she is awake, asleep or switched off.

FORM — a bell notification, deliberately, not a dialog (MG asked, 2026-08-18):

  · it PERSISTS until read, which is the property that matters for something
    forgotten — a popup dismissed at 09:00 is gone;
  · it does not interrupt. A modal on login fires even when she was already on her
    way to do it, and anything that cries wolf daily gets clicked away by reflex;
  · it is per-user, so it can be narrowed to the people who actually import
    without every HR Manager being nagged.

Recipients default to everyone holding HR Manager, and can be narrowed to named
users in `Ingress Sync Settings` without touching code.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate


def _recipients(settings):
    """Named users if configured, otherwise everyone who could do the import."""
    named = (settings.get("reminder_recipients") or "").strip()
    if named:
        wanted = [u.strip() for u in named.replace("\n", ",").split(",") if u.strip()]
        return [u for u in wanted if frappe.db.exists("User", u)]

    return [r.parent for r in frappe.get_all(
        "Has Role", filters={"role": "HR Manager", "parenttype": "User"},
        fields=["parent"])
        if r.parent != "Administrator"
        and frappe.db.get_value("User", r.parent, "enabled")]


def covered(work_date) -> bool:
    """Is there a COMPLETED batch whose window includes this date?

    Completed, not merely existing: a Failed batch means the import was attempted
    and did not land, which is precisely when the reminder should still fire.
    """
    return bool(frappe.get_all(
        "Ingress Import Batch",
        filters={"status": "Completed",
                 "from_date": ("<=", work_date),
                 "to_date": (">=", work_date)},
        limit=1))


def daily_import_check():
    """Scheduler entry. Silent when yesterday is covered — which is most days."""
    settings = frappe.get_cached_doc("Ingress Sync Settings")
    if not settings.get("reminder_enabled"):
        return

    target = add_days(getdate(nowdate()), -1)
    if covered(target):
        return

    people = _recipients(settings)
    if not people:
        # Worth an error log: a reminder with nobody to remind is a silent
        # failure of exactly the kind this module exists to prevent.
        frappe.log_error(
            "Ingress import reminder has no recipients — nobody holds HR Manager "
            "and no names are configured in Ingress Sync Settings.",
            "Ingress import reminder")
        return

    unmapped = frappe.db.count("Employee", {"status": "Active"})
    subject = _("No attendance imported for {0} yet").format(
        frappe.format(target, {"fieldtype": "Date"}))
    body = _(
        "Nobody has imported attendance for <b>{0}</b>. Until that happens, "
        "{1} employees have no Finger Log for the day, so their appraisal "
        "figures, overtime and leave are all waiting on it."
        "<br><br><b>Two steps:</b><br>"
        "1. In <b>Ingress</b> — Attendance Sheet → <b>Generate</b> for {0}, all "
        "employees. The day is not complete until this is done."
        "<br>2. In <b>ERPNext</b> — Ingress Import Batch → <b>Import from "
        "Ingress</b>, from and to {0}."
    ).format(frappe.format(target, {"fieldtype": "Date"}), unmapped)

    for user in people:
        _notify(user, subject, body)


def _notify(user, subject, body):
    """One unread notification per person per day — never a stack of them.

    A reminder that repeats itself is a reminder people learn to ignore, and the
    scheduler may run this more than once if a queue is retried.
    """
    already = frappe.get_all(
        "Notification Log",
        filters={"for_user": user, "subject": subject, "read": 0},
        limit=1)
    if already:
        return

    doc = frappe.new_doc("Notification Log")
    doc.for_user = user
    doc.type = "Alert"
    doc.subject = subject
    doc.email_content = body
    doc.document_type = "Ingress Import Batch"
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)


@frappe.whitelist()
def preview():
    """What would the reminder do right now? For testing without waiting a day."""
    frappe.only_for("HR Manager")
    settings = frappe.get_cached_doc("Ingress Sync Settings")
    target = add_days(getdate(nowdate()), -1)
    return {
        "enabled": bool(settings.get("reminder_enabled")),
        "checking_work_date": str(target),
        "already_covered": covered(target),
        "would_notify": [] if covered(target) else _recipients(settings),
    }
