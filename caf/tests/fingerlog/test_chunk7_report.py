"""Chunk 7.1 — the My Attendance report, proven AS A ROLE. OD-12 / OD-63.

    bench --site <site> execute caf.tests.fingerlog.test_chunk7_report.run

FIX SESSION 2026-08-15 (D-1/D-2/D-5): the report is now HR-ONLY. Employees use
the scoped /app/finger-log list + calendar instead (option d) — their rows are
asserted in `workflow_gaps/run_session_decisions.ps1` (AC-1). This suite now
proves: the desk gate refuses employees, and the HR view still works end-to-end
(scope internals, join, drafts).

🔴 WHY THIS FILE IS MOSTLY ABOUT PERMISSION
-------------------------------------------
A **Script Report runs its own SQL**. So `permission_query_conditions` never
fires, and the desk gate is `query_report.py:57`:
`has_permission(ref_doctype, "report")` — Finger Log holds `report=0` for the
Employee role (D-1 Custom DocPerm row), so the gate refuses them. The gate is
what a real employee hits; `execute()` alone bypasses it, which is exactly the
miss the 2026-08-14 testing session found (C7 used to call execute() directly).

Read-only throughout: this suite creates no documents, so it needs no cleanup and
cannot eat imported data (§F4). It reads the July import deliberately, because
that is the realistic shape.
"""

import frappe

from caf.caf.report.my_attendance import my_attendance

EMP_USER = "seriramulu@caffood.com"       # HR-EMP-00075, role Employee
EMP = "HR-EMP-00075"
OTHER = "HR-EMP-00016"                    # someone they must NOT be able to read
HRM = "hr.manager.test@caffood.com"

FLT = {"from_date": "2026-07-01", "to_date": "2026-07-31"}

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def as_user(user, fn, *a):
    frappe.set_user(user)
    try:
        return fn(*a), ""
    except Exception as e:
        return None, type(e).__name__
    finally:
        frappe.set_user("Administrator")


def own_rows(employee):
    # docstatus < 2 — drafts included. A leave day's log is a DRAFT (assert_no_clash
    # refused it) and so is a miss-punch (OD-58); excluding them made 380 of the
    # July rows vanish from the employee's own record.
    return frappe.db.count("Finger Log", {"employee": employee, "docstatus": ("<", 2),
                                          "work_date": ("between", [FLT["from_date"],
                                                                    FLT["to_date"]])})


def fingerprint(employee):
    """A value that differs between employees, unlike a row COUNT."""
    return frappe.db.sql("""SELECT ROUND(SUM(IFNULL(caf_work_hours,0)), 2)
                              FROM `tabFinger Log`
                             WHERE employee=%s AND docstatus < 2
                               AND work_date BETWEEN %s AND %s""",
                         (employee, FLT["from_date"], FLT["to_date"]))[0][0] or 0


def data_fingerprint(data):
    return round(sum((d.get("caf_work_hours") or 0) for d in (data or [])), 2)


def run():
    try:
        mine, other = own_rows(EMP), own_rows(OTHER)
        fp_mine, fp_other = fingerprint(EMP), fingerprint(OTHER)
        check("C7-FIX", mine > 0 and other > 0 and fp_mine != fp_other,
              f"fixture: {EMP} has {mine} logs / {fp_mine} h, {OTHER} has {other} / "
              f"{fp_other} h. ⚠️ the COUNTS are identical, so every scope assertion "
              f"below compares HOURS — a count could not tell the two apart")

        # ------------------------------------------------------- C7-GATE-EMP
        # The desk path — the exact 403 a real employee sees (issue 1). Roles on
        # the Report are HR-only (D-2) and Employee holds report=0 on Finger Log
        # (D-1). execute() alone would bypass this, so the gate itself is the
        # assertion (the 2026-08-14 session's miss).
        from frappe.desk.query_report import run as report_run
        (_, err) = as_user(EMP_USER, report_run, "My Attendance", FLT)
        check("C7-GATE-EMP", err == "PermissionError",
              f"desk gate: Employee running My Attendance -> {err} "
              f"(must be PermissionError, never a 200)")

        # ------------------------------------------------------- C7-GATE-HR
        (hres, _) = as_user(HRM, report_run, "My Attendance", FLT)
        hresult = (hres or {}).get("result") if isinstance(hres, dict) else None
        check("C7-GATE-HR", hresult is not None and len(hresult) > 0,
              f"desk gate: HR Manager runs the same report -> "
              f"{len(hresult or [])} rows (must pass the gate)")

        # ------------------------------------------------------------ C7-HR
        hres2, _ = as_user(HRM, my_attendance.execute, FLT)
        hcols, hdata = hres2 if hres2 else (None, None)
        hnames = [c["fieldname"] for c in hcols] if hcols else []
        check("C7-HR", hdata is not None and len(hdata) > mine
              and "leave_type" in hnames and "ot_approval_id" in hnames,
              f"HR Manager sees {len(hdata) if hdata is not None else 'ERROR'} rows "
              f"(> any single employee's {mine}) and gets both HR-only columns")

        hfil, _ = as_user(HRM, my_attendance.execute, dict(FLT, employee=OTHER))
        _, hfdata = hfil if hfil else (None, None)
        check("C7-HRFILT", hfdata is not None and data_fingerprint(hfdata) == fp_other,
              f"...and for HR the Employee filter IS honoured: {data_fingerprint(hfdata)} h "
              f"for {OTHER}, matching their {fp_other}")

        # ------------------------------------------------------------ C7-JOIN
        # The status/leave verdict comes from Attendance, never from the log — FDR4.
        with_leave = [d for d in (hdata or []) if d.get("leave_type")]
        check("C7-JOIN", with_leave,
              f"the Attendance join works: {len(with_leave)} HR row(s) carry a leave_type, "
              f"e.g. {with_leave[0]['leave_type'] if with_leave else '—'} "
              f"(FDR4 — it comes from Attendance, never from the Finger Log)")

        leave_rows = [d for d in (hdata or []) if d.get("leave_type")]
        check("C7-STATUS2", leave_rows and all(d.get("status") for d in leave_rows),
              f"and every leave row has one: "
              f"{sorted({d['status'] for d in leave_rows})} across {len(leave_rows)} row(s) "
              f"— previously these showed as an empty dated row")

        # ------------------------------------------------------------ C7-DRAFT
        drafts = frappe.db.count("Finger Log",
                                 {"docstatus": 0,
                                  "work_date": ("between", [FLT["from_date"],
                                                            FLT["to_date"]])})
        check("C7-DRAFT", drafts > 0 and len(hdata or []) > (
            frappe.db.count("Finger Log",
                            {"docstatus": 1,
                             "work_date": ("between", [FLT["from_date"],
                                                       FLT["to_date"]])})),
              f"drafts are INCLUDED: {drafts} draft log(s) in July (leave days + "
              f"miss-punches), and the report returns {len(hdata or [])} rows — more "
              f"than the submitted-only count. Excluding them hid all 52 leave days")
    finally:
        frappe.set_user("Administrator")

    print("\n=== Chunk 7.1 — My Attendance, as a role ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:10s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    print(f"   session restored to: {frappe.session.user}")
    return not failed
