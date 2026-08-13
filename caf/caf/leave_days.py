"""E7 / Chunk 6c — count leave days against the ROSTER, not a static list.

Purpose : after stock computes `total_leave_days`, recount the span using CAF's
          own day-type resolution, so a Shift Assignment filed for one of those
          dates is reflected in what the leave costs.
Hook    : doc_events["Leave Application"]["validate"]
Refs    : test plan **E7** · framework §6.14 · OD-72 · R1 · roadmap §9e row 6c

THE DEFECT, PRECISELY
---------------------
Two systems answer *"is this date a working day for X"*, and only one of them can
see a Shift Assignment:

    CAF    resolve_day_type()          Shift Assignment -> default_shift -> list
    STOCK  get_number_of_leave_days()  ->  get_holidays()  ->
           get_holiday_list_for_employee()   <- the employee's STATIC list

Read `get_holidays()` in hrms: it counts rows in ONE Holiday List for the whole
span. A list is a property of the employee, not of the date, so it cannot express
*"this Saturday only, these two people swapped."* Nothing in CAF is broken — the
Finger Log, the Attendance and the roster grid are all correct. Stock's leave
arithmetic simply never asks CAF.

⚠️ **It cuts BOTH ways, which is why "it favours the employee" is no defence.**
The person who gains the working Saturday gets a free leave day; their mirror
partner, who gains the rest Saturday, is overcharged one.

WHY THIS AND NOT AN OVERRIDE OF get_number_of_leave_days() — MG, option C
-------------------------------------------------------------------------
That function is also called by payroll and by allocation, and it is
`@frappe.whitelist()` — the leave form calls it live to preview the count.
Overriding it changes all of those at once. Adjusting the DOCUMENT is narrower:
one field, one doctype, one moment.

✅ **The precondition was measured before this was written, not assumed.**
`LeaveApplication.create_leave_ledger_entry()` builds its entry as
`args = dict(leaves=self.total_leave_days * -1, ...)` — the ledger is DERIVED
from the field. Live check across all **693** submitted applications: **0**
disagree with their ledger. So correcting the document corrects the balance.
(47 rows show a ledger summing to zero; every one is an *amended* 2025 row
carrying a reversing pair, which is document history, not a second source.)

⚠️ ORDERING IS THE WHOLE TRICK, AND IT IS ASSERTED, NOT ASSUMED
`doc_events` handlers for `validate` run **after** the controller's own
`validate()`, so stock sets `total_leave_days` and this overwrites it. If that
ever changed, the fix would silently stop working and every count would revert
to the stock number — which is why **E7-GAIN** and **E7-LOSE** assert the final
value on the document rather than that this function was called.

Changelog
---------
1.0  2026-08-13  Chunk 6c — E7 closed
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import flt, getdate

from caf.caf.shift_resolution import resolve_day_type

WORKDAY = "Workday"


def working_days(employee, from_date, to_date):
    """Days in the span that CAF resolves as a Workday for THIS employee.

    One `resolve_day_type` call per day: it is the only thing that knows about a
    Shift Assignment, and a swap is per-date by definition.
    """
    n, d, end = 0, getdate(from_date), getdate(to_date)
    while d <= end:
        day_type, _shift = resolve_day_type(employee, d)
        if day_type == WORKDAY:
            n += 1
        d += timedelta(days=1)
    return n


def caf_leave_days(employee, leave_type, from_date, to_date,
                   half_day=0, half_day_date=None):
    """What the span SHOULD cost, by the roster. Mirrors stock's half-day rules.

    Returns None when the leave type counts holidays anyway — there is then
    nothing to exclude and stock's own number is already right.
    """
    if frappe.db.get_value("Leave Type", leave_type, "include_holiday"):
        return None

    days = working_days(employee, from_date, to_date)
    if not half_day:
        return flt(days)

    # Same three branches as `get_number_of_leave_days`, applied to the roster
    # count instead of the calendar count.
    if getdate(from_date) == getdate(to_date):
        return flt(0.5) if days else flt(0)
    if half_day_date and getdate(from_date) <= getdate(half_day_date) <= getdate(to_date):
        hd_type, _s = resolve_day_type(employee, half_day_date)
        # A half day on a rest day removes nothing — it was never counted.
        return flt(days - 0.5) if hd_type == WORKDAY else flt(days)
    return flt(days)


def recount_leave_days(doc, method=None):
    """Rewrite `total_leave_days` from the roster. Hooked to `validate`."""
    if not (doc.employee and doc.leave_type and doc.from_date and doc.to_date):
        return
    if getdate(doc.from_date) > getdate(doc.to_date):
        return                          # stock refuses this; do not mask its message

    want = caf_leave_days(doc.employee, doc.leave_type, doc.from_date,
                          doc.to_date, doc.half_day, doc.half_day_date)
    if want is None:
        return

    stock = flt(doc.total_leave_days)
    if abs(want - stock) < 0.001:
        return                          # the usual case: the two already agree

    # 🔴 Stock's own `if self.total_leave_days <= 0: throw` has ALREADY run, on
    # ITS number. If the roster says every day of this span is a rest day, that
    # guard cannot catch it and a zero-day leave would be submitted. Refuse here.
    if want <= 0:
        frappe.throw(
            _("Every day from {0} to {1} is a rest day or holiday for {2}, so "
              "there is no leave to take. Check the shift assignments for those "
              "dates.").format(doc.from_date, doc.to_date, doc.employee),
            title=_("Nothing to deduct"))

    doc.total_leave_days = want


def describe(doc):
    """Why the number differs — for a comment or a test message. No side effects."""
    want = caf_leave_days(doc.employee, doc.leave_type, doc.from_date,
                          doc.to_date, doc.half_day, doc.half_day_date)
    if want is None:
        return f"{doc.leave_type} includes holidays; no adjustment"
    moved = []
    d, end = getdate(doc.from_date), getdate(doc.to_date)
    while d <= end:
        day_type, shift = resolve_day_type(doc.employee, d)
        moved.append(f"{d} {day_type} ({shift})")
        d += timedelta(days=1)
    return f"roster says {want}: " + " · ".join(moved)
