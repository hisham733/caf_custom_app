"""A late leave does THREE different things, and the day's current state decides.

    bench --site <site> execute caf.tests.chain.test_late_leave_shapes.run

🔴 WHY THIS EXISTS — the L2 climb, 2026-09-12
----------------------------------------------
MG's own monthly sequence: *"before or after unblock, submit a late leave
application."* Measured, the same MC on the same kind of day lands three ways,
and nothing warns HR which she is about to get:

    the day's Attendance            what the late leave does
    ────────────────────            ────────────────────────────────────────
    none (log still a DRAFT)        ✅ leave creates its OWN row,
                                       caf_finger_log EMPTY — FDR4 clean
    Absent (submitted, nobody came) 🔴 the SAME row is reconciled to On Leave
                                       and KEEPS caf_finger_log      = T-44
    Present (submitted, he worked)  ⛔ stock REFUSES it outright:
                                       AttendanceAlreadyMarkedError

⭐ The third was a surprise and is HR-facing (manual row **A20**): hrms'
`validate_attendance()` filters on `status in (Present, Work From Home)`, so only
an **Absent** day is silently taken over.

⚠️ A FIXTURE ABOUT LATE LEAVE MUST START FROM AN ABSENT DAY. The first version of
this used an ordinary worked day, stock refused the leave, and the T-44 rung could
not be built at all. That is recorded here because it will be the next person's
first mistake too.

🔴 LLS3 IS DELIBERATELY RED WHILE T-44 IS UNDECIDED. It asserts the CURRENT,
wrong shape so the register and the code agree about what is true today; when MG
decides to clear the link it flips, and the flip is the signal. Clearing the link
is a design decision about which source owns a day — not this suite's to take.
"""

import traceback

import frappe
from frappe.utils import strip_html

from caf.tests.chain import dataset

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<20}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _att(emp, date):
    return frappe.db.get_value(
        "Attendance", {"employee": emp, "attendance_date": date, "docstatus": 1},
        ["name", "status", "leave_type", "leave_application", "caf_finger_log"],
        as_dict=True)


def _try_leave(emp, date):
    try:
        return dataset._leave(emp, date), ""
    except Exception as e:
        frappe.db.rollback()
        return None, strip_html(str(e)).strip()


def _cleanup(emp, days):
    for date in days:
        for dt, field in (("Leave Application", "from_date"),
                          ("Attendance", "attendance_date"),
                          ("Finger Log", "work_date")):
            for r in frappe.get_all(dt, filters={"employee": emp, field: date},
                                    fields=["name", "docstatus"]):
                doc = frappe.get_doc(dt, r.name)
                if doc.docstatus == 1:
                    doc.flags.ignore_permissions = True
                    doc.flags.ignore_links = True
                    doc.flags.caf_skip_leave_guard = True
                    doc.cancel()
                frappe.delete_doc(dt, r.name, force=True, ignore_permissions=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    emp = dataset.employee("OLD", required=False)
    if not emp:
        print("SKIPPED — the cast does not resolve on this site (dataset.CAST)")
        return True
    if not frappe.db.exists("Leave Allocation",
                            {"employee": emp, "leave_type": dataset.LEAVE_TYPE,
                             "docstatus": 1}):
        print(f"SKIPPED — no submitted {dataset.LEAVE_TYPE} allocation for {emp}, "
              f"so no leave can be approved. A skip, not a pass.")
        return True

    days = dataset.free_workdays(emp, 3)
    draft_day, absent_day, present_day = days

    try:
        _cleanup(emp, days)

        # ── 1 · the log is still a DRAFT — the leave simply takes the day ───
        dataset._log(emp, draft_day)
        la, err = _try_leave(emp, draft_day)
        row = _att(emp, draft_day)
        check("LLS1-DRAFT-DAY",
              la and row and row.status == "On Leave"
              and row.leave_application == la.name and not row.caf_finger_log,
              f"over a DRAFT day the leave creates its OWN Attendance "
              f"({row and row.name}, caf_finger_log={row and row.caf_finger_log}) "
              f"— FDR4 clean, because no Finger Log ever decided the day"
              + (f". REFUSED: {err[:120]}" if err else ""))

        # ── 2 · the day is ABSENT — the same row is taken over ──────────────
        log = dataset._log(emp, absent_day, absent=True)
        log.submit()
        was = _att(emp, absent_day)
        la2, err = _try_leave(emp, absent_day)
        now = _att(emp, absent_day)
        live = frappe.db.count("Attendance", {"employee": emp,
                                              "attendance_date": absent_day,
                                              "docstatus": 1})
        check("LLS2-ABSENT-DAY",
              was and was.status == "Absent" and la2 and now
              and now.status == "On Leave" and now.name == was.name and live == 1,
              f"over an ABSENT day the leave is ACCEPTED and reconciles the SAME "
              f"row — {was and was.status} ➜ {now and now.status}, still "
              f"{now and now.name}, and exactly {live} live row. ⚠️ Not two rows: "
              f"the reconciliation itself is correct"
              + (f". REFUSED: {err[:120]}" if err else ""))

        check("LLS3-T44-LINK-KEPT",
              bool(now and now.leave_type and now.caf_finger_log),
              f"🔴 **T-44, ASSERTED AS IT IS TODAY, NOT AS IT SHOULD BE** — the row "
              f"carries leave_type={now and now.leave_type} AND "
              f"caf_finger_log={now and now.caf_finger_log}, so it claims two "
              f"sources and FDR4 says such rows must be 0. ⭐ **When MG decides to "
              f"clear the link this assertion FLIPS, and that flip is the signal "
              f"to retire it.** Until then the code and the register agree")

        # ── 3 · the day is PRESENT — stock refuses outright ────────────────
        worked = dataset._log(emp, present_day)
        worked.submit()
        # 🔴 COMMIT BEFORE PROVOKING THE REFUSAL. `_try_leave` rolls back on
        # failure, and on the first run that rollback also undid this submit —
        # so the day afterwards had no Attendance at all and the assertion read
        # as a product fault. A fixture must be durable before the thing being
        # tested is allowed to fail.
        frappe.db.commit()
        la3, err = _try_leave(emp, present_day)
        after = _att(emp, present_day)
        # ⚠️ `dataset.names_date` accepts EITHER form: stock formats the date for
        # the reader (`08-06-2026`), not in ISO, so an ISO-only check fails
        # against a perfectly good message. Two suites hit this in one hour,
        # which is why it is one shared predicate.
        named = dataset.names_date(err, present_day)
        check("LLS4-PRESENT-DAY-REFUSED",
              la3 is None and "already marked" in err.lower() and named
              and after and after.status == "Present",
              f"over a day he WORKED the leave is REFUSED by stock — "
              f"{err[:130]!r} — and the day is untouched ({after and after.status}). "
              f"⚠️ hrms `validate_attendance()` filters on Present / Work From "
              f"Home, which is why ONLY an Absent day is silently taken over")
        check("LLS4-REFUSAL-IS-BARE",
              la3 is None and not any(w in err.lower() for w in
                                      ("cancel", "instead", "correct")),
              f"⚠️ and the refusal offers NO remedy — it names the date and the "
              f"row and stops. Manual row A20 exists because HR meets this "
              f"whenever somebody brings an MC for a day they clocked in on")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        _cleanup(emp, days)

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
