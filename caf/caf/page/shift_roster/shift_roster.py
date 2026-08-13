"""Chunk 7.5 — the Shift & Saturday roster.  OD-72.

MG asked for two things in one sentence: *"identify which SAssign.doc is which
case"* and *"which emp is assigned to which shift_type"*. After R1 those are no
longer the same table.

    BEFORE R1                          AFTER R1  (today)
    136 Shift Assignments              0 Shift Assignments
      86 wrong default_shift             the roster lives in the SHIFT, and
      46 routine rest Saturdays          resolve_day_type() is the only thing
       4 genuine exceptions              that knows it

So a screen built on Shift Assignment alone is a screen of *exceptions* — right,
useful, and blank most weeks. The roster is a different query, and it is the one
that is always populated.

🔴 **Why the grid is the centre.** The failure this project has actually seen is
a whole COLUMN, not a row: on 2026-02-14 all eight alternate-Saturday employees
were rostered to work and not one of them clocked in, because HR had not recorded
a company holiday. **There was no document to list.** A list of assignments shows
what HR remembered to file; the grid shows what the system believes.

⚠️ Everything here is `frappe.only_for`. The Page's role list decides who may
*open* the route; it does not decide what a whitelisted method returns to a
caller who reaches it directly (PROTOCOL §C4). The methods are the enforcement.
"""

import calendar

import frappe
from frappe import _
from frappe.utils import add_days, get_first_day, get_last_day, getdate, nowdate

from caf.caf.shift_resolution import RESTDAY, get_shift_for_date, resolve_day_type
from caf.caf.shift_swap import half_done_swaps

# ⚠️ READ and MANAGE are different populations, and the split is deliberate
# (MG, 2026-08-12: *"HR user can see only"*).
#
#   READ    HR Manager · HR User · System Manager   — the whole screen
#   MANAGE  HR Manager · System Manager             — filing a trade
#
# HR User already holds `read` on Shift Assignment through the Custom DocPerm, so
# withholding the roster from them told them nothing the list view would not.
# Filing stays HR Manager's: `shift_swap.create/plan/cancel_both` carry their own
# `frappe.only_for`, and the button is hidden from HR User for tidiness only —
# hiding a button is not a lock (PROTOCOL §C4).
ROLES = ["HR Manager", "HR User", "System Manager"]

# ── OD-71's detector ────────────────────────────────────────────────────────
# A working day on which an implausible share of the workforce has no punch AT
# ALL. HR asked for a weekly prompt ("are there new holidays?"); a prompt asks
# them to remember something they have already forgotten once. This finds it.
#
# Calibrated against the real case: on 2026-02-14 the share was 8/8 = 100%, and
# in three months of punch data that shape occurs nowhere else except the
# confirmed public holiday of 21 March. 0.9 leaves room for one straggler.
#
# ⚠️ MIN_LOGS exists because a small day means nothing — three people off is a
# Tuesday, not a holiday.
DETECTOR_SHARE = 0.9
DETECTOR_MIN_LOGS = 6

# The importer writes 00:00:00 for "did not punch", never NULL (PROTOCOL §F2 —
# this project has been caught by that exact sentinel twice).
NO_PUNCH = ("00:00:00", "0:00:00")


def _month_bounds(month=None):
    """`month` is 'YYYY-MM'. Defaults to the month containing today."""
    anchor = getdate(f"{month}-01") if month else getdate(nowdate())
    return get_first_day(anchor), get_last_day(anchor)


def _saturdays(first, last):
    out, d = [], first
    while d <= last:
        if d.weekday() == calendar.SATURDAY:
            out.append(d)
        d = add_days(d, 1)
    return out


def alt_shifts():
    """The mirror pairs. Read from `caf_alt_sat`, never from the shift name —
    the names carry 1st-3rd / 2nd-4th as documentation and go stale after the
    year's first public holiday (§6.9, I1)."""
    return frappe.get_all(
        "Shift Type",
        filters={"caf_alt_sat": 1},
        fields=["name", "caf_shift_code", "caf_sat_mirror", "caf_sat_anchor",
                "caf_sat_anchor_date", "holiday_list"],
        order_by="name",
    )


