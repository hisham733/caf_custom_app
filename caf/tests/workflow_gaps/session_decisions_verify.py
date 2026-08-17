"""S10 companion — the D-13 closed-window row. bench execute only.

    bench --site <site> execute caf.tests.workflow_gaps.session_decisions_verify.run

The ps1 suite proves the OPEN-window side of the OT cascade refresh. This file
proves the CLOSED-window side: an appraisal submitted more than a month ago is
FINAL — the cascade still zeroes+flags the log, but the appraisal cell must NOT
move. `window_closed()` reads the Version log, so the fixture backdates its own
submit Version row (frappe.db.sql — the suite's own fixture, owner+date scoped).

Runs as Administrator (bench execute); the workflow bits use frappe.set_user.
"""

import frappe

EMP = "HR-EMP-00013"  # mohd - too@ is his real supervisor, so the appraisal walk is legit
CYCLE = "2026-06"
D_OT = "2026-06-29"   # Monday — the Sunday rule (get_work_hours returns 1h) would skew the OT check
OT_SHIFT = "8am Schedule"  # mohd's default (8:30am) has caf_allow_ot=0; an SA overrides for the day
RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def cleanup():
    for dt, filt in (
            ("Attendance", {"employee": EMP, "attendance_date": D_OT}),
            ("Finger Log", {"employee": EMP, "work_date": D_OT}),
            ("OT Approval", {"work_date": D_OT}),
            ("Shift Assignment", {"employee": EMP, "start_date": D_OT}),
            ("Appraisal", {"employee": EMP, "appraisal_cycle": CYCLE}),
            ("Leave Application", {"employee": EMP, "from_date": D_OT})):
        for r in frappe.get_all(dt, filters=filt, fields=["name", "docstatus"]):
            doc = frappe.get_doc(dt, r.name)
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            if doc.docstatus == 1:
                doc.reload()
                doc.cancel()
            frappe.delete_doc(dt, r.name, ignore_permissions=True, force=True)
    frappe.db.commit()


def cell(app_name, kra="OT Hours"):
    doc = frappe.get_doc("Appraisal", app_name)
    for row in doc.appraisal_kra:
        if row.kra == kra:
            return row.caf_date_cell or ""
    return None


def run():
    frappe.set_user("Administrator")
    cleanup()
    try:
        # --- appraisal: submitted, then its submit Version BACKDATED 60 days ---
        # Mirrors the API suites: SUP creates + submits, HRM approves. The insert
        # ignores permissions (the point under test is the FBR39 WINDOW, not
        # creation rights - EMP16's real manager has no API token).
        emp = frappe.get_doc("Employee", EMP)
        frappe.set_user("too@caffood.com")
        try:
            app = frappe.new_doc("Appraisal")
            app.employee = EMP
            app.appraisal_cycle = CYCLE
            app.appraisal_template = "CAF Monthly Appraisal"
            app.flags.ignore_permissions = True
            app.insert()
            from frappe.model.workflow import apply_workflow
            apply_workflow(app, "Submit for Review")
        finally:
            frappe.set_user("hr.manager.test@caffood.com")
        app = frappe.get_doc("Appraisal", app.name)
        app.flags.ignore_permissions = True
        from frappe.model.workflow import apply_workflow
        apply_workflow(app, "Approve")
        frappe.set_user("Administrator")

        app = frappe.get_doc("Appraisal", app.name)
        check("CW-SETUP", app.docstatus == 1,
              f"appraisal {app.name} submitted (ds={app.docstatus})")

        frappe.db.sql("""UPDATE `tabVersion` SET creation = DATE_SUB(NOW(), INTERVAL 60 DAY)
                          WHERE ref_doctype='Appraisal' AND docname=%s""", app.name)
        from caf.caf.appraisal_refresh import window_closed
        closed, _, deadline = window_closed(app.name)
        check("CW-WINDOW-CLOSED", closed,
              f"window_closed() sees the backdated submit (deadline {deadline})")

        app.refresh_auto_fill(force=True)
        app.flags.ignore_permissions = True
        app.flags.caf_system_write = True   # OD-61: the machine writing the cells
        app.save(ignore_permissions=True)

        # --- Shift Assignment: an OT-allowed shift for the day (OD-45) ---
        sa = frappe.new_doc("Shift Assignment")
        sa.employee = EMP
        sa.shift_type = OT_SHIFT
        sa.start_date = D_OT
        sa.end_date = D_OT
        sa.flags.ignore_permissions = True
        sa.insert()
        sa.submit()
        check("CW-SHIFT", sa.docstatus == 1,
              f"shift assignment {sa.name} ({OT_SHIFT}) live for {D_OT}")

        # --- OT approval + linked log on the same date ---
        ot = frappe.new_doc("OT Approval")
        ot.work_date = D_OT
        ot.type = "normal"
        ot.ot_department = emp.department
        ot.reason = "S10 CW fixture"
        ot.append("emp_list", {"work_date": D_OT, "emp_id": EMP, "emp_name": emp.employee_name,
                               "start_work": "08:00:00", "ot_end": "18:30:00", "ot_duration": 2.0})
        ot.flags.ignore_permissions = True
        ot.insert()
        ot.submit()

        log = frappe.new_doc("Finger Log")
        log.employee = EMP
        log.employee_name = emp.employee_name
        log.work_date = D_OT
        log.time_in, log.out = "08:00:00", "18:30:00"
        log.set("break", "12:30:00")
        log.resume = "13:30:00"
        log.overtime = 2
        log.flags.ignore_permissions = True
        log.insert()
        log.submit()
        check("CW-LINKED", log.final_ot == 2.0 and log.ot_approval_id == ot.name,
              f"log {log.name} linked: final_ot={log.final_ot} ot={log.ot_approval_id}")

        # The D-15 FL-submit refresh is UNGATED (corrections philosophy), so the
        # cell may already carry the OT - capture the baseline AFTER it, right
        # before the cancel. The CASCADE's refresh is the windowed one (D-13).
        app.reload()
        before = cell(app.name)

        # --- cancel the approval: cascade fires, refresh is window-gated ---
        ot.flags.ignore_permissions = True
        ot.cancel()
        log.reload()
        check("CW-CASCADE", log.final_ot == 0 and not log.ot_approval_id
              and log.caf_hr_review == 1,
              f"cascade zeroed+flagged: final_ot={log.final_ot} flag={log.caf_hr_review}")

        app.reload()
        after = cell(app.name)
        check("CW-CELL-UNCHANGED", before == after,
              f"closed-window appraisal cell UNCHANGED: '{before}' -> '{after}' (D-13)")
    finally:
        frappe.set_user("Administrator")
        cleanup()

    print("\n=== S10 companion - D-13 closed window ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:16s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
