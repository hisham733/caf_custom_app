"""Leave over a day he actually worked — say it in CAF's words. T-45 finding F5.

Hook : doc_events["Leave Application"]["before_validate"]
Refs : FDR4 · FBR69 · D-12 · T-45 (the L2 climb)

🔴 WHY THIS EXISTS
-------------------
Somebody clocks in on Monday morning and goes home sick at eleven. The day is
already recorded as **Present**. HR then files the MC and stock refuses with:

    Attendance for employee HR-EMP-00045 is already marked for the following
    dates: 08-06-2026

That is the whole message. It names the date and the row and **says nothing about
what to do** — and the obvious move, cancelling the attendance, is itself refused
by D-12 while the leave stands. HR is left in a loop with no exit.

⚠️ **It is not rare.** Anybody who starts a day and leaves sick lands here, and it
is exactly the day an MC is most likely to arrive for.

⭐ WHY A `before_validate` HOOK AND NOT `validate`
--------------------------------------------------
Stock's own `validate_attendance()` (hrms `leave_application.py:599`) runs inside
the controller's `validate`, and **`doc_events` run AFTER the controller's method
of the same name** — so a `validate` hook would always speak second, after the
unhelpful message had already thrown. `before_validate` runs first, which is the
only place this can get in front.

🔴 IT REFUSES THE SAME DAYS STOCK WOULD. This is a better message, not a new
permission — the filter below is copied from stock deliberately, including
`half_day_status != 'Absent'`. If the two ever disagree, HR would meet one
message in some cases and the other in the rest, which is worse than either.
"""

import frappe
from frappe import _


def _worked_days(doc):
    """Days in this application that already carry a PRESENT attendance.

    The filter mirrors hrms `validate_attendance()` exactly — same statuses, same
    docstatus, same half-day clause.
    """
    if not (doc.get("employee") and doc.get("from_date") and doc.get("to_date")):
        return []
    return frappe.get_all(
        "Attendance",
        filters={"employee": doc.employee,
                 "attendance_date": ("between", [doc.from_date, doc.to_date]),
                 "status": ("in", ["Present", "Work From Home"]),
                 "docstatus": 1,
                 "half_day_status": ("!=", "Absent")},
        fields=["name", "attendance_date", "caf_finger_log"],
        order_by="attendance_date")


def explain_worked_day(doc, method=None):
    """`Leave Application.before_validate` — refuse first, and say what to do."""
    if doc.get("docstatus") == 2 or doc.get("status") == "Rejected":
        return                                   # cancelling never asks for more
    rows = _worked_days(doc)
    if not rows:
        return

    who = frappe.db.get_value("Employee", doc.employee, "employee_name") \
        or doc.employee
    items = "".join(
        _("<li><b>{0}</b> — recorded as present{1}</li>").format(
            frappe.utils.formatdate(r.attendance_date),
            _(" from Finger Log {0}").format(
                f'<a href="/app/finger-log/{r.caf_finger_log}">{r.caf_finger_log}</a>')
            if r.caf_finger_log else "")
        for r in rows)

    frappe.throw(
        _("<p><a href='/app/employee/{0}'>{1}</a> is already recorded as having "
          "<b>worked</b> on:</p><ul>{2}</ul>"
          "<p>A day the clock says he worked cannot also be leave, so this "
          "application is refused for those dates.</p>"
          "<p><b>What to do</b> — it depends which is true:</p><ul>"
          "<li>he <b>did not</b> work: correct the punches <b>in Ingress</b> and "
          "re-import the day, then file this leave again;</li>"
          "<li>he worked <b>part</b> of the day: file the leave as a <b>half "
          "day</b> for the dates he was in;</li>"
          "<li>the leave is for <b>other</b> dates too: file those separately — "
          "only the days above are refused.</li></ul>"
          "<p>⚠️ Cancelling the attendance record instead will not work while the "
          "day belongs to a submitted Finger Log.</p>"
          ).format(doc.employee, frappe.utils.escape_html(who), items),
        title=_("He is recorded as present that day"))