def _assignments_between(first, last):
    """Submitted assignments overlapping the window, indexed by (employee, date).

    Overlap, not containment — an assignment that started last month and ends in
    this one still owns these days. The same trap 7.4's C74-OVERLAP caught.
    """
    rows = frappe.get_all(
        "Shift Assignment",
        filters={"docstatus": 1, "start_date": ["<=", last], "end_date": [">=", first]},
        fields=["name", "employee", "shift_type", "start_date", "end_date",
                "caf_swap_kind", "caf_swap_with", "caf_swap_partner", "status"],
    )
    by_day = {}
    for r in rows:
        d = getdate(r.start_date)
        while d <= getdate(r.end_date):
            by_day[(r.employee, str(d))] = r
            d = add_days(d, 1)
    return rows, by_day


def roster_population(first, last, alt_names, by_day):
    """MG's rule, Q2: *whoever is on a shift where `caf_alt_sat = 1`* — not a
    hardcoded list of eight names.

    Two ways to be on one, and both count:
      · `Employee.default_shift` is an alt shift            (the standing case)
      · a Shift Assignment in this window points at one     (a cover moves
        somebody onto a mirror they do not normally hold)

    A hardcoded list would have rotted the first time HR moved anyone.
    """
    emps = frappe.get_all(
        "Employee",
        filters={"default_shift": ["in", alt_names], "status": "Active"},
        fields=["name", "employee_name", "default_shift", "department"],
    )
    seen = {e.name for e in emps}

    for (employee, _d), row in by_day.items():
        if row.shift_type in alt_names and employee not in seen:
            extra = frappe.db.get_value(
                "Employee", employee,
                ["name", "employee_name", "default_shift", "department"], as_dict=True)
            if extra and extra.name not in seen:
                emps.append(extra)
                seen.add(extra.name)

    emps.sort(key=lambda e: (e.default_shift or "", e.employee_name or ""))
    return emps


def grid(first, last, alt_names, by_day, employees, saturdays):
    """One cell per employee per Saturday, straight from `resolve_day_type()`.

    ⚠️ Deliberately NOT read from `Finger Log.day_type`. A stored day_type is
    what the resolver said the last time something touched that row, and the two
    can differ — measured 2026-08-12, three of July's 32 alt-Saturday cells
    disagreed. The grid must show what the system believes *now*, because that
    is what the next re-resolve, re-import or amend will write.
    """
    rows = []
    for e in employees:
        cells = []
        for d in saturdays:
            day_type, shift = resolve_day_type(e.name, d)
            assignment = by_day.get((e.name, str(d)))
            cells.append({
                "date": str(d),
                "day_type": day_type,
                "shift": shift,
                "overridden": bool(assignment),
                "assignment": assignment.name if assignment else None,
                "kind": (assignment.caf_swap_kind or "Single") if assignment else None,
                "traded_with": assignment.caf_swap_with if assignment else None,
            })
        rows.append({
            "employee": e.name,
            "employee_name": e.employee_name,
            "department": e.department,
            "default_shift": e.default_shift,
            "cells": cells,
        })
    return rows


def overrides(assignment_rows):
    """MG's sentence, exactly: *"Mr A's original shift_type is X, but the
    shift_assignment.doc changed it to B."*

    Same rows as the exceptions list, read from the employee's side with
    `default_shift` beside the assigned one — which is the comparison MG
    described and the reason this is one table with a `kind` column rather than
    two sections. A standalone assignment (`caf_swap_kind` empty) belongs here
    just as much as a swap does; to HR all three are *a document that overrides
    somebody's default shift*.
    """
    out = []
    for r in assignment_rows:
        emp = frappe.db.get_value(
            "Employee", r.employee, ["employee_name", "default_shift"], as_dict=True) or {}
        out.append({
            "name": r.name,
            "employee": r.employee,
            "employee_name": emp.get("employee_name") or r.employee,
            "default_shift": emp.get("default_shift"),
            "shift_type": r.shift_type,
            "changed": (emp.get("default_shift") or None) != r.shift_type,
            "kind": r.caf_swap_kind or "Single",
            "traded_with": r.caf_swap_with,
            "traded_with_name": frappe.db.get_value("Employee", r.caf_swap_with, "employee_name")
            if r.caf_swap_with else None,
            "partner": r.caf_swap_partner,
            "start_date": str(r.start_date),
            "end_date": str(r.end_date),
            "status": r.status,
        })
    out.sort(key=lambda r: (r["start_date"], r["employee_name"]))
    return out


