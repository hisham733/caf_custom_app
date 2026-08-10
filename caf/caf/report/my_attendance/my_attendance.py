"""My Attendance — the self-service Finger Log report. Chunk 7.1, OD-12 / OD-63.

    Desk: /app/query-report/My Attendance

WHY THIS EXISTS, IN MG'S WORDS
------------------------------
    "this dash enables emp to double check to ensure that design framework is
     correct"

Not convenience — **verification**. 117 people checking `day_type`, the resolved
shift, the work-hour formula and the OT arithmetic against what they personally
remember. Chunk T's 84 assertions prove the code does what the developer thinks it
should; this is the only thing that proves the **model matches reality**, and it
is why MG sequenced it before Chunk 6, while leave migration is still reversible.

The error class it is aimed at is real and has happened: 287 false `Absent` rows
in a single month, every one a Sunday, because the creation path had no `day_type`
check. `day_type` and `short` are in the column list precisely because a person
recognises *"that Saturday was my rest day"* instantly and a test does not.

🔴 PERMISSION LIVES IN `execute()`, NOT IN A HOOK
------------------------------------------------
OD-63: an employee sees **only their own** rows; **HR Manager sees all**;
supervisors are deliberately excluded, unlike the appraisal's subtree rule
(D18/D55) — punch times and lateness are personal data.

⚠️ A **Script Report runs its own SQL**, so `permission_query_conditions` never
fires and the `Report` doctype's role list only controls who can OPEN it, not what
they get back. **The scoping below is the whole of the enforcement.** A filter in
the `.js`, or a column the front end hides, is not a permission — that is the same
mistake as workflow `allow_edit` (PROTOCOL §C4). Test R-OWN asserts another
employee's rows are ABSENT from the result, not merely un-rendered.

`leave_type` and the OT Approval link are HR-only for the same reason: `leave_type`
discloses **MC**, which is health information.
"""

import frappe
from frappe import _

from caf.caf.overrides.appraisal import get_employee_for_user, is_hr_manager

# MG's field list, 2026-08-11. `status` is deliberately absent — see the report's
# entry in roadmap §9d.1 for the open question about putting it back.
BASE_COLUMNS = [
    ("work_date", _("Work Date"), "Date", 100),
    ("shift_type", _("Shift"), "Data", 150),
    ("day_type", _("Day Type"), "Data", 100),
    ("time_in", _("In"), "Data", 80),
    ("lunch", _("Lunch"), "Data", 140),
    ("out", _("Out"), "Data", 80),
    ("caf_work_hours", _("Work Hours"), "Float", 100),
    ("short", _("Short"), "Float", 90),
    ("final_ot", _("Final OT"), "Float", 90),
]

HR_ONLY_COLUMNS = [
    ("leave_type", _("Leave Type"), "Data", 130),
    ("ot_approval_id", _("OT Approval"), "Data", 150),
]


def get_columns(hr):
    cols = list(BASE_COLUMNS) + (list(HR_ONLY_COLUMNS) if hr else [])
    return [{"fieldname": f, "label": lbl, "fieldtype": ft, "width": w}
            for f, lbl, ft, w in cols]


def _hhmm(value):
    """A punch as HH:MM, and an all-zero punch as nothing at all.

    Ingress writes `00:00:00` rather than NULL for "did not punch" — the trap that
    produced OD-49 and cost a blocking decision. Rendering it as `00:00` would
    invite every employee to report a bug that is not one.
    """
    if not value:
        return ""
    text = str(value)
    if text.startswith("0:00:00") or text.startswith("00:00:00"):
        return ""
    parts = text.split(":")
    return f"{int(parts[0]):02d}:{parts[1]}" if len(parts) >= 2 else text


def execute(filters=None):
    filters = frappe._dict(filters or {})
    hr = is_hr_manager()

    # 🔴 `< 2`, NOT `= 1`. Cancelled rows are excluded; DRAFTS are not.
    #
    # Measured on the July import: 380 of 2,568 logs are drafts, and they are
    # precisely the days a person would most want to check —
    #   • 50 of the 52 leave days, where `assert_no_clash` correctly REFUSED to let
    #     a Finger Log overwrite a day a Leave Application had already decided
    #     (FDR4), leaving the log in draft;
    #   • 241 `caf_not_full_day` rows — a forgotten tap-out, held for HR (OD-58).
    #
    # Filtering them out made every leave day and every miss-punch VANISH from the
    # employee's own record. A missing row reads as data loss, which is the
    # opposite of what this report is for.
    conditions = ["fl.docstatus < 2"]
    values = {}

    # 🔴 OD-63 — the only place this is enforced.
    if hr:
        if filters.get("employee"):
            conditions.append("fl.employee = %(employee)s")
            values["employee"] = filters.employee
    else:
        own = get_employee_for_user()
        if not own:
            frappe.msgprint(_(
                "Your user account is not linked to an Employee record, so there is no "
                "attendance to show. Ask HR to set the User ID on your Employee record."))
            return get_columns(False), []
        conditions.append("fl.employee = %(employee)s")
        values["employee"] = own

    if filters.get("from_date"):
        conditions.append("fl.work_date >= %(from_date)s")
        values["from_date"] = filters.from_date
    if filters.get("to_date"):
        conditions.append("fl.work_date <= %(to_date)s")
        values["to_date"] = filters.to_date

    rows = frappe.db.sql("""
        SELECT fl.work_date, fl.shift_type, fl.day_type, fl.time_in, fl.`break`,
               fl.resume, fl.`out`, fl.caf_work_hours, fl.short, fl.final_ot,
               fl.ot_approval_id, att.leave_type
          FROM `tabFinger Log` fl
          -- 🔴 JOIN ON employee + date, NOT on `att.caf_finger_log`.
          -- A leave-created Attendance has NO Finger Log link: stock's
          -- update_attendance() only reuses an existing row, and where none
          -- exists it inserts a fresh one with `caf_finger_log` empty. So joining
          -- on the link misses exactly the rows that carry `leave_type` — the one
          -- case the column exists for. Caught by test C7-JOIN, which returned 0
          -- leave rows out of 2,188 against the link join.
          -- Employee + date is also how the appraisal reads Attendance (§1.2).
          LEFT JOIN `tabAttendance` att
                 ON att.employee = fl.employee
                AND att.attendance_date = fl.work_date
                AND att.docstatus = 1
         WHERE {conditions}
      ORDER BY fl.work_date DESC
    """.format(conditions=" AND ".join(conditions)), values, as_dict=True)

    data = []
    for r in rows:
        lunch_out, lunch_in = _hhmm(r.get("break")), _hhmm(r.resume)
        row = {
            "work_date": r.work_date,
            "shift_type": r.shift_type,
            "day_type": r.day_type,
            "time_in": _hhmm(r.time_in),
            # One column, both halves — MG's list has a single "lunch". The raw
            # pair still shows, because verification needs the actual times.
            "lunch": f"{lunch_out} – {lunch_in}" if (lunch_out or lunch_in) else "",
            "out": _hhmm(r.get("out")),
            "caf_work_hours": r.caf_work_hours,
            "short": r.short,
            "final_ot": r.final_ot,
        }
        if hr:
            row["leave_type"] = r.leave_type or ""
            # Rendered as a new-tab anchor by the formatter in my_attendance.js.
            # Kept as Data, not Link: a Link opens in the same tab and would lose
            # the row the user was reading.
            row["ot_approval_id"] = r.ot_approval_id or ""
        data.append(row)

    return get_columns(hr), data
