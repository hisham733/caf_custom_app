"""An OT Approval must reach the days it covers. T-48, built 2026-09-13.

    bench --site <site> execute caf.tests.chain.test_ot_approval_reaches_days.run

🔴 WHY THIS EXISTS — MG's side quest, and it came back worse than the bug
--------------------------------------------------------------------------
*"check if this workflow is feasible: FL submitted with an OT_approval, then weeks
later HR submits OT_approval (type = special) with more OT / less OT."*

**It was feasible and it broke.** The log kept the number it was submitted with,
still pointing at the approval row FBR71 had just cancelled, with no flag anywhere
— while the approvals in force said something else. **1.5 hours would have been
paid that nobody approved.**

The cause was one missing wire: `Leave Application`, `Shift Assignment` and
`Finger Log` all reach back into the days they affect; **`OT Approval` had no
`doc_events` entry at all.**

WHAT EACH ASSERTION PROTECTS
-----------------------------
    OAR1  a later SPECIAL for FEWER hours flags the day, naming BOTH figures
    OAR2  …and for MORE hours too — the fix is not one-directional
    OAR3  🔴 `final_ot` is NOT rewritten. A number somebody is paid must not
          change behind a submitted document — the fix puts it in front of a
          person, it does not quietly re-pay the day
    OAR4  CANCELLING an approval flags the day as well
    OAR5  an approval that still AGREES flags nothing. Without this the suite
          would pass against a system that flags everything, which is the same
          as flagging nothing

⚠️ Self-cleaning: builds its own day and removes it in `finally`.
"""

import traceback

import frappe

from caf.tests.chain import dataset

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<26}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _state(name):
    return frappe.db.get_value(
        "Finger Log", name,
        ["final_ot", "ot_approval_id", "caf_hr_review", "caf_hr_review_note"],
        as_dict=True)


def _clear_flag(name):
    doc = frappe.get_doc("Finger Log", name)
    doc.db_set("caf_hr_review", 0, update_modified=False)
    doc.db_set("caf_hr_review_note", "", update_modified=False)


def _cleanup(emp, day):
    for r in frappe.get_all("Finger Log",
                            filters={"employee": emp, "work_date": day},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Finger Log", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            doc.cancel()
        frappe.delete_doc("Finger Log", r.name, force=True, ignore_permissions=True)
    for r in frappe.get_all("Attendance",
                            filters={"employee": emp, "attendance_date": day},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Attendance", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.flags.caf_skip_leave_guard = True
            doc.cancel()
        frappe.delete_doc("Attendance", r.name, force=True, ignore_permissions=True)
    for r in dataset._ot_approvals(emp, [day]):
        doc = frappe.get_doc("OT Approval", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("OT Approval", r.name, force=True, ignore_permissions=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    emp = dataset.employee("OLD", required=False)
    if not emp:
        print("SKIPPED — the cast does not resolve on this site (dataset.CAST)")
        return True

    day = dataset.free_workdays(emp, 1)[0]

    try:
        _cleanup(emp, day)

        log = dataset._log(emp, day, ot=dataset.OT_CLOCKED)      # 2.30 -> 2.5
        normal = dataset._approval(emp, day, 3.0)                # covers it
        log.reload()
        log.submit()
        frappe.db.commit()
        start = _state(log.name)

        # ── OAR5 first — a MATCHING approval must flag nothing ─────────────
        _clear_flag(log.name)
        agree = dataset._approval(emp, day, 2.5, kind="special_approve")
        frappe.db.commit()
        after_agree = _state(log.name)
        check("OAR5-AGREEMENT-IS-QUIET", after_agree.caf_hr_review == 0,
              f"a later approval that lands on the SAME figure "
              f"({after_agree.final_ot}) flags nothing. ⚠️ Without this the suite "
              f"would pass against a system that flags every approval, which "
              f"tells HR exactly as much as flagging none")

        # ── OAR1 — a later special for FEWER hours ─────────────────────────
        _clear_flag(log.name)
        dataset._approval(emp, day, 1.0, kind="special_approve")
        frappe.db.commit()
        less = _state(log.name)
        note = frappe.utils.strip_html(less.caf_hr_review_note or "")
        check("OAR1-LESS-IS-FLAGGED",
              less.caf_hr_review == 1 and "2.5" in note and "1.0" in note,
              f"🔴 **THE HOLE MG FOUND.** A special approval for 1.0 h filed after "
              f"the log was submitted now FLAGS it, and the note carries both "
              f"figures — {note[:130]!r}. Before this, the log kept 2.5 h "
              f"pointing at a row FBR71 had just cancelled, with nothing said "
              f"anywhere: 1.5 hours paid that nobody approved")

        check("OAR3-FINAL-OT-NOT-REWRITTEN",
              float(less.final_ot or 0) == float(start.final_ot or 0),
              f"⭐ …and `final_ot` is UNCHANGED at {less.final_ot}. **A number "
              f"somebody is paid must not move behind a submitted document.** The "
              f"fix puts the day in front of a person — it does not quietly "
              f"re-pay it, which would be the same silence in the other direction")

        # ── OAR2 — and for MORE hours ──────────────────────────────────────
        _clear_flag(log.name)
        dataset._approval(emp, day, 4.0, kind="special_approve")
        frappe.db.commit()
        more = _state(log.name)
        check("OAR2-MORE-IS-FLAGGED", more.caf_hr_review == 1,
              f"a special for MORE hours flags it too — the comparison asks "
              f"whether the stored figure still MATCHES, not whether it is too "
              f"big. An under-payment is somebody's money as much as an "
              f"over-payment is")

        # ── OAR4 — cancelling an approval ──────────────────────────────────
        _clear_flag(log.name)
        doc = frappe.get_doc("OT Approval", normal.name)
        doc.flags.ignore_permissions = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.db.commit()
        cancelled = _state(log.name)
        check("OAR4-CANCEL-IS-FLAGGED", cancelled.caf_hr_review == 1,
              f"withdrawing an approval flags the day as well "
              f"(caf_hr_review={cancelled.caf_hr_review}). An approval taken away "
              f"changes what is authorised exactly as much as one added, and the "
              f"cancel path had the same silence as the submit path")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        _cleanup(emp, day)

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
