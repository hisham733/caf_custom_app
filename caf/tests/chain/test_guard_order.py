"""The ORDER the Finger Log guards fire in. T-45, codified from the L1 climb.

    bench --site <site> execute caf.tests.chain.test_guard_order.run

🔴 WHY THIS EXISTS, AND WHY THE ORDER IS THE POINT
---------------------------------------------------
Every guard is tested where it lives. **None of those suites can see the order**,
because each builds a day with exactly one thing wrong. HR meets a day with
several things wrong and is shown **exactly one message** — and the first one is
the only one she can act on.

Measured in a browser 2026-09-12 (`playbooks/L1_submit_ladder.md`), on one day
carrying all four faults at once:

    1  "Overtime has no approval"             <- validate()
    2  "Not a full day"                       <- before_submit(), controller
    3  "The day is already decided by leave"  <- before_submit(), assert_no_clash
    4  "Month not confirmed"                  <- before_submit(), doc_event
    5  submits -> Attendance

🔴 **That REVERSED the sketch this project worked from for a day.** The mechanism
is Frappe's: `validate()` runs before `before_submit()`, and `doc_events` run
after the controller's own method of the same name (`hooks.py:654`). Nothing
declares the resulting order anywhere, so a plausible refactor — moving the OT
check into `before_submit`, say — would silently reorder what HR is told and
would make manual row **A18** wrong, with every per-guard suite still green.

WHAT IS ASSERTED, AND WHAT DELIBERATELY IS NOT
-----------------------------------------------
Asserted: **which guard speaks, and in what order**, plus the FACTS each refusal
carries — never its wording (`test_ot_messages` is the shape: reword freely, drop
a fact and this goes red).

⚠️ Not asserted: dialog titles and anything about how the desk renders them. Those
were measured in the browser and belong to the playbook.

⚠️ IT ARMS THE ROSTER GATE onto its own month — this is the one suite that must
NOT suspend it, because rung 4 IS the gate. Restored by MEANING in the `finally`,
and the restore is ASSERTED (a cleared Date on a Single reads back as
`0001-01-01`, which is a gate that refuses every Finger Log ever recorded).
"""

import traceback

import frappe
from frappe.utils import strip_html

from caf.tests import roster_gate
from caf.tests.chain import dataset

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<20}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _submit(name):
    """Try to submit. Returns the refusal as plain text, or '' if it went through."""
    doc = frappe.get_doc("Finger Log", name)
    doc.flags.ignore_permissions = True
    try:
        doc.submit()
        return ""
    except Exception as e:
        frappe.db.rollback()
        return strip_html(str(e)).strip()


def _facts(msg, *needles):
    return {str(n): (str(n) in msg) for n in needles}


