"""Holiday List generation — one list per DISTINCT WORKING WEEK, per year.

Chunk 2b, roadmap §6. The authoring counterpart to `shift_resolution.py`.

WHY THIS EXISTS — P-7
---------------------
Chunk 0 hand-built one Holiday List per shift per year: 10 shifts x 2 years = 20
lists. But a Holiday List's content is fully determined by two things, and
neither of them is the shift:

    the public holidays        identical for everyone — FBR12
    the working week           `caf_work_mon` .. `caf_work_sun` — FBR23

CAF has ten shifts and exactly TWO working weeks (Mon-Sat and Mon-Fri), so
eight of those twenty lists were duplicates that had to be kept in step by hand.
This module generates one list per pattern instead, which is what P-7 asked to
be revisited: 20 lists become 4, and January's regeneration becomes one call.

WHAT LANDS IN A LIST
--------------------
    weekly_off = 0   a public holiday          ->  Holiday
    weekly_off = 1   a non-working weekday     ->  Restday
    absent           ->  Workday

A date that is BOTH is written once, as `weekly_off = 1`. The employee is off
because the day was never scheduled; a holiday cannot be "given" on a day
already off. `resolve_day_type()` reaches the same verdict from the other
direction — it checks the working week before the holiday list — so the two
agree by construction.

WHO READS WHICH COPY — FDR6
---------------------------
`Shift Type.holiday_list` is where the list is AUTHORED. `Employee.holiday_list`
is what every stock function actually reads (leave day counting, `is_holiday`),
so the shift's choice is copied down onto the employee. CAF's own day-type
resolution reads neither for rest days — it reads `caf_work_<dow>` — which is
why a Shift Assignment can move one employee's Saturday without touching a list
(OD-52).

USAGE
-----
    bench --site <site> execute caf.caf.holiday_lists.regenerate

Re-runnable: an existing generated list is rebuilt in place, so its name — and
therefore every Employee and Shift Type pointing at it — survives.
"""

import frappe
from frappe.utils import getdate, strip_html
from datetime import date, timedelta

DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Python's weekday(): Monday = 0 .. Sunday = 6. Same order as shift_resolution.
_DOW_FIELD = ("caf_work_mon", "caf_work_tue", "caf_work_wed", "caf_work_thu",
              "caf_work_fri", "caf_work_sat", "caf_work_sun")

PH_LIST = "CAF Public Holidays {year}"
PATTERN_LIST = "CAF {label} {year}"


def working_week(shift_row) -> tuple:
    """The shift's working week as 7 flags, Monday first. FBR23."""
    return tuple(1 if shift_row.get(f) else 0 for f in _DOW_FIELD)


def pattern_label(pattern: tuple) -> str:
    """A readable name for a working week: (1,1,1,1,1,1,0) -> 'Mon-Sat'."""
    days = [i for i, v in enumerate(pattern) if v]
    if not days:
        return "No Working Days"
    if days == list(range(days[0], days[-1] + 1)):
        if len(days) == 1:
            return DOW[days[0]]
        return f"{DOW[days[0]]}-{DOW[days[-1]]}"
    return "+".join(DOW[i] for i in days)


def _dates_in_year(year: int):
    d, end = date(year, 1, 1), date(year, 12, 31)
    while d <= end:
        yield d
        d += timedelta(days=1)


def _public_holidays_in(holiday_list: str, year: int) -> tuple:
    rows = frappe.get_all(
        "Holiday",
        filters={"parent": holiday_list, "weekly_off": 0,
                 "holiday_date": ("between", [date(year, 1, 1), date(year, 12, 31)])},
        fields=["holiday_date", "description"], order_by="holiday_date")
    return tuple((getdate(r.holiday_date), strip_html(r.description or "").strip())
                 for r in rows)


def collect_public_holidays(year: int) -> list:
    """The year's public holidays. FBR12 — one set, applying to everyone.

    Once `CAF Public Holidays <year>` exists it IS the source, which is what
    makes a re-run stable and independent of the Chunk 0 lists this module
    goes on to delete. Before then the set is lifted from those lists — all of
    them, not one, because if two disagree somebody edited a single list and
    generating from either would quietly drop a holiday. Verify, then use.
    """
    canonical = PH_LIST.format(year=year)
    if frappe.db.exists("Holiday List", canonical):
        rows = _public_holidays_in(canonical, year)
        if rows:
            return [{"holiday_date": d, "description": desc} for d, desc in rows]

    candidates = set()
    for shift in frappe.get_all("Shift Type", fields=["name", "holiday_list"]):
        if shift.holiday_list:
            candidates.add(shift.holiday_list)
        # the Chunk 0 naming: one list per shift per year
        if frappe.db.exists("Holiday List", f"{shift.name} {year}"):
            candidates.add(f"{shift.name} {year}")

    sets = {}
    for hl in sorted(candidates):
        rows = _public_holidays_in(hl, year)
        if rows:
            sets.setdefault(rows, []).append(hl)

    if not sets:
        frappe.throw(f"No public holidays found for {year} in any shift Holiday List")

    if len(sets) > 1:
        detail = "; ".join(f"{len(k)} holidays in {v}" for k, v in sets.items())
        frappe.throw(f"Shift Holiday Lists disagree on {year}'s public holidays (FBR12): {detail}")

    return [{"holiday_date": d, "description": desc} for d, desc in list(sets)[0]]


