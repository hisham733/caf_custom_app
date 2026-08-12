"""Seed the rest-Saturday Shift Assignments from the Ingress snapshot.

Chunk 2b item 5, roadmap §6. Implements **OD-52**.

THE MECHANISM
-------------
A Saturday swap files TWO Shift Assignments, one per employee. The man covering
gets one pointing at a shift that works Saturday; the man resting gets one
pointing at a shift that does NOT. `Shift Assignment.shift_type` is `reqd`, so
"you are not working" can only be said by naming a shift whose working week
excludes that day — which is why CAF has three real no-Saturday shifts and why
`caf_work_sat` is the field that carries the meaning.

The resting employee's other shift parameters are never consulted: he is not
working that day, so its times, OT gate and rounding do not matter. The nearest
start time is chosen anyway, so the row reads sensibly to a human.

WHAT IS AND IS NOT SEEDED
-------------------------
Source: `ingress_snapshot/attendance.csv.gz`, `daytype = 'R'` on a Saturday,
matched to an Active employee by `attendance_device_id`.

⚠️ **This is a TEST fixture, not a production migration.** `development.localhost`
needs enough real rest Saturdays to exercise OD-52 in both directions — it does
not need CAF's full roster history, and pulling the whole snapshot in drags along
one-off events that have to be reasoned about individually. `SEED_MONTHS` keeps
the window to the recent past for that reason. Widening it is a decision, not a
default: at 14 months the load also picks up **2026-04-04**, a company-wide
Saturday shutdown affecting 76 of 88 employees, which is a Holiday List question
rather than 76 Shift Assignments.

Two filters:

  1. Only the last `SEED_MONTHS` months. Older rest Saturdays are real but add
     nothing a test can use.

  2. Employees whose DEFAULT shift already does not work Saturday are SKIPPED.
     Their Saturdays resolve Restday without any assignment; filing one would be
     a no-op that only makes the data look busier than it is.

⚠️ Check per employee, never in aggregate. The same source counted over three
different windows gives 545 rows / 78 employees, 469 / 16, and 316 / 13 — all
"plausible" totals hiding entirely different sets of people.

USAGE
-----
    docker cp attendance.csv.gz frappe:/tmp/attendance.csv.gz
    bench --site <site> execute caf.scripts.seed_rest_saturdays.seed

Re-runnable: it removes the assignments it made on a previous run first, not
last, so a failed run does not poison the next one — and so narrowing the window
actually shrinks the data rather than leaving orphans behind.
"""

import csv
import gzip
from collections import defaultdict
from datetime import datetime

import frappe
from frappe.utils import add_months, getdate, nowdate

SNAPSHOT = "/tmp/attendance.csv.gz"

# How far back to seed. A test fixture, not a migration — see the header.
SEED_MONTHS = 3


