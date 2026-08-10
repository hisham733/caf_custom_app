"""Chunk 7.1 — the My Attendance report, proven AS A ROLE. OD-12 / OD-63.

    bench --site <site> execute caf.tests.fingerlog.test_chunk7_report.run

🔴 WHY THIS FILE IS MOSTLY ABOUT PERMISSION
-------------------------------------------
A **Script Report runs its own SQL**. So `permission_query_conditions` never
fires, and the `Report` doctype's role list controls only who may OPEN the report,
not what comes back. **`execute()` is the entire enforcement**, which makes it the
one thing worth testing hardest.

C7-SCOPE is the test that matters: the report exposes an **Employee filter**, and
a non-HR caller must not be able to use it to read somebody else. The filter is
sent by the browser, so it is attacker-controlled — a `depends_on` in the `.js`
hides the field and hides nothing else (PROTOCOL §C4).

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
    """A value that differs between employees, unlike a row COUNT.

    🔴 Both fixture employees have exactly 31 July logs, so `len(data) == 31`
    passes whether the report returned their own rows or somebody else's. That is
    the W3 trap — an assertion that cannot fail for the reason it claims. The sum
    of hours worked is unique to the person.
    """
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

        # ------------------------------------------------------------ C7-OWN
        (res, _), err = as_user(EMP_USER, my_attendance.execute, FLT), ""
        (cols, data), err = res if isinstance(res, tuple) else ((None, None), "error"), ""
        check("C7-OWN", data is not None and len(data) == mine
              and data_fingerprint(data) == fp_mine,
              f"{EMP_USER} sees {len(data) if data is not None else 'ERROR'} rows / "
              f"{data_fingerprint(data)} h — their own ({mine} / {fp_mine}), not "
              f"{OTHER}'s ({fp_other}) and not everyone's")

        # ------------------------------------------------------------ C7-COLS
        names = [c["fieldname"] for c in cols]
        check("C7-COLS", "leave_type" not in names and "ot_approval_id" not in names,
              f"and the HR-only columns are ABSENT from their result, not merely hidden: "
              f"{names}")

        # ------------------------------------------------------------ C7-SCOPE
        # 🔴 The one that matters. The Employee filter comes from the browser.
        widened, _ = as_user(EMP_USER, my_attendance.execute,
                             dict(FLT, employee=OTHER))
        wcols, wdata = widened if widened else (None, None)
        # ⚠️ Length AND hours. This fixture's own total happens to be 0 h, so an
        # hours-only check would also pass on an EMPTY result — "returned nothing"
        # is not the same as "returned only their own", and the difference is the
        # whole assertion.
        check("C7-SCOPE", wdata is not None and len(wdata) == mine
              and data_fingerprint(wdata) == fp_mine
              and data_fingerprint(wdata) != fp_other,
              f"passing employee={OTHER} as the Employee user returns "
              f"{len(wdata) if wdata is not None else 'ERROR'} rows / "
              f"{data_fingerprint(wdata)} h — still their OWN ({mine} / {fp_mine}), not "
              f"{OTHER}'s ({fp_other}). The browser-supplied filter cannot widen scope")

        # ------------------------------------------------------------ C7-HR
        hres, _ = as_user(HRM, my_attendance.execute, FLT)
        hcols, hdata = hres if hres else (None, None)
        hnames = [c["fieldname"] for c in hcols] if hcols else []
        check("C7-HR", hdata is not None and len(hdata) > mine
              and "leave_type" in hnames and "ot_approval_id" in hnames,
              f"HR Manager sees {len(hdata) if hdata is not None else 'ERROR'} rows "
              f"(> their own {mine}) and gets both HR-only columns")

        hfil, _ = as_user(HRM, my_attendance.execute, dict(FLT, employee=OTHER))
        _, hfdata = hfil if hfil else (None, None)
        check("C7-HRFILT", hfdata is not None and data_fingerprint(hfdata) == fp_other,
              f"...and for HR the Employee filter IS honoured: {data_fingerprint(hfdata)} h "
              f"for {OTHER}, matching their {fp_other} — the same filter that was "
              f"ignored for the Employee")

        # ------------------------------------------------------------ C7-ZERO
        # Ingress writes 00:00:00 for "did not punch", never NULL — the trap
        # behind OD-49. Rendering it as "00:00" would have every employee
        # reporting a bug that is not one.
        blanks = [d for d in (data or []) if d["time_in"] == "" and d["out"] == ""]
        zeros = [d for d in (data or []) if "00:00" in (d["time_in"] or "")]
        check("C7-ZERO", not zeros,
              f"all-zero punches render EMPTY, not '00:00': {len(blanks)} punchless "
              f"row(s) shown blank, {len(zeros)} showing a fake midnight (must be 0)")

        # ------------------------------------------------------------ C7-JOIN
        # The status/leave verdict comes from Attendance, never from the log — FDR4.
        # Prove the join actually reaches it for HR.
        with_leave = [d for d in (hdata or []) if d.get("leave_type")]
        check("C7-JOIN", with_leave,
              f"the Attendance join works: {len(with_leave)} HR row(s) carry a leave_type, "
              f"e.g. {with_leave[0]['leave_type'] if with_leave else '—'} "
              f"(FDR4 — it comes from Attendance, never from the Finger Log)")

        # ------------------------------------------------------------ C7-DRAFT
        # 🔴 The leave days are exactly the days whose Finger Log is a DRAFT —
        # assert_no_clash refuses to let a log overwrite a leave-decided day. If
        # the report ever goes back to `docstatus = 1` this returns 0 and every
        # leave day silently disappears from the person's own record.
        drafts = frappe.db.count("Finger Log",
                                 {"docstatus": 0,
                                  "work_date": ("between", [FLT["from_date"],
                                                            FLT["to_date"]])})
        # ------------------------------------------------------------ C7-STATUS
        # 🔴 Added on MG's instruction. Without it a leave day rendered as a date
        # with every other field blank: the log is a DRAFT with all-zero punches,
        # and leave_type is HR-only, so the employee had nothing at all to explain
        # the row. `status` says WHAT was recorded without disclosing WHY.
        statuses = {d.get("status") for d in (data or [])}
        check("C7-STATUS", "status" in [c["fieldname"] for c in cols]
              and statuses - {""},
              f"the employee's own rows carry a status: {sorted(s for s in statuses if s)} "
              f"— the blank-punch rows are now legible without exposing leave_type")

        leave_rows = [d for d in (hdata or []) if d.get("leave_type")]
        check("C7-STATUS2", leave_rows and all(d.get("status") for d in leave_rows),
              f"and every leave row has one: "
              f"{sorted({d['status'] for d in leave_rows})} across {len(leave_rows)} row(s) "
              f"— previously these showed as an empty dated row")

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
