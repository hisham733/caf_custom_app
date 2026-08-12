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


# ------------------------------------------------- alternate Saturdays (OD-67)

def _ph_dates_between(lo: date, hi: date) -> set:
    """Every public holiday from `lo` to `hi`, refusing to guess.

    🔴 The alternation is WALKED, not computed from a date, because a public
    holiday is taken by everyone and does not advance it. So a holiday the walk
    cannot see does not merely omit one day — it **inverts every Saturday after
    it** for the rest of the run. Throwing is the only safe answer to a missing
    year: MG asked whether the anchor could be pushed back to 2024, and it cannot,
    because 2024 has no list.
    """
    dates = set()
    for year in range(lo.year, hi.year + 1):
        name = PH_LIST.format(year=year)
        if not frappe.db.exists("Holiday List", name):
            frappe.throw(
                f"Cannot walk the alternate-Saturday sequence: '{name}' does not exist, "
                f"so {year}'s public holidays are unknown. A Saturday holiday the walk "
                f"cannot see inverts every Saturday after it. Generate {year} first.")
        dates.update(d for d, _ in _public_holidays_in(name, year))
    return dates


def alt_saturday_rest_days(year: int, anchor_date, anchor_rests: bool) -> set:
    """The Saturdays of `year` this pattern rests on. OD-67.

    Verified against Ingress (framework §6.9):

        2026-03-14  rest: Afiza, Hazwani, Too Poh Chin
        2026-03-21  PUBLIC HOLIDAY          <- everyone off, sequence does NOT advance
        2026-03-28  rest: Najwa, Nurfarahayu, Seow    <- the exact complement of 03-14

    `anchor_rests` says what this pattern does on `anchor_date`; its mirror does
    the opposite, which is the whole of the mirror relationship.
    """
    year = int(year)
    anchor_date, end = getdate(anchor_date), date(year, 12, 31)

    if anchor_date.weekday() != 5:
        frappe.throw(f"The alternate-Saturday anchor {anchor_date} is not a Saturday")
    if anchor_date > end:
        frappe.throw(f"The anchor {anchor_date} is after {year}; nothing to walk")

    # ⚠️ A MID-YEAR ANCHOR IS ALLOWED, and Saturdays before it are simply not rest
    # days for this pattern. That is not a gap — it is the truth: an alternating
    # shift created in April did not exist in March, and nobody was on it.
    #
    # 🔴 It is also the only safe way to absorb a RETROACTIVE holiday. Measured
    # 2026-08-12: adding the company holiday of 14 February — seven months late —
    # re-phased the walk from that date and agreement with the Ingress record fell
    # from 26/32 to 13/32. The roster never knew about that day at the time, so the
    # real sequence stepped over it. A holiday only makes the alternation wait when
    # it was recorded BEFORE the day arrived. Anchoring after the disputed period
    # is what MG chose, and it is what I3's "regenerate forward only" is protecting.

    ph = _ph_dates_between(anchor_date, end)
    rest, state, d = set(), bool(anchor_rests), anchor_date
    while d <= end:
        if d.weekday() == 5 and d not in ph:
            if state and d.year == year:
                rest.add(d)
            state = not state          # only a Saturday that RAN moves the alternation
        d += timedelta(days=1)
    return rest


def alt_label(rest_saturdays: set) -> str:
    """'1st-3rd' or '2nd-4th', from the first Saturday the pattern rests on.

    ⚠️ NOMINAL, and deliberately so. MG's decision: the numbers name the Saturdays
    the shift **RESTS** on — matching production's own `Alternate First Saturday
    Off` lists, so the two systems cannot invert against each other. But after the
    year's first Saturday public holiday the label stops being literally true,
    which is exactly why `caf_sat_mirror` and `caf_shift_code` are what the code
    reads and the name is documentation only.
    """
    if not rest_saturdays:
        return "Alt Sat"
    first = min(rest_saturdays)
    nth = (first.day - 1) // 7 + 1
    return "Alt Sat 1st-3rd" if nth % 2 else "Alt Sat 2nd-4th"


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

    ph_desc = {r["holiday_date"]: r["description"] for r in public}

    # 🔴 Grouped by working week AND alternation, not by working week alone.
    # A mirror pair has IDENTICAL weekday flags — both Mon-Sat — so keying on the
    # pattern alone would collapse the two into one list and regenerate over the
    # alternation on the next January run. The anchor is what tells them apart.
    #
    # Two shifts from DIFFERENT families (8-5 and 8:30am) that share a working
    # week and an anchor share a list, which is correct: a Holiday List describes
    # days, not times.
    shifts = frappe.get_all(
        "Shift Type",
        fields=["name", "caf_alt_sat", "caf_sat_anchor_date", "caf_sat_anchor"]
        + list(_DOW_FIELD))

    groups = {}
    for s in shifts:
        if s.caf_alt_sat and s.caf_sat_anchor_date and s.caf_sat_anchor:
            key = ("alt", working_week(s), getdate(s.caf_sat_anchor_date),
                   s.caf_sat_anchor == "Rest")
        else:
            key = ("plain", working_week(s))
        groups.setdefault(key, []).append(s.name)

    made = {}
    for key, owners in sorted(groups.items(), key=lambda kv: str(kv[0])):
        pattern = key[1]
        if key[0] == "alt":
            rest_saturdays = alt_saturday_rest_days(year, key[2], key[3])
            label = alt_label(rest_saturdays)
        else:
            rest_saturdays = None
            label = pattern_label(pattern)

        name = PATTERN_LIST.format(label=label, year=year)

        rows = []
        for d in _dates_in_year(year):
            # An alternating shift's SATURDAYS come from the walk, never from
            # `caf_work_sat` — that flag says "this shift works Saturdays at all",
            # which is true of both halves of a mirror pair.
            if rest_saturdays is not None and d.weekday() == 5:
                if d in rest_saturdays:
                    rows.append({"holiday_date": d, "weekly_off": 1,
                                 "description": "Sat — alternate rest day"})
                elif d in ph_dates:
                    rows.append({"holiday_date": d, "weekly_off": 0,
                                 "description": ph_desc[d]})
                continue

            if not pattern[d.weekday()]:
                # A rest day. It wins over a public holiday landing on it — the
                # employee was never scheduled, so there is nothing to give.
                rows.append({"holiday_date": d, "weekly_off": 1,
                             "description": f"{DOW[d.weekday()]} — rest day"})
            elif d in ph_dates:
                rows.append({"holiday_date": d, "weekly_off": 0,
                             "description": ph_desc[d]})

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