def _date(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def no_saturday_shifts() -> list:
    """The shifts that can express "resting this Saturday", nearest time first."""
    return frappe.get_all("Shift Type", filters={"caf_work_sat": 0},
                          fields=["name", "start_time", "caf_allow_ot"],
                          order_by="start_time")


def pick_rest_shift(default_shift: str, candidates: list) -> str:
    """A no-Saturday shift that preserves the employee's OT eligibility.

    ⚠️ The framework says the rest shift's parameters do not matter because he
    is not working that day. That is true right up until he works anyway — and
    then it matters a lot, because `caf_allow_ot` is read off the RESOLVED
    shift. Two of CAF's three no-Saturday shifts carry `caf_allow_ot = 0`, so a
    naive nearest-start-time pick would quietly revoke OT eligibility from
    someone whose own shift grants it — and **all rest-day work is OT (FBR4)**.
    The assignment is meant to say "not working today", nothing more.

    So match `caf_allow_ot` first, and only then break ties on start time.
    """
    default = frappe.db.get_value("Shift Type", default_shift,
                                  ["start_time", "caf_allow_ot"], as_dict=True)
    if not default:
        return candidates[0].name

    same_ot = [c for c in candidates if bool(c.caf_allow_ot) == bool(default.caf_allow_ot)]
    pool = same_ot or candidates

    if default.start_time is None:
        return pool[0].name
    return min(pool, key=lambda c: abs((c.start_time - default.start_time).total_seconds())).name


def collect(snapshot: str = SNAPSHOT, since=None) -> dict:
    """{employee: {date: default_shift}} — the Saturdays needing an assignment."""
    since = getdate(since or add_months(nowdate(), -SEED_MONTHS))
    by_device, sat_works = {}, {}
    for s in frappe.get_all("Shift Type", fields=["name", "caf_work_sat"]):
        sat_works[s.name] = s.caf_work_sat
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "attendance_device_id", "default_shift", "company"]):
        if e.attendance_device_id:
            by_device[str(e.attendance_device_id).strip()] = e

    # 🔴 FUTURE DATES ARE NOT OBSERVATIONS — bug found 2026-08-12.
    #
    # Ingress carries PLANNED roster months ahead, and for some employees those
    # future rows default to `daytype = 'R'`. This function read them as fact.
    # Measured: 20 of Dina Laila's 20 rows, and 20 of 33 each for Rajaindran and
    # Chen Xiao Natalie, came from dates that had not happened — and HR confirmed
    # none of the three has alternate Saturdays at all. **86 assignments asserted a
    # rest day nobody had taken.**
    #
    # Dina Laila is the clean proof: her past Saturdays are 0 of 4 rested, her
    # future ones 20 of 20.
    today = getdate(nowdate())

    wanted = defaultdict(dict)
    with gzip.open(snapshot, "rt", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            if (row.get("daytype") or "").strip().upper() != "R":
                continue
            day = _date(row.get("date"))
            if not day or day.weekday() != 5 or day < since or day > today:
                continue
            emp = by_device.get((row.get("userid") or "").strip())
            if not emp or not emp.default_shift:
                continue
            # filter 1 — his own shift already rests on Saturday
            if not sat_works.get(emp.default_shift):
                continue
            wanted[emp.name][day] = emp

    return wanted


def clear(employees=None) -> int:
    """Remove previously seeded rows — single-day assignments onto a no-Sat shift."""
    shifts = [s.name for s in no_saturday_shifts()]
    filters = {"shift_type": ("in", shifts)}
    if employees:
        filters["employee"] = ("in", list(employees))

    removed = 0
    for sa in frappe.get_all("Shift Assignment", filters=filters,
                             fields=["name", "docstatus", "start_date", "end_date"]):
        if sa.start_date != sa.end_date:
            continue
        doc = frappe.get_doc("Shift Assignment", sa.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Shift Assignment", sa.name, ignore_permissions=True, force=True)
        removed += 1
    return removed


def seed(snapshot: str = SNAPSHOT, submit: bool = True, since=None) -> dict:
    since = getdate(since or add_months(nowdate(), -SEED_MONTHS))
    wanted = collect(snapshot, since)
    # Clear ALL previously seeded rows, not just the ones inside the current
    # window — otherwise narrowing the window leaves the old rows orphaned and
    # the fixture never actually shrinks.
    removed = clear()
    candidates = no_saturday_shifts()

    created, failed = 0, {}
    for employee, days in wanted.items():
        for day, emp in sorted(days.items()):
            # Savepoint per row. A bare rollback in a per-row except once
            # destroyed ~5,600 good rows in this project. Twice.
            sp = f"sa_{employee.replace('-', '_')}_{day:%Y%m%d}"[:60]
            frappe.db.savepoint(sp)
            try:
                doc = frappe.new_doc("Shift Assignment")
                doc.employee = employee
                doc.company = emp.company
                doc.shift_type = pick_rest_shift(emp.default_shift, candidates)
                doc.start_date = day
                doc.end_date = day
                doc.status = "Active"
                doc.flags.ignore_permissions = True
                doc.insert()
                if submit:
                    doc.submit()
                created += 1
            except Exception as e:
                frappe.db.rollback(save_point=sp)
                failed[f"{employee} {day}"] = str(e).split("\n")[0][:120]

    frappe.db.commit()

    print(f"window           {since} onward ({SEED_MONTHS} months)")
    print(f"employees        {len(wanted)}")
    print(f"removed (rerun)  {removed}")
    print(f"created          {created}")
    print(f"failed           {len(failed)}")
    for k, v in list(failed.items())[:10]:
        print(f"   {k}: {v}")
    return {"employees": len(wanted), "created": created, "removed": removed, "failed": failed}
