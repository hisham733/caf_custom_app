"""Who arrived early on a day nobody sanctioned it — the call-the-planner list.

MG, 2026-09-15: *"given a work_date range, list all FL where the in punch is
earlier than X with respect to shift_type.start… to make it easy for HR to list
all incidents of early clock-in, before HR calls the planner for sanction
verification."*

🔴 WHY THE SANCTION TEST IS THE WHOLE POINT
-------------------------------------------
Listing *"who arrived early"* is useless: **91.7% of all logs clock in early**,
66.5% by more than five minutes. Even at an hour it is **54 days** — and **44 of
those 54 are perfectly sanctioned**, because the OT Approval covering the day
already says `start_work 07:00` against an 08:00 shift. A list where four rows in
five need no action is a list HR stops opening.

⭐ So this report asks the narrower question that actually has an answer:

    arrived more than X minutes early  AND  no submitted OT Approval
    for that day sanctions an early start

**Measured on this site: 54 days becomes 10.** Every one of the ten is a real
conversation with the planner, and every one is already in FBR85's worklist.

⚠️ AND THIS MATTERS BECAUSE THE SANCTION IS ALWAYS LATE
------------------------------------------------------
Production's OT Approvals are **never** filed in advance — 0 of 15,043 rows from
real filers; 11.2% on the day, 87.3% within a week, median one day. So *"no
sanction on file"* on a fresh day means *"not yet"*, not *"never"*. **Run this a
few days behind, not the same afternoon.**

WHY X IS A FILTER AND NOT A SETTING — MG's call
-----------------------------------------------
`HR Settings.caf_early_start_minutes` (60) still exists and is unchanged, but
this report does not read it. X belongs to the question being asked today, not to
the site: HR may want 60 for a weekly scan and 15 when chasing one person. The
filter defaults to **60** so the standing scan needs no thought.

🔴 THE MIRROR — and why it is NOT symmetrical
---------------------------------------------
The obvious mirror is *"clocked out more than X after the shift end with no
sanction"*, and it already has a different home: **that case BLOCKS the Finger
Log** (FBR11 — overtime with no approval refuses the submit), so it appears in
`Attendance Follow-Up` as a blocked row and nothing can be paid for it. An
unsanctioned EARLY start blocks nothing, pays nothing, and is invisible — which
is exactly why it needs a report of its own.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, getdate, nowdate

from caf.caf.shift_resolution import get_shift_params

BLANK = ("None", "0:00:00", "00:00:00", "")


def execute(filters=None):
    frappe.only_for(["HR Manager", "System Manager"])
    filters = frappe._dict(filters or {})
    return _columns(), _rows(filters)


def _columns():
    return [
        {"label": _("Work Date"), "fieldname": "work_date",
         "fieldtype": "Date", "width": 95},
        {"label": _("Employee"), "fieldname": "employee_name",
         "fieldtype": "Data", "width": 190},
        {"label": _("Shift starts"), "fieldname": "shift_start",
         "fieldtype": "Data", "width": 90},
        {"label": _("Clocked in"), "fieldname": "clocked_in",
         "fieldtype": "Data", "width": 90},
        {"label": _("Minutes early"), "fieldname": "minutes_early",
         "fieldtype": "Int", "width": 105},
        # ⭐ The column that turns a list into a decision: was it asked for?
        {"label": _("Sanctioned?"), "fieldname": "sanctioned",
         "fieldtype": "Data", "width": 190},
        {"label": _("OT paid (h)"), "fieldname": "ot_in_hour",
         "fieldtype": "Float", "width": 95, "precision": 2},
        {"label": _("Finger Log"), "fieldname": "finger_log",
         "fieldtype": "Link", "options": "Finger Log", "width": 150},
        {"label": _("Shift"), "fieldname": "shift_type",
         "fieldtype": "Link", "options": "Shift Type", "width": 160},
    ]


def _mins(t):
    if not t or str(t) in BLANK:
        return None
    parts = str(t).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _hhmm(m):
    return "%02d:%02d" % (m // 60, m % 60) if m is not None else "—"


def _rows(filters):
    # 🔴 The default window STOPS A WEEK BACK, and that is not caution — it is
    # the measured filing lag. Production files an OT Approval a median of ONE
    # day after the work date and 90% within two, so a day from this morning has
    # no sanction on file yet and would appear here as a problem it is not.
    # Measured on this site: the September import left 352 logs and **zero**
    # approvals covering September, which turns a 10-row list into a 62-row one
    # made almost entirely of days nobody has processed yet.
    to_date = getdate(filters.get("to_date") or add_days(nowdate(), -7))
    from_date = getdate(filters.get("from_date") or add_months(to_date, -3))
    threshold = int(filters.get("minutes_early") or 60)
    show_sanctioned = bool(filters.get("include_sanctioned"))

    logs = frappe.get_all(
        "Finger Log",
        filters={"work_date": ("between", [from_date, to_date]),
                 "docstatus": ("<", 2)},
        fields=["name", "employee", "employee_name", "shift_type", "work_date",
                "day_type", "time_in", "ot_in_hour"],
        order_by="work_date desc", limit_page_length=0)

    params, out = {}, []
    for log in logs:
        if log.shift_type not in params:
            params[log.shift_type] = get_shift_params(log.shift_type)
        p = params[log.shift_type]
        start = _mins(p.get("start_time")) if p else None
        t_in = _mins(log.time_in)
        if start is None or t_in is None or t_in >= start:
            continue
        early = start - t_in
        if early <= threshold:
            continue

        # Does a submitted approval for that day sanction an earlier start?
        row = frappe.get_all(
            "OT Approval Table",
            filters={"emp_id": log.employee, "work_date": log.work_date,
                     "docstatus": 1},
            fields=["parent", "start_work"], order_by="creation desc", limit=1)
        if not row:
            sanctioned, ok = _("no approval for this day at all"), False
        else:
            sw = _mins(row[0].start_work)
            if sw is not None and sw < start:
                sanctioned = _("yes — {0} sanctions {1}").format(
                    row[0].parent, _hhmm(sw))
                ok = True
            else:
                sanctioned = _("NO — {0} starts them at {1}").format(
                    row[0].parent, _hhmm(sw) if sw is not None else "—")
                ok = False

        if ok and not show_sanctioned:
            continue

        out.append({
            "work_date": log.work_date,
            "employee_name": log.employee_name,
            "shift_start": _hhmm(start),
            "clocked_in": str(log.time_in)[:5],
            "minutes_early": early,
            "sanctioned": sanctioned,
            "ot_in_hour": flt(log.ot_in_hour or 0),
            "finger_log": log.name,
            "shift_type": log.shift_type,
        })
    return out
