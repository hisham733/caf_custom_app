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

import re

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

    🔴 R5 (2026-08-12): `status = "Active"` REMOVED from this filter, and it was a
    live defect, not a tidy-up.

    Stock runs `mark_expired_shift_assignments_as_inactive()` **daily**: every
    submitted assignment whose `end_date` is before yesterday is flipped to
    `Inactive` with a raw `frappe.db.set_value` — no hook, no Version. Measured on
    this site: the job is registered, not stopped, last ran 2026-08-01, and would
    have flipped **73 of 136** rows. It has not bitten only because the scheduler
    is inactive on dev.

    With the filter in place, an expired assignment stopped being visible here, so
    re-resolving a historical date fell back to `default_shift` and returned
    **Workday** where the truth was **Restday** — silently, on any amend, re-import
    or Chunk 4 re-resolve. A punchless day that becomes a Workday is an **Absent**,
    and FBR37 counts it.

    A **cancelled** assignment is still excluded, by `docstatus`. An **expired** one
    is still telling the truth about its own past date, which is the only thing this
    function asks it. Pairs with locking the field (R3) so nothing else can set it.
    """
    work_date = getdate(work_date)

    rows = frappe.get_all(
        "Shift Assignment",
        filters={
            "employee": employee,
            "docstatus": 1,
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


def _year_variant(name: str | None, year: int) -> str | None:
    """`CAF Mon-Sat 2026` asked about a 2025 date -> `CAF Mon-Sat 2025`. OD-66.

    🔴 A Holiday List is PER YEAR and an Employee or Shift Type points at exactly
    one. Before R1 that only cost the odd public holiday; now the list is the
    source of REST days too, so resolving a 2027 date against the 2026 list would
    return no rest days at all — every Sunday and every rest Saturday becoming a
    Workday, and every punchless one an Absent. Silently, because a missing
    Holiday row is indistinguishable from an ordinary working day.

    The generator owns these names (`CAF {label} {year}`), so the year is a
    reliable suffix. If no sibling exists the original is returned unchanged and
    `_list_covers()` then declines to use it.
    """
    if not name:
        return name
    m = re.search(r"(\d{4})\s*$", name)
    if not m or int(m.group(1)) == year:
        return name
    sibling = f"{name[:m.start(1)]}{year}"
    return sibling if frappe.db.exists("Holiday List", sibling) else name


def _list_covers(holiday_list: str | None, work_date) -> bool:
    """Does this list actually span the date? Guards the fallback below."""
    if not holiday_list:
        return False
    span = frappe.db.get_value("Holiday List", holiday_list,
                               ["from_date", "to_date"], as_dict=True)
    if not span or not span.from_date or not span.to_date:
        return False
    return getdate(span.from_date) <= getdate(work_date) <= getdate(span.to_date)


def is_rest_day(holiday_list: str | None, work_date, shift: str | None) -> bool:
    """Is this a rest day? **R1 — the list decides, the flags are the fallback.**

    A `weekly_off = 1` row means the employee was never scheduled. Reading it from
    the list rather than from `caf_work_<dow>` is what makes an ALTERNATING
    Saturday expressible at all: a mirror pair has identical weekday flags and
    differs only in which Saturdays its list marks (OD-67).

    ⚠️ The flags remain the fallback for any date the list does not span — a year
    that was never generated, or a shift with no list. They are also what GENERATES
    the list for a plain weekly pattern, so the two agree by construction and this
    fallback changes no answer it is asked for.
    """
    if _list_covers(holiday_list, work_date):
        return bool(frappe.db.exists("Holiday", {
            "parent": holiday_list,
            "holiday_date": getdate(work_date),
            "weekly_off": 1,
        }))
    return bool(shift) and not works_on(shift, work_date)


def get_holiday_list(employee: str, shift: str | None, work_date=None) -> str | None:
    """The shift's list wins, then the employee's, then the company's.

    The shift comes first because a per-date Shift Assignment is exactly how a swap is
    expressed (OD-52) — reading the employee's own list would ignore the swap.
    """
    year = getdate(work_date).year if work_date else None

    if shift:
        hl = frappe.db.get_value("Shift Type", shift, "holiday_list")
        if hl:
            return _year_variant(hl, year) if year else hl
    hl = frappe.db.get_value("Employee", employee, "holiday_list")
    if hl:
        return _year_variant(hl, year) if year else hl
    company = frappe.db.get_value("Employee", employee, "company")
    hl = frappe.db.get_value("Company", company, "default_holiday_list")
    return _year_variant(hl, year) if (hl and year) else hl


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

    A rest day outranks a public holiday: if the shift does not work Saturdays and a
    public holiday lands on one, the day is reported as Restday, because the employee
    was never scheduled and a holiday cannot be "given" on a day already off. That
    ordering matters for OT rates — Restday and Holiday OT are paid differently, and
    it is preserved here by asking `weekly_off = 1` first. The generator writes such a
    date **once**, as `weekly_off = 1`, so the two agree by construction.

    **R1 (2026-08-12): both verdicts now come from the SAME list**, resolved for the
    work date's own year (OD-66). Rest days used to come from `caf_work_<dow>` while
    only holidays came from the list — two sources that could drift, and that could
    not express an alternating Saturday at all, because a mirror pair has identical
    weekday flags (OD-67).
    """
    work_date = getdate(work_date)
    shift = shift or get_shift_for_date(employee, work_date)
    holiday_list = get_holiday_list(employee, shift, work_date)

    if is_rest_day(holiday_list, work_date, shift):
        return RESTDAY, shift

    if is_public_holiday(holiday_list, work_date):
        return HOLIDAY, shift

    return WORKDAY, shift
