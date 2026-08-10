"""One test per DECISION logged for Chunk 3 — MG, 2026-08-10.

    bench --site <site> execute caf.tests.fingerlog.test_chunk3_decisions.run

WHY PYTHON AND NOT .ps1 LIKE THE APPRAISAL SUITE
------------------------------------------------
The appraisal suite is PowerShell because **permissions** are its axis, and a
permission test must run as a real role over the REST API. Chunk 3's decisions
are server logic — an arithmetic formula, a submit guard, a controller hook —
where the API adds a layer of quoting between the test and the thing tested.
The lifecycle assertions here still exercise the real document lifecycle
(`insert` → `submit` → `cancel`), just without the HTTP round trip.
`run_chunk3.ps1` wraps this so it runs like the rest of the suite.

RE-RUNNABLE: every artifact is removed FIRST, not last.
"""

import frappe
from frappe.utils import getdate

from caf.caf import work_hours
from caf.caf.shift_resolution import get_shift_params

# fixtures
EMP_OT = "HR-EMP-00016"       # 8am Schedule  08:00-16:30, lunch 60 -> net 7.5h
EMP_NOLUNCH = "HR-EMP-00001"  # special       09:00-18:00, lunch 0  -> net 9.0h
EMP_MONFRI = "HR-EMP-00127"   # 8am no OT no Sat - Saturday is a REST day
D = "2026-10-%02d"            # October 2026: past the seeded OT Approvals

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def remove(doctype, name):
    """Cancel-then-delete. A submitted row cannot be deleted, and a test that
    forgets this fails on its own leftovers rather than on anything real."""
    if not frappe.db.exists(doctype, name):
        return
    doc = frappe.get_doc(doctype, name)
    doc.flags.ignore_links = True
    doc.flags.ignore_permissions = True
    if doc.docstatus == 1:
        doc.cancel()
    frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


def cleanup():
    # 🔴 SCOPED TO OCTOBER — this suite's own month (D = "2026-10-%02d").
    #
    # It used to purge by EMPLOYEE ALONE, and that quietly deleted every imported
    # Finger Log belonging to these three: 62 rows of real July data per run,
    # while the suite reported 21/21 green. Caught 2026-08-11 by the canary in
    # `test_chunk_t.run_all`, which counts the imported month before and after.
    #
    # This is the SAME mistake already written up for the Chunk 2b suite, which
    # ate ~50 rows the same way. Documenting it there did not stop it recurring
    # here — hence the canary, which does.
    for emp in (EMP_OT, EMP_NOLUNCH, EMP_MONFRI):
        for f in frappe.get_all("Finger Log",
                                filters={"employee": emp,
                                         "work_date": ("between",
                                                       ["2026-10-01", "2026-10-31"])},
                                fields=["name"], limit_page_length=0):
            for a in frappe.get_all("Attendance", filters={"caf_finger_log": f.name},
                                    fields=["name"]):
                remove("Attendance", a.name)
            remove("Finger Log", f.name)
    frappe.db.commit()


def make(emp, day, **punches):
    doc = frappe.new_doc("Finger Log")
    doc.employee = emp
    doc.employee_name = frappe.db.get_value("Employee", emp, "employee_name")
    doc.work_date = day
    doc.overtime = punches.pop("overtime", 0)
    for k in ("time_in", "break", "resume", "out"):
        doc.set(k, punches.get(k, "00:00:00"))
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