def _write_list(name: str, year: int, rows: list):
    """Create or rebuild a Holiday List in place, so links to it survive."""
    if frappe.db.exists("Holiday List", name):
        doc = frappe.get_doc("Holiday List", name)
        doc.set("holidays", [])
    else:
        doc = frappe.new_doc("Holiday List")
        doc.holiday_list_name = name

    doc.from_date = date(year, 1, 1)
    doc.to_date = date(year, 12, 31)
    for r in sorted(rows, key=lambda r: r["holiday_date"]):
        doc.append("holidays", r)
    doc.flags.ignore_permissions = True
    doc.save()
    return doc.name


def generate_holiday_lists(year: int, repoint: bool = True) -> dict:
    """One Holiday List per distinct working week for `year`.

    Returns {pattern_label: list_name}. With `repoint`, every Shift Type is
    pointed at the list for its own pattern.
    """
    year = int(year)
    public = collect_public_holidays(year)
    ph_dates = {r["holiday_date"] for r in public}

    _write_list(PH_LIST.format(year=year), year, list(public))

    shifts = frappe.get_all("Shift Type", fields=["name"] + list(_DOW_FIELD))
    patterns = {}
    for s in shifts:
        patterns.setdefault(working_week(s), []).append(s.name)

    made = {}
    for pattern, owners in patterns.items():
        label = pattern_label(pattern)
        name = PATTERN_LIST.format(label=label, year=year)

        rows = []
        for d in _dates_in_year(year):
            if not pattern[d.weekday()]:
                # A rest day. It wins over a public holiday landing on it — the
                # employee was never scheduled, so there is nothing to give.
                rows.append({"holiday_date": d, "weekly_off": 1,
                             "description": f"{DOW[d.weekday()]} — rest day"})
            elif d in ph_dates:
                rows.append({"holiday_date": d, "weekly_off": 0,
                             "description": next(r["description"] for r in public
                                                 if r["holiday_date"] == d)})

        _write_list(name, year, rows)
        made[label] = name

        if repoint:
            for shift in owners:
                frappe.db.set_value("Shift Type", shift, "holiday_list", name)

    return made


def sync_employee_holiday_lists(year: int) -> int:
    """Copy the shift's list down onto the employee. FDR6.

    Every stock function — leave day counting, `is_holiday` — reads
    `Employee.holiday_list` and knows nothing about shifts, so the two chains
    diverge unless the list is copied down.
    """
    year = int(year)
    changed = 0
    for emp in frappe.get_all("Employee", filters={"status": "Active"},
                              fields=["name", "default_shift", "holiday_list"]):
        if not emp.default_shift:
            continue
        want = frappe.db.get_value("Shift Type", emp.default_shift, "holiday_list")
        if want and want != emp.holiday_list:
            frappe.db.set_value("Employee", emp.name, "holiday_list", want)
            changed += 1
    return changed


def drop_per_shift_lists(years=(2025, 2026)) -> dict:
    """Delete the Chunk 0 lists — one per shift per year — now superseded.

    Only touches lists named exactly '<Shift Type name> <year>'. Anything else,
    including CAF's pre-existing production lists, is left alone. A list that is
    still linked somewhere is reported, never forced.
    """
    dropped, kept = [], {}
    shifts = [s.name for s in frappe.get_all("Shift Type")]
    for year in years:
        for shift in shifts:
            name = f"{shift} {year}"
            if not frappe.db.exists("Holiday List", name):
                continue
            try:
                frappe.delete_doc("Holiday List", name, ignore_permissions=True)
                dropped.append(name)
            except Exception as e:
                kept[name] = str(e).split("\n")[0][:120]
    return {"dropped": dropped, "still_linked": kept}


def regenerate(years="2025,2026", current_year=2026):
    """The annual entry point. FDR6's whole chain, in order."""
    made = {}
    for year in [int(y) for y in str(years).split(",")]:
        # Only the current year's lists are the ones a Shift Type points at —
        # the field holds one list, and it must be the year in play.
        made[year] = generate_holiday_lists(year, repoint=(year == int(current_year)))

    moved = sync_employee_holiday_lists(current_year)
    removed = drop_per_shift_lists(tuple(int(y) for y in str(years).split(",")))
    frappe.db.commit()

    print("generated:", made)
    print("employees repointed:", moved)
    print("per-shift lists dropped:", len(removed["dropped"]))
    if removed["still_linked"]:
        print("STILL LINKED, not dropped:", removed["still_linked"])
    return {"made": made, "employees_repointed": moved, "dropped": removed}
