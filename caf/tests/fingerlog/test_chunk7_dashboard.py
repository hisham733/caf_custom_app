"""Chunk 7.2 — the two panels OD-64 adds to the appraisal dashboard.

    bench --site <site> execute caf.tests.fingerlog.test_chunk7_dashboard.run

🔴 WHY A PANEL NEEDS A TEST AT ALL
----------------------------------
Both panels returned **0 rows** on first run and looked perfectly healthy doing
it — every suite cleans up after itself, so nothing that had ever been refreshed
still existed. A dashboard that finds nothing is indistinguishable from a
dashboard that cannot find anything, which is the §F2 trap wearing a new hat: a
count of zero is a red flag, not a result.

So this suite **makes** the thing it looks for — a submitted appraisal, then a
late MC that rewrites it — and only then asks the panel.

MG chose two of the three signals (OD-64): *refreshed after submit* and
`caf_hr_review`. The FBR39 window panel was dropped.

RE-RUNNABLE: artifacts are removed FIRST, and the fixture lives in **June**, the
month the importer never touched (§F4d).
"""

import frappe

from caf.caf.page.hr_appraisal_dashboard import hr_appraisal_dashboard as dash

# ⚠️ Chosen deliberately: 8am Schedule, used by no other suite, no appraisal in
# this cycle — and JOINED IN 2016. The first pick, HR-EMP-00213, joined
# 2026-08-03, and stock refuses an Attendance dated before an employee's joining
# date, so a June fixture was rejected outright. A fixture employee has to
# pre-date its own fixture.
EMP = "HR-EMP-00020"            # Chan Wai Khong
EMP_USER = "seriramulu@caffood.com"     # role Employee, NOT this employee
CYCLE = "2026-06"
TEMPLATE = "CAF Monthly Appraisal"
D_ABS = "2026-06-12"            # Friday. Not the 17th — AWAL MUHARRAM (§F1c)
# 🔴 UNCOUNTED, and the first version of this suite got it wrong. `MC` is in
# `caf_attendance_leave_codes`, so FBR37 counts it — and the day was already
# `Absent`, which FBR37's *other* branch also counts. Covering one counted state
# with another leaves the number exactly where it was, so
# `refresh_submitted_appraisal()` correctly wrote nothing and the panel correctly
# showed nothing. The test was asserting a refresh that should never have happened.
#
# `Annual` is NOT in the codes, so covering the Absent day REMOVES a counted day
# and the cell actually moves — which is the case the panel exists to surface.
UNCOUNTED_LEAVE = "Annual"

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def remove(doctype, name):
    if not frappe.db.exists(doctype, name):
        return
    doc = frappe.get_doc(doctype, name)
    doc.flags.ignore_links = True
    doc.flags.ignore_permissions = True
    if doc.docstatus == 1:
        doc.cancel()
    frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


def cleanup():
    """Scoped to this suite's ONE employee, ONE date and ONE cycle (§F4)."""
    for dt, field in (("Leave Application", "from_date"),
                      ("Attendance", "attendance_date"),
                      ("Finger Log", "work_date")):
        for r in frappe.get_all(dt, filters={"employee": EMP, field: D_ABS},
                                fields=["name"]):
            remove(dt, r.name)
    for r in frappe.get_all("Appraisal",
                            filters={"employee": EMP, "appraisal_cycle": CYCLE},
                            fields=["name"]):
        remove("Appraisal", r.name)
    frappe.db.commit()