def run():
    cleanup()

    # ---------------------------------------------------------------- OD-57
    meta = frappe.get_meta("Finger Log", cached=False)
    f = meta.get_field("caf_work_hours")
    check("OD-57", f is not None and f.read_only == 1,
          f"caf_work_hours exists={f is not None} read_only={getattr(f, 'read_only', None)}")

    # ---------------------------------------------------------------- OD-51
    gone = [n for n in ("approval", "department") if meta.get_field(n)]
    kept = meta.get_field("leave_taken") is not None
    check("OD-51", not gone and kept,
          f"dropped approval+department (still present: {gone or 'none'}); leave_taken kept={kept}")

    cols = {r[0] for r in frappe.db.sql(
        "select COLUMN_NAME from information_schema.columns "
        "where table_schema=database() and table_name='tabFinger Log'")}
    check("OD-51b", not ({"approval", "department", "work"} & cols),
          f"orphan columns dropped too: {sorted({'approval','department','work'} & cols) or 'none'}")

    # ---------------------------------------------------------------- OD-59
    p = get_shift_params("8am Schedule")            # 08:00-16:30 lunch 60 -> net 450m
    net = work_hours.net_minutes(p)
    w, s = work_hours.compute("08:00:00", "12:00:00", "13:00:00", "16:30:00", p)
    check("OD-59a", net == 450 and w == 7.5 and s == 0.0,
          f"exact shift: net={net}m work={w} short={s}")

    # early in / late out must NOT inflate work - that is overtime, not work
    w2, _ = work_hours.compute("06:00:00", "12:00:00", "13:00:00", "19:00:00", p)
    check("OD-59b", w2 == 7.5,
          f"clamped to the shift window: 06:00-19:00 -> work={w2} (must stay 7.5, the rest is OT)")

    # a longer actual lunch is deducted as taken
    w3, _ = work_hours.compute("08:00:00", "12:00:00", "13:30:00", "16:30:00", p)
    check("OD-59c", w3 == 7.0, f"90-min actual lunch -> work={w3} (expect 7.0)")

    # cross-midnight - FBR28
    w4, _ = work_hours.compute("08:00:00", "12:00:00", "13:00:00", "00:30:00", p)
    check("OD-59d", w4 == 7.5, f"out after midnight -> work={w4} (must not go negative)")

    # the invariant, on every submitted row
    bad = 0
    for r in frappe.get_all("Finger Log",
                            filters={"docstatus": 1, "caf_not_full_day": 0, "day_type": "Workday"},
                            fields=["shift_type", "caf_work_hours", "short"],
                            limit_page_length=0):
        n = work_hours.net_minutes(get_shift_params(r.shift_type))
        if abs(round((r.caf_work_hours + r.short) * 60) - n) > 1:
            bad += 1
    check("OD-59e", bad == 0, f"work + short == net on every submitted workday row: {bad} failures")

    # ---------------------------------------------------------------- OD-58
    doc = make(EMP_OT, D % 5, time_in="08:00:00", **{"break": "12:00:00"})
    refused = False
    try:
        doc.submit()
    except frappe.ValidationError:
        refused = True
    # Assert the STORED docstatus, never the in-memory one: Frappe sets
    # self.docstatus = 1 before before_submit runs, so the object says
    # "submitted" even when the guard refused it. Only the database is truth.
    stored = frappe.db.get_value("Finger Log", doc.name, "docstatus")
    check("OD-58a", doc.caf_not_full_day == 1 and refused and stored == 0,
          f"in + lunch_out, no out -> not_full_day={doc.caf_not_full_day} "
          f"refused={refused} stored docstatus={stored} (must be 0)")

    # the ABSENT row is EXEMPT - complete by absence
    doc = make(EMP_OT, D % 6)
    doc.submit()
    att = frappe.get_all("Attendance", filters={"caf_finger_log": doc.name},
                         fields=["status", "leave_type"])
    check("OD-58b", doc.caf_not_full_day == 0 and doc.docstatus == 1
          and att and att[0].status == "Absent",
          f"all-zero row submits: not_full_day={doc.caf_not_full_day} "
          f"status={att[0].status if att else None}")

    # a shift with NO lunch must not demand a lunch pair
    pn = get_shift_params("special")
    check("OD-58c", work_hours.required_punches(pn) == ("time_in", "out")
          and work_hours.required_punches(p) == ("time_in", "break", "resume", "out"),
          f"required punches per shift: no-lunch={work_hours.required_punches(pn)} "
          f"with-lunch={work_hours.required_punches(p)}")

    # ---------------------------------------------------------------- OD-56
    # the half-day SHAPE must never produce a Half Day
    half = make(EMP_OT, D % 7, time_in="08:00:00", **{"break": "12:00:00"})
    made_half = frappe.db.count("Attendance", {"caf_finger_log": half.name})
    check("OD-56", half.caf_not_full_day == 1 and made_half == 0,
          f"half-day shape -> Not Full Day, NOT Half Day; attendance rows created={made_half}")

    # ---------------------------------------------------------------- REST
    # 🔴 A REST DAY IS NOT AN ABSENCE. The creation path had no day_type check
    # while the re-resolve did, and the two disagreeing produced 287 false
    # Absents in a single month - every one a Sunday, and every one countable
    # against the employee under FBR37.
    sat = D % 10                                   # 2026-10-10 is a Saturday
    for old in frappe.get_all("Finger Log",
                              filters={"employee": EMP_MONFRI, "work_date": sat},
                              fields=["name"]):
        remove("Finger Log", old.name)
    rest = make(EMP_MONFRI, sat)                   # all-zero, and a no-Saturday shift
    rest.submit()
    made = frappe.db.count("Attendance", {"caf_finger_log": rest.name})
    check("REST", rest.day_type == "Restday" and made == 0,
          f"all-zero on a {rest.day_type}: Attendance rows created={made} (must be 0 - "
          f"he was never scheduled)")

    # but if he DID punch on a rest day, that is real attendance
    for old in frappe.get_all("Finger Log",
                              filters={"employee": EMP_MONFRI, "work_date": sat},
                              fields=["name"]):
        for a in frappe.get_all("Attendance", filters={"caf_finger_log": old.name},
                                fields=["name"]):
            remove("Attendance", a.name)
        remove("Finger Log", old.name)
    worked = make(EMP_MONFRI, sat, time_in="08:00:00", out="16:30:00",
                  **{"break": "12:00:00", "resume": "13:00:00"})
    worked.submit()
    att_r = frappe.get_all("Attendance", filters={"caf_finger_log": worked.name},
                           fields=["status"])
    check("REST2", worked.day_type == "Restday" and att_r and att_r[0].status == "Present",
          f"punched on a {worked.day_type} -> {att_r[0].status if att_r else None} "
          f"(he turned up; FBR4 makes every hour OT)")

    # ---------------------------------------------------------------- FBR37
    # The appraisal counts ATTENDANCE now, not Finger Log.leave_taken (OD-43).
    from caf.caf.overrides.appraisal import get_upl_dates
    codes = frappe.db.get_single_value("HR Settings", "caf_attendance_leave_codes") or ""
    counted = [c.strip() for c in codes.split(",") if c.strip()]
    probes = []
    for status, lt, expect in (("On Leave", "MC", True),
                               ("On Leave", "Annual", False),
                               ("Absent", None, True)):
        row = frappe.get_all("Attendance",
                             filters={"docstatus": 1, "status": status,
                                      "leave_type": lt or ("is", "not set")},
                             fields=["employee", "attendance_date"], limit=1)
        if not row:
            continue
        cell = get_upl_dates(row[0].employee, row[0].attendance_date,
                             row[0].attendance_date)
        probes.append((f"{status}/{lt or 'none'}", bool(cell), expect))
    check("FBR37", probes and all(got == exp for _, got, exp in probes),
          "counts authorised leave AND unexplained absence, ignores the rest: "
          + "; ".join(f"{n} counted={g} expected={e}" for n, g, e in probes)
          + f"   [list: {counted}]")

    # ---------------------------------------------------------------- FDR4
    leaked = frappe.db.sql("""select count(*) from tabAttendance
                              where ifnull(caf_finger_log,'')<>'' and ifnull(leave_type,'')<>''""")[0][0]
    check("FDR4", leaked == 0,
          f"Attendance rows created by Finger Log carrying a leave_type: {leaked} (must be 0)")

    # ---------------------------------------------------------------- OD-45
    fl = make(EMP_OT, D % 8, time_in="08:00:00", **{"break": "12:00:00",
                                                    "resume": "13:00:00", "out": "16:30:00"})
    check("OD-45", fl.day_type in ("Workday", "Restday", "Holiday") and fl.shift_type,
          f"day_type/shift_type derived, never imported: {fl.day_type} / {fl.shift_type}")

    # ---------------------------------------------------------------- verdict + link
    fl.submit()
    att = frappe.get_all("Attendance", filters={"caf_finger_log": fl.name},
                         fields=["name", "status", "leave_type", "shift"])
    check("VERDICT", att and att[0].status == "Present" and not att[0].leave_type,
          f"punched workday -> {att[0].status if att else None}, "
          f"leave_type={att[0].leave_type if att else None}")

    # ---------------------------------------------------------------- cancel cascade
    fl.reload()
    fl.flags.ignore_permissions = True
    fl.cancel()
    after = frappe.db.get_value("Attendance", att[0].name, "docstatus")
    check("CANCEL", fl.docstatus == 2 and after == 2,
          f"cancelling the log cancels the Attendance (never deletes): log={fl.docstatus} att={after}")

    # ---------------------------------------------------------------- collision
    leave = frappe.get_all("Leave Application",
                           filters={"docstatus": 1, "status": "Approved"},
                           fields=["employee", "from_date"], limit=1)
    if leave:
        for old in frappe.get_all("Finger Log",
                                  filters={"employee": leave[0].employee,
                                           "work_date": leave[0].from_date},
                                  fields=["name"]):
            d = frappe.get_doc("Finger Log", old.name)
            d.flags.ignore_links = True
            if d.docstatus == 1:
                d.cancel()
            frappe.delete_doc("Finger Log", old.name, ignore_permissions=True, force=True)
        clash = make(leave[0].employee, leave[0].from_date,
                     time_in="08:00:00", **{"break": "12:00:00",
                                            "resume": "13:00:00", "out": "16:30:00"})
        threw = False
        try:
            clash.submit()
        except frappe.ValidationError:
            threw = True
        stored = frappe.db.get_value("Finger Log", clash.name, "docstatus")
        # The STORED docstatus is what matters: a refusal that still leaves the
        # row submitted is not a refusal. That is exactly what happened while the
        # check lived in on_submit.
        check("COLLIDE", threw and stored == 0,
              f"approved leave on the date -> refused={threw}, stored docstatus={stored} (must be 0)")
        remove("Finger Log", clash.name)
    else:
        check("COLLIDE", False, "no approved Leave Application on dev to test against")

    cleanup()
    # 🔴 This used to assert `count(employee=EMP_OT) == 0` — that the employee had
    # NO Finger Logs anywhere. It passed only because cleanup was deleting their
    # imported July rows too, so the assertion was encoding the bug rather than
    # catching it. Scope it to the suite's own month, and assert the imported data
    # is still there.
    left = frappe.db.count("Finger Log", {"employee": EMP_OT,
                                          "work_date": ("between",
                                                        ["2026-10-01", "2026-10-31"])})
    imported = frappe.db.count("Finger Log", {"employee": EMP_OT,
                                              "work_date": ("between",
                                                            ["2026-07-01", "2026-07-31"])})
    check("CLEAN", left == 0 and imported > 0,
          f"fixtures removed ({left} left in October) and the imported month is "
          f"UNTOUCHED ({imported} July rows still present)")

    frappe.db.commit()

    print("\n=== Chunk 3 — one test per logged decision ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:9s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