def _cleanup(emp, day, month_start):
    for dt, field in (("Leave Application", "from_date"),
                      ("Attendance", "attendance_date"),
                      ("Finger Log", "work_date")):
        for r in frappe.get_all(dt, filters={"employee": emp, field: day},
                                fields=["name", "docstatus"]):
            doc = frappe.get_doc(dt, r.name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.flags.ignore_links = True
                doc.flags.caf_skip_leave_guard = True
                doc.cancel()
            frappe.delete_doc(dt, r.name, force=True, ignore_permissions=True)
    for r in dataset._ot_approvals(emp, [day]):
        doc = frappe.get_doc("OT Approval", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("OT Approval", r.name, force=True,
                          ignore_permissions=True)
    for r in frappe.get_all("Monthly Roster Confirmation",
                            filters={"month_start": month_start},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Monthly Roster Confirmation", r.name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Monthly Roster Confirmation", r.name, force=True,
                          ignore_permissions=True)
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
        print(f"SKIPPED — {emp} holds no submitted {dataset.LEAVE_TYPE} "
              f"allocation, so rung 3 cannot be built and the ORDER cannot be "
              f"shown. This is a skip, not a pass.")
        return True

    day = dataset.free_workdays(emp, 1)[0]
    month_start = day[:8] + "01"
    before_gate = None

    try:
        _cleanup(emp, day, month_start)

        # Every fault at once. The order they are CREATED in is irrelevant; the
        # order the guards FIRE in is the whole question.
        dataset._leave(emp, day)
        log = dataset._log(emp, day, ot=dataset.OT_CLOCKED, missing_punch=True)

        # 🔴 READ THE OLD VALUE FIRST. `roster_gate._set()` returns the value it
        # has just WRITTEN, not the one it replaced — and taking its return as the
        # snapshot left this site's live gate sitting at June instead of
        # 2026-09-01 on the very first run of this suite. Measured and repaired
        # the same minute; the lesson is that a restore is only as good as what
        # the snapshot actually captured.
        from caf.caf.doctype.monthly_roster_confirmation \
            import monthly_roster_confirmation as mrc
        before_gate = mrc.gate_from()
        roster_gate._set(month_start)                        # the gate is a RUNG
        frappe.db.commit()

        who = frappe.db.get_value("Employee", emp, "employee_name")

        # ── 1 · overtime, from validate() ──────────────────────────────────
        msg = _submit(log.name)
        f = _facts(msg, who, day, log.ot_in_hour)
        check("ORD1-OT-FIRST",
              "overtime" in msg.lower() and "approval" in msg.lower()
              and all(f.values()),
              f"the FIRST refusal on a day that is ALSO held, ALSO leave-covered "
              f"and in an unconfirmed month is the OVERTIME one, carrying "
              f"{f}. 🔴 This reversed the project's own sketch: `validate()` runs "
              f"before `before_submit()`, so OT is judged first")

        # ── 2 · not a full day, from before_submit() ───────────────────────
        dataset._approval(emp, day, 3.0)
        frappe.db.commit()
        msg = _submit(log.name)
        check("ORD2-HELD-SECOND",
              "not a full day" in msg.lower() and str(day) in msg,
              f"once the overtime is approved the next refusal is OD-58's "
              f"incomplete-punch guard, naming the date — {msg[:90]!r}. ⚠️ It "
              f"cannot name WHICH punch (T-45 finding F1): `_missing` is set in a "
              f"branch `validate()` skips on the submit path")

        # ── 3 · the leave clash, still before_submit() ─────────────────────
        fix = frappe.get_doc("Finger Log", log.name)
        fix.resume = "13:00:00"
        fix.flags.ignore_permissions = True
        fix.save(ignore_permissions=True)
        frappe.db.commit()
        msg = _submit(log.name)
        la = frappe.db.get_value("Leave Application",
                                 {"employee": emp, "from_date": day,
                                  "docstatus": 1}, "name")
        f = _facts(msg, who, day, dataset.LEAVE_TYPE, la)
        # ⚠️ Match on the BODY, not the title. `frappe.throw(..., title=...)`
        # puts the title on the dialog and `str(e)` returns only the message —
        # so asserting "decided by leave" (the title) failed against a refusal
        # that was working perfectly. Caught on the first run of this suite.
        check("ORD3-LEAVE-THIRD",
              "approved leave" in msg.lower()
              and "may not overwrite" in msg.lower() and all(f.values()),
              f"third: the approved absence, naming the person, the date, the "
              f"leave TYPE and the APPLICATION {f}, and saying a Finger Log may "
              f"not overwrite an approved absence. Both the employee and the "
              f"leave are links in the rendered message")

        # ── 4 · the roster gate, a doc_event — so it is LAST ───────────────
        leave = frappe.get_doc("Leave Application", la)
        leave.flags.ignore_permissions = True
        leave.cancel()
        frappe.db.commit()
        msg = _submit(log.name)
        check("ORD4-GATE-LAST",
              "roster" in msg.lower() and "confirmed" in msg.lower(),
              f"LAST: the roster gate — {msg[:110]!r}. ⭐ It is last because it is "
              f"a `doc_events` hook and those run AFTER the controller's own "
              f"`before_submit` (hooks.py:654). A day with unapproved overtime "
              f"never reaches it, which is how that ordering was first found — by "
              f"tripping over it")

        # ── 5 · and then it goes through ───────────────────────────────────
        roster = frappe.new_doc("Monthly Roster Confirmation")
        roster.month_start = month_start
        roster.no_new_holidays = 1
        roster.flags.ignore_permissions = True
        roster.insert(ignore_permissions=True)
        roster.submit()
        frappe.db.commit()
        msg = _submit(log.name)
        att = frappe.db.get_value(
            "Attendance", {"employee": emp, "attendance_date": day,
                           "docstatus": 1},
            ["name", "status", "caf_finger_log"], as_dict=True)
        doc = frappe.get_doc("Finger Log", log.name)
        check("ORD5-SUBMITS",
              msg == "" and doc.docstatus == 1 and att
              and att.caf_finger_log == log.name,
              f"with every rung cleared the log SUBMITS and writes its Attendance "
              f"({att and att.name}, {att and att.status}). ⚠️ The positive case "
              f"matters: four refusals prove nothing if the fifth state cannot be "
              f"reached")
        check("ORD5-FINAL-OT", float(doc.final_ot or 0) == float(doc.ot_in_hour or 0),
              f"and the overtime survived the whole climb unchanged — final_ot "
              f"{doc.final_ot} against a clocked {doc.ot_in_hour}. A day that was "
              f"refused four times must not arrive with a different number")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        try:
            _cleanup(emp, day, month_start)
        finally:
            if before_gate is not None or True:
                roster_gate._set(before_gate)
                ok, detail = roster_gate.restored(before_gate)
                check("ORD-GATE-RESTORE", ok, detail)

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
