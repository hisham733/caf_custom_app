"""The one-year bar on ANNUAL leave. Option B, as MG chose it.

Purpose : refuse an Annual Leave Application from somebody who has not yet
          completed one year of service, and name the date it becomes usable.
Hook    : doc_events["Leave Application"]["validate"]
Refs    : framework §6.15 · OD-78 (closed) · `caf.caf.leave_allocation`

THE RULE, AND WHY IT IS A GUARD RATHER THAN A ZERO
--------------------------------------------------
CAF's rule, confirmed by MG on 2026-08-13 and again on 2026-09-02:

    an employee may not TAKE annual leave until they have completed one year of
    service, and the bar lifts on their own ANNIVERSARY — not at the start of
    the next cycle.

There were two ways to enforce it, and MG chose the second:

    A  allocate nothing until the anniversary   the balance reads 0, which is
                                                honest to the system and a lie
                                                to the employee — they ARE
                                                accruing
    B  allocate at the start of the cycle and   ⭐ chosen. The employee sees the
       refuse the APPLICATION                   days they have earned, and finds
                                                out when they can use them at
                                                the moment they try

MG accepted the visible-but-unusable balance explicitly. This module is the
second half of that choice; without it, option B is just option "no rule".

🔴 WHY THE STOCK BALANCE CHECK IS NOT ENOUGH
---------------------------------------------
`caf.caf.leave_allocation.start_for()` already opens an ANNUAL allocation on the
later of (anniversary, 1 January), so stock would refuse an early application
for lack of balance. That is a coincidence of the allocation dates, not a rule —
and it evaporates the moment anybody allocates from 1 January instead, which is
exactly what option B asks for. The rule has to be stated somewhere it cannot be
undone by a data-entry choice.

It also produces the wrong message. *"Insufficient leave balance"* tells an
employee they have run out; the truth is that they have days and cannot spend
them yet. A refusal that misdescribes itself is a support call.

WHAT IS NOT TOUCHED
-------------------
MC, unpaid, emergency and every other leave type. §6.15's sentence is about
annual leave alone, and applying the anniversary to medical would postpone every
new joiner's sick leave by a year — against the Employment Act and against what
CAF already does (`leave_allocation` module header, measured on 31 rows).

⚠️ It must stay a `validate` hook, not `before_submit`. The Leave Approver files
the application FOR their report (OD-82), so the refusal has to arrive while the
form is being filled — not after somebody has been told their leave is booked.
"""

import frappe
from frappe import _
from frappe.utils import format_date, getdate

from caf.caf.leave_allocation import ANNUAL, anniversary


def check_service_bar(doc, method=None):
    """`Leave Application.validate`. Refuses ANNUAL before the anniversary."""
    if doc.get("leave_type") != ANNUAL:
        return
    if not doc.get("employee") or not doc.get("from_date"):
        return

    row = frappe.db.get_value(
        "Employee", doc.employee,
        ["employee_name", "date_of_joining"], as_dict=True)
    if not row or not row.date_of_joining:
        # No joining date is a data problem, and readiness_audit already reports
        # it. Refusing here would block leave on the strength of a blank field.
        return

    opens = anniversary(row.date_of_joining)
    start = getdate(doc.from_date)
    if start >= opens:
        return

    end = getdate(doc.to_date or doc.from_date)
    spans = end >= opens

    who = row.employee_name or doc.employee
    joined = format_date(getdate(row.date_of_joining))
    when = format_date(opens)

    if spans:
        # Naming the split is the difference between a refusal and an
        # instruction. The second half of this application is legitimate.
        detail = _(
            "<p>The part of this application from <b>{0}</b> onwards is fine — "
            "re-file it starting on that date, and use another leave type for "
            "the days before it.</p>").format(when)
    else:
        detail = _(
            "<p>Annual leave becomes available on <b>{0}</b>. Until then, medical, "
            "emergency and unpaid leave are unaffected.</p>").format(when)

    frappe.throw(
        _("<p><b>{0}</b> joined on {1} and completes one year of service on "
          "<b>{2}</b>. CAF's rule is that annual leave may not be TAKEN before "
          "then, even though it has already been allocated.</p>{3}").format(
              who, joined, when, detail),
        title=_("Annual leave opens on {0}").format(when))