@frappe.whitelist()
def holiday_gap(first=None, last=None):
    """OD-71's detector — MG chose the detector over HR's weekly prompt.

    A day the roster called Workday on which almost nobody punched at all. It
    would have caught 2026-02-14 by itself, with names, the following Monday.

    Future days are excluded: a working day that has not happened yet has no
    punches, and flagging it would make the alarm cry wolf every week.
    """
    frappe.only_for(ROLES)
    if not first or not last:
        first, last = _month_bounds()
    rows = frappe.db.sql(
        """
        SELECT work_date,
               COUNT(*)                                            AS rostered,
               SUM(CASE WHEN time_in IS NULL OR time_in IN ('00:00:00', '0:00:00')
                        THEN 1 ELSE 0 END)                         AS no_punch
          FROM `tabFinger Log`
         WHERE docstatus < 2
           AND day_type = 'Workday'
           AND work_date BETWEEN %(first)s AND %(last)s
           AND work_date <= %(today)s
      GROUP BY work_date
        HAVING rostered >= %(min_logs)s
           AND no_punch >= rostered * %(share)s
      ORDER BY work_date
        """,
        {"first": getdate(first), "last": getdate(last), "today": getdate(nowdate()),
         "min_logs": DETECTOR_MIN_LOGS, "share": DETECTOR_SHARE},
        as_dict=True,
    )
    for r in rows:
        r["work_date"] = str(r["work_date"])
        r["share"] = round(float(r["no_punch"]) / float(r["rostered"]), 3)
        r["names"] = [
            n[0] for n in frappe.db.sql(
                """SELECT e.employee_name
                     FROM `tabFinger Log` fl
                     JOIN `tabEmployee` e ON e.name = fl.employee
                    WHERE fl.docstatus < 2 AND fl.work_date = %s
                      AND fl.day_type = 'Workday'
                      AND (fl.time_in IS NULL OR fl.time_in IN ('00:00:00', '0:00:00'))
                 ORDER BY e.employee_name LIMIT 12""",
                r["work_date"])
        ]
    return {"rows": rows, "count": len(rows)}


# ── OD-69(b)'s detector ─────────────────────────────────────────────────────
# The mirror image of `holiday_gap`. That one finds a day the roster called WORK
# where nobody came; this finds a day the roster called REST where the whole
# group came in.
#
# 🔴 FLAG, NEVER BLOCK — MG's decision, and the reason is the group size. Working
# a rest day is legitimate: FBR4 makes all of it OT, and that is a paid, wanted
# path. Refusing the Finger Log would stop an employee's attendance, OT and
# appraisal figures over a roster error that is not their fault.
#
# ⚠️ And MG's own objection is what settles the shape: the `8-5` family has only
# TWO members, so "both worked a rest Saturday" is barely evidence — it could as
# easily be two people who simply came in. The `8:30am` family has six, where
# "all six" is a strong signal. So the finding CARRIES ITS GROUP SIZE, and HR
# reads 6-of-6 as urgent and 2-of-2 as worth a glance. The system does not
# pretend to know which.
GROUP_MIN = 2

# Saturdays only. A Sunday is a rest day for everybody, so a group working one is
# ordinary rest-day overtime, not a sign the alternation has slipped. The
# alternation lives entirely in Saturdays (measured 2026-08-13: a public holiday
# on any other weekday does not move the sequence at all).


def _punched(employee, work_date):
    row = frappe.db.get_value(
        "Finger Log", {"employee": employee, "work_date": getdate(work_date),
                       "docstatus": ("<", 2)}, ["name", "time_in"], as_dict=True)
    if not row:
        return None
    return row.name if str(row.time_in) not in NO_PUNCH else None


