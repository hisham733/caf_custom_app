"""Ingress ➜ Finger Log import. Chunk 3. Field contract: CAF_BUILD_SPEC.md §9.6.

THE ONE RULE THAT MATTERS MOST
-----------------------------
🔴 **`day_type` and `shift_type` are NEVER imported.** Ingress' `daytype` and
`sche1` play no part in the target design (**OD-45**) — the shift comes from a
Shift Assignment covering the date, else `Employee.default_shift`, and the day
type is resolved from that shift's working week. Importing Ingress' opinion
would silently reintroduce the machine as the authority and undo Chunk 2.

`caf_work_hours` and `short` are likewise **derived, not imported** (OD-59) —
`validate()` computes them, so this module simply does not set them.

WHAT IS IMPORTED
----------------
    work_date            Ingress `date`      the business date, FBR7
    time_in break resume out    the four punches — FACTS, FDR10
    overtime             `othour`            hour.minute, FBR2
    ftag_id              `userid`            provenance, and the join key

WHO IS IMPORTED — OD-24
-----------------------
Employees who are **Active** and carry an `attendance_device_id`. Ingress keeps
emitting rostered days for people who left years ago (one ex-employee has 457
such rows, none of them punched), and those map to nobody. An **active**
employee who simply did not turn up DOES get a row, with no punches — that is
the `Absent` case and it is the point of the design, not noise.

SAFETY
------
**Savepoint per row.** A bare `rollback()` inside a per-row `except` destroyed
~5,600 good rows in this project. Twice.
"""

import csv
import gzip
from datetime import datetime

import frappe
from frappe.utils import getdate

SNAPSHOT = "/tmp/attendance.csv.gz"

# Ingress column -> Finger Log field. The punches only; everything else is
# either derived or deliberately excluded.
PUNCHES = {
    "att_in": "time_in",
    "att_break": "break",
    "att_resume": "resume",
    "att_out": "out",
}

# 🔴 NEVER import these. Listed so the omission is visible rather than accidental.
NEVER_IMPORT = {
    "daytype": "day_type is resolved from the shift — OD-45",
    "sche1": "shift_type is resolved from Shift Assignment / default_shift — OD-45",
    "workhour": "caf_work_hours is derived — OD-59",
    "shorthour": "short is derived — OD-59",
    "leavetype": "leave_type belongs to the Leave Application — FDR4",
}


def _date(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _time(value):
    """A punch, or the all-zero sentinel when the machine recorded nothing.

    ⚠️ Writes '00:00:00', NOT NULL — deliberately. The whole absence path keys on
    the all-zero row, and testing `time_in IS NULL` is the trap that produced a
    withdrawn decision (OD-49) after returning 0 of 21,363.
    """
    value = (value or "").strip()
    if not value:
        return "00:00:00"
    parts = value.split(":")
    if len(parts) == 2:
        parts.append("00")
    try:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(float(parts[2])):02d}"
    except (ValueError, IndexError):
        return "00:00:00"


def _float(value):
    try:
        return float((value or "0").strip() or 0)
    except ValueError:
        return 0.0


def active_by_device() -> dict:
    rows = frappe.get_all("Employee", filters={"status": "Active"},
                          fields=["name", "employee_name", "attendance_device_id"])
    return {str(r.attendance_device_id).strip(): r for r in rows if r.attendance_device_id}


def run(snapshot: str = SNAPSHOT, from_date=None, to_date=None, submit: bool = True,
        limit: int = 0) -> dict:
    """Import a date range. Existing live rows for a date are left alone (FDR1)."""
    by_device = active_by_device()
    from_date = getdate(from_date) if from_date else None
    to_date = getdate(to_date) if to_date else None

    stats = frappe._dict(read=0, skipped_no_employee=0, skipped_out_of_range=0,
                         already_present=0, created=0, submitted=0,
                         not_full_day=0, failed=0)
    errors, not_full = {}, []

    with gzip.open(snapshot, "rt", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            day = _date(row.get("date"))
            if not day:
                continue
            if (from_date and day < from_date) or (to_date and day > to_date):
                stats.skipped_out_of_range += 1
                continue

            emp = by_device.get((row.get("userid") or "").strip())
            if not emp:
                stats.skipped_no_employee += 1
                continue

            stats.read += 1
            if limit and stats.created >= limit:
                break

            # FDR1 — one LIVE Finger Log per employee per work_date.
            if frappe.db.exists("Finger Log", {"employee": emp.name, "work_date": day,
                                               "docstatus": ("<", 2)}):
                stats.already_present += 1
                continue

            sp = f"fl_{stats.read}"
            frappe.db.savepoint(sp)
            try:
                doc = frappe.new_doc("Finger Log")
                doc.employee = emp.name
                doc.employee_name = emp.employee_name      # from ERPNext, not Ingress
                doc.ftag_id = (row.get("userid") or "").strip()
                doc.work_date = day
                for src, field in PUNCHES.items():
                    doc.set(field, _time(row.get(src)))
                doc.overtime = _float(row.get("othour"))
                doc.flags.ignore_permissions = True
                doc.insert()                                # validate() derives the rest
                stats.created += 1

                if doc.caf_not_full_day:
                    # OD-58 — leave it in draft for HR. Not an error.
                    stats.not_full_day += 1
                    not_full.append(f"{emp.name} {day}")
                elif submit:
                    doc.submit()
                    stats.submitted += 1
            except Exception as e:
                frappe.db.rollback(save_point=sp)
                stats.failed += 1
                errors[f"{emp.name} {day}"] = str(e).splitlines()[0][:130]

    frappe.db.commit()

    for k, v in stats.items():
        print(f"{k:24s} {v}")
    if not_full:
        print(f"\nNOT FULL DAY - left in draft for HR ({len(not_full)}):")
        for n in not_full[:10]:
            print(f"   {n}")
    if errors:
        print(f"\nfailed ({len(errors)}):")
        for k, v in list(errors.items())[:10]:
            print(f"   {k}: {v}")
    return {"stats": dict(stats), "errors": errors, "not_full_day": not_full}


def import_month(year, month, snapshot: str = SNAPSHOT):
    """Convenience for the checkpoint: one calendar month."""
    from calendar import monthrange
    year, month = int(year), int(month)
    last = monthrange(year, month)[1]
    return run(snapshot, f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}")
