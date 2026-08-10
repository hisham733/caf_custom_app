"""Shift and day-type resolution — the single source of truth for "what kind of day was this".

Used by Finger Log (Chunk 2) and, from Chunk 3, by Attendance. Nothing else may
decide a day type.

DESIGN — see CAF_DESIGN_FRAMEWORK.md §6.4 and CAF_BUILD_SPEC.md §8.

  OD-45   The shift for a date comes from ERPNext ONLY: a submitted Shift Assignment
          covering that date, else Employee.default_shift. Ingress plays no part and
          `sche1` is not imported.

  OD-52   A Saturday swap files TWO Shift Assignments — one per employee. Mr A points
          at a shift that works Saturday; Mr B points at one that does not. That is why
          day_type MUST be resolved from the shift that applies on the date, never from
          the employee's own default.

  FBR23   The working week is a property of the SHIFT. Stock Shift Type has no such
          field, so CAF adds `caf_work_mon` .. `caf_work_sun`.

  FBR12   Public holidays apply to everyone, so they live in the Holiday List.

The two sources are deliberately split:

    caf_work_<dow> = 0        ->  Restday     per shift, changes with a Shift Assignment
    date in Holiday List      ->  Holiday     per company, same for everyone
    neither                   ->  Workday

⚠️ The Holiday List ALSO carries the rest days, generated from the same flags by
`generate_holiday_lists()`. That copy exists for STOCK's benefit — leave day counting
(`get_number_of_leave_days`) reads the Holiday List and knows nothing about shifts.
CAF's own resolution never reads it for rest days, so the two cannot drift in a way
that changes a day type.
"""

import frappe
from frappe.utils import getdate

WORKDAY = "Workday"
RESTDAY = "Restday"
HOLIDAY = "Holiday"

# Python's weekday(): Monday = 0 .. Sunday = 6
_DOW_FIELD = ("caf_work_mon", "caf_work_tue", "caf_work_wed", "caf_work_thu",
              "caf_work_fri", "caf_work_sat", "caf_work_sun")


def get_shift_for_date(employee: str, work_date) -> str | None:
    """The shift that applies to this employee on this date. OD-45, option A.

    A submitted Shift Assignment covering the date wins; otherwise the employee's
    default shift. Returns None if neither exists — the caller must decide what that
    means rather than having a silent fallback invented here.
    """
    work_date = getdate(work_date)

    rows = frappe.get_all(
        "Shift Assignment",
        filters={
            "employee": employee,
            "docstatus": 1,
            "status": "Active",
            "start_date": ("<=", work_date),
        },
        or_filters=[
            ["end_date", ">=", work_date],
            ["end_date", "is", "not set"],
        ],
        fields=["name", "shift_type", "start_date"],
        order_by="start_date desc, creation desc",
        limit=1,
    )
    if rows:
        return rows[0].shift_type

    return frappe.db.get_value("Employee", employee, "default_shift") or None


def get_shift_params(shift: str) -> frappe._dict:
    """The CAF rules hanging off a Shift Type. CAF_BUILD_SPEC.md §8."""
    p = frappe.db.get_value(
        "Shift Type", shift,
        ["name", "start_time", "end_time", "holiday_list",
         "caf_allow_ot", "caf_ot_gate_minutes", "caf_ot_round_minutes",
         "caf_lunch_minutes"] + list(_DOW_FIELD),
        as_dict=True,
    )
    return p or frappe._dict()


def works_on(shift: str, work_date) -> bool:
    """Does this shift's working week include that weekday? FBR23."""
    field = _DOW_FIELD[getdate(work_date).weekday()]
    return bool(frappe.db.get_value("Shift Type", shift, field))


def get_holiday_list(employee: str, shift: str | None) -> str | None:
    """The shift's list wins, then the employee's, then the company's.

    The shift comes first because a per-date Shift Assignment is exactly how a swap is
    expressed (OD-52) — reading the employee's own list would ignore the swap.
    """
    if shift:
        hl = frappe.db.get_value("Shift Type", shift, "holiday_list")
        if hl:
            return hl
    hl = frappe.db.get_value("Employee", employee, "holiday_list")
    if hl:
        return hl
    company = frappe.db.get_value("Employee", employee, "company")
    return frappe.db.get_value("Company", company, "default_holiday_list")


def is_public_holiday(holiday_list: str | None, work_date) -> bool:
    """A dated, non-weekly-off row in the Holiday List. FBR12 — applies to everyone."""
    if not holiday_list:
        return False
    return bool(frappe.db.exists("Holiday", {
        "parent": holiday_list,
        "holiday_date": getdate(work_date),
        "weekly_off": 0,
    }))


def resolve_day_type(employee: str, work_date, shift: str | None = None) -> tuple:
    """Return (day_type, shift).

    A public holiday outranks a rest day: if the shift does not work Saturdays and a
    public holiday lands on one, the day is reported as Restday, because the employee
    was never scheduled and a holiday cannot be "given" on a day already off. That
    ordering matters for OT rates — Restday and Holiday OT are paid differently.
    """
    work_date = getdate(work_date)
    shift = shift or get_shift_for_date(employee, work_date)

    if shift and not works_on(shift, work_date):
        return RESTDAY, shift

    if is_public_holiday(get_holiday_list(employee, shift), work_date):
        return HOLIDAY, shift

    return WORKDAY, shift