@frappe.whitelist()
def group_worked_rest_day(first=None, last=None):
    """OD-69(b) — a whole alternate-Saturday group worked a day their list rests.

    One person working a rest Saturday is overtime. **Every** member of the group
    working it is a roster error — and the difference lives in the count, not in
    any one document, which is exactly why this cannot be a rule at the log.
    February 2026 would have raised it three times.
    """
    frappe.only_for(ROLES)
    if not first or not last:
        first, last = _month_bounds()
    first, last = getdate(first), getdate(last)

    shifts = alt_shifts()
    alt_names = [s.name for s in shifts]
    _rows, by_day = _assignments_between(first, last)
    employees = roster_population(first, last, alt_names, by_day)

    out = []
    for d in _saturdays(first, last):
        if d > getdate(nowdate()):
            continue                     # nobody has punched yet — see holiday_gap
        groups = {}
        for e in employees:
            day_type, shift = resolve_day_type(e.name, d)
            if shift in alt_names and day_type == RESTDAY:
                groups.setdefault(shift, []).append(e)

        for shift, members in groups.items():
            if len(members) < GROUP_MIN:
                continue
            worked = [(e, _punched(e.name, d)) for e in members]
            worked = [(e, log) for e, log in worked if log]
            if len(worked) != len(members):
                continue
            out.append({
                "date": str(d),
                "shift": shift,
                "group_size": len(members),
                "worked": len(worked),
                "employees": [e.employee_name for e, _ in worked],
                "logs": [log for _, log in worked],
                # MG's point, carried to the screen rather than hidden in a
                # threshold: 6 of 6 is evidence, 2 of 2 is a coincidence away.
                "strength": "strong" if len(members) >= 3 else "weak",
            })
    return {"rows": out, "count": len(out)}


@frappe.whitelist()
def flag_group_rest_day_work(first=None, last=None):
    """Write `caf_hr_review` onto the logs the detector found. Same field and
    worklist Chunk 4 already uses, so HR has one queue and not two.

    ⚠️ `caf_hr_review` is deliberately OUTSIDE OD-62's guard — it exists for a
    human to act on, so HR keeps a route to clear a flag they have dealt with.
    """
    frappe.only_for(["HR Manager", "System Manager"])
    found = group_worked_rest_day(first, last)
    flagged = []
    for r in found["rows"]:
        note = _("All {0} of {1} on {2} worked {3}, which their Holiday List calls "
                 "a rest day. Either the roster is wrong, or a holiday is missing "
                 "from the list.").format(
                     r["worked"], r["group_size"], r["shift"], r["date"])
        for name in r["logs"]:
            doc = frappe.get_doc("Finger Log", name)
            if doc.get("caf_hr_review"):
                continue
            doc.caf_hr_review = 1
            doc.caf_hr_review_note = note
            doc.flags.ignore_permissions = True
            doc.flags.caf_system_write = True
            doc.save()
            # OD-26 — the trail, because a flag with no explanation is one HR
            # clears without understanding it.
            doc.add_comment("Comment", note)
            flagged.append(name)
    frappe.db.commit()
    return {"flagged": flagged, "count": len(flagged), "found": found["count"]}


@frappe.whitelist()
def get_roster(month=None):
    """Everything the page draws, in one round trip."""
    frappe.only_for(ROLES)

    first, last = _month_bounds(month)
    saturdays = _saturdays(first, last)

    shifts = alt_shifts()
    alt_names = [s.name for s in shifts]

    assignment_rows, by_day = _assignments_between(first, last)
    employees = roster_population(first, last, alt_names, by_day)

    return {
        "month": first.strftime("%Y-%m"),
        "month_label": first.strftime("%B %Y"),
        "first": str(first),
        "last": str(last),
        "saturdays": [str(d) for d in saturdays],
        "shifts": shifts,
        "rows": grid(first, last, alt_names, by_day, employees, saturdays),
        "overrides": overrides(assignment_rows),
        "half_done": half_done_swaps(),
        "holiday_gap": holiday_gap(first, last),
        "group_rest_work": group_worked_rest_day(first, last),
        # Stated on the screen rather than left to be inferred: the grid covers
        # alternating shifts only, so a standalone assignment for anyone else
        # appears in the table below it and NOWHERE in the grid.
        "assignment_total": frappe.db.count("Shift Assignment", {"docstatus": 1}),
    }


@frappe.whitelist()
def employees_on(shift):
    """Placement (a)'s question asked from the roster side: who is on this shift?

    The Shift Type form's Connections answers it for `default_shift`; this adds
    the per-date truth, which Connections cannot express because a form has no
    date on it.
    """
    frappe.only_for(ROLES)
    today = getdate(nowdate())
    standing = frappe.get_all(
        "Employee",
        filters={"default_shift": shift, "status": "Active"},
        fields=["name", "employee_name"],
        order_by="employee_name",
    )
    effective = [
        e for e in frappe.get_all(
            "Employee", filters={"status": "Active"}, fields=["name", "employee_name"])
        if get_shift_for_date(e.name, today) == shift
    ]
    return {
        "shift": shift,
        "standing": standing,
        "effective_today": sorted(effective, key=lambda e: e.employee_name or ""),
        "date": str(today),
    }