def run():
    cleanup()
    try:
        # ------------------------------------------------------------ fixture
        log = frappe.new_doc("Finger Log")
        log.employee = EMP
        log.employee_name = frappe.db.get_value("Employee", EMP, "employee_name")
        log.work_date = D_ABS
        for f in ("time_in", "break", "resume", "out"):
            log.set(f, "00:00:00")          # punchless -> Absent, a counted day
        log.flags.ignore_permissions = True
        log.insert()
        log.submit()

        app = frappe.new_doc("Appraisal")
        app.employee = EMP
        app.appraisal_cycle = CYCLE
        app.appraisal_template = TEMPLATE
        app.flags.caf_skip_supervisor_check = True
        app.flags.ignore_permissions = True
        app.insert()
        app.flags.caf_skip_supervisor_check = True
        app.submit()
        app.db_set("workflow_state", "Completed", update_modified=False)
        frappe.db.commit()

        before = dash.get_refreshed_after_submit()
        mine_before = [r for r in before["rows"] if r["name"] == app.name]
        check("C72-FIX", app.docstatus == 1 and not mine_before,
              f"fixture: {app.name} is submitted and has NOT been refreshed yet, so "
              f"the panel does not list it ({len(mine_before)} rows). Without this "
              f"the assertion below could pass on a stale trail")

        # A late UNCOUNTED leave over the Absent day: the counted day disappears,
        # the submitted appraisal is rewritten, and OD-26's comment records it.
        la = frappe.new_doc("Leave Application")
        la.employee = EMP
        la.leave_type = UNCOUNTED_LEAVE
        la.from_date = la.to_date = D_ABS
        la.status = "Approved"
        la.company = frappe.db.get_value("Employee", EMP, "company")
        la.flags.ignore_permissions = True
        la.insert()
        la.submit()
        frappe.db.commit()

        # ------------------------------------------------------- C72-REFRESH 🔴
        after = dash.get_refreshed_after_submit()
        mine = [r for r in after["rows"] if r["name"] == app.name]
        row = mine[0] if mine else None
        check("C72-REFRESH", row and row["refresh_count"] >= 1 and row["detail"],
              f"a submitted appraisal that MOVED is now visible: "
              f"{app.name} x{row['refresh_count'] if row else 0} refresh(es), "
              f"last {row['last_refreshed'] if row else '—'}. "
              f"Monthly progress still counts it as done — this is the only place "
              f"that says the number changed underneath")

        check("C72-DETAIL", row and "OD-44" in (row["detail"] or "")
              and "➜" in (row["detail"] or ""),
              f"and it carries WHAT moved, not just that something did: "
              f"{str(row['detail'])[:130] if row else '—'}")

        # --------------------------------------------------------- C72-SCOPE 🔴
        # A supervisor may see their own subtree. This employee is not in the
        # Employee-role fixture's subtree, so their refreshed appraisal must be
        # absent — not merely un-rendered.
        frappe.set_user(EMP_USER)
        try:
            scoped = dash.get_refreshed_after_submit()
        finally:
            frappe.set_user("Administrator")
        leaked = [r for r in scoped["rows"] if r["name"] == app.name]
        check("C72-SCOPE", scoped["scope"] == "subtree" and not leaked,
              f"as {EMP_USER} the panel is scoped ({scoped['scope']}) and "
              f"{app.name} is ABSENT from the payload ({len(leaked)} leaks of "
              f"{len(scoped['rows'])} rows) — not hidden by the front end")

        # ------------------------------------------------------ C72-HRREVIEW
        log.reload()
        log.db_set("caf_hr_review", 1, update_modified=False)
        log.db_set("caf_hr_review_note", "CHUNK 7.2 TEST — OT lost its approval",
                   update_modified=False)
        frappe.db.commit()

        flags = dash.get_hr_review_flags()
        found = [r for r in flags["rows"] if r["name"] == log.name]
        check("C72-HRREVIEW", found and flags["total"] >= 1,
              f"a flagged Finger Log surfaces: {flags['total']} flagged in total, "
              f"and {log.name} is among them. Chunk 4 raises this flag instead of "
              f"throwing — a background re-resolve must not abort the batch (S3) — "
              f"so until now it went somewhere to be forgotten")

        # --------------------------------------------------------- C72-HRONLY
        frappe.set_user(EMP_USER)
        try:
            dash.get_hr_review_flags()
            refused = ""
        except Exception as e:
            refused = type(e).__name__
        finally:
            frappe.set_user("Administrator")
        check("C72-HRONLY", refused,
              f"and it is HR-only: {EMP_USER} gets {refused or '🔴 NOTHING — it let '
              f'them through'}. Finger Log is restricted to HR Manager and System "
              f"Manager (D40) and these rows carry OT figures")

        # ---------------------------------------------------------- C72-PAYLOAD
        payload = dash.get_dashboard()
        check("C72-PAYLOAD", "refreshed" in payload and "hr_review" in payload
              and "monthly" in payload,
              f"get_dashboard() still serves the page in one round trip: "
              f"{sorted(payload.keys())}")
    finally:
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    # ------------------------------------------------------------- C72-CLEAN
    left = (frappe.db.count("Finger Log", {"employee": EMP, "work_date": D_ABS})
            + frappe.db.count("Appraisal", {"employee": EMP,
                                            "appraisal_cycle": CYCLE})
            + frappe.db.count("Leave Application", {"employee": EMP,
                                                    "from_date": D_ABS}))
    check("C72-CLEAN", left == 0,
          f"the suite left {left} artifact(s) behind for {EMP} on {D_ABS} "
          f"— scoped to one employee, one date, one cycle (§F4)")

    print("\n=== Chunk 7.2 — refreshed-after-submit and caf_hr_review (OD-64) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:14s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    print(f"   session restored to: {frappe.session.user}")
    return not failed
