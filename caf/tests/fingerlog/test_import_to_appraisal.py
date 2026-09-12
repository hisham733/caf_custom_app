"""Import ➜ submit ➜ late leave ➜ appraisal — the chain, end to end.

    bench --site <site> execute caf.tests.fingerlog.test_import_to_appraisal.run
    bench --site <site> execute caf.tests.fingerlog.test_import_to_appraisal.cleanup

🔴 WHY THIS EXISTS — MG, 2026-09-12
-----------------------------------
616 Finger Logs were imported for 10-16 August to prove the Ingress batch path
works. MG's question was the right one:

    "after importing these 616, did you complete the full suite test?
     - unblock some with HR manager role
     - before or after unblock, submit a late leave application
     - before or after unblock, then submit an appraisal of the same or
       previous month"

The honest answer was no. The per-doctype suites all passed, but **nothing
walked the chain** — and the chain is where CAF's rules actually meet each
other. Each link is covered somewhere; the JOINS between them were not.

WHAT IT ASSERTS, AND WHY EACH LINK MATTERS
------------------------------------------
    IMP1  a freshly imported draft SUBMITS, and writes Attendance
          (the roster gate only bites from `caf_roster_gate_from`, so an
           August date must pass freely — a gate that blocked everything
           would look identical to a gate that works)

    IMP2  a LATE leave over a day whose log is still a DRAFT
    IMP3  a LATE leave over a day whose log is already SUBMITTED
          🔴 MG asked specifically about "before or after unblock". These are
          the two orders, and they are not obviously the same: one has an
          Attendance row to reconcile and the other does not.

    IMP4  an appraisal for that month reads the imported data
    IMP5  a leave filed AFTER that appraisal is submitted REFRESHES it
          (OD-44/FBR39's in-window path — the one that silently does nothing
           if a hook is unwired)

⚠️ IT MUTATES REAL DATA and does not put it back. That is deliberate: the
window it works in is test data imported for this purpose, and unpicking a
submitted Attendance chain surgically is more likely to leave a mess than to
clean one. **Run `cleanup()` when finished** — it removes the whole window.

⚠️ SKIPS CLEANLY when there is nothing to work with (no drafts in the window),
so it is safe in the battery on a site that never imported them.
"""

import frappe
from frappe.utils import getdate

WINDOW = ("2026-08-10", "2026-08-16")
CYCLE = "2026-08"
LEAVE_TYPE = "MC"

_results = []


def check(tid, ok, detail):
    _results.append((tid, bool(ok), detail))
    print("%-10s %-5s %s" % (tid, "PASS" if ok else "FAIL", detail))
    return ok


def skip(tid, detail):
    _results.append((tid, True, "SKIPPED — " + detail))
    print("%-10s %-5s SKIPPED — %s" % (tid, "PASS", detail))


def _drafts(employee=None, submittable_only=True):
    """Workday drafts in the window.

    🔴 `submittable_only` excludes HELD days (`caf_not_full_day`), and leaving
    them in is a mistake this suite made on its first run: IMP1 picked a day with
    a missing punch and reported a product FAILURE for *"Not a full day: … a
    Finger Log may not decide that half a day was worked"* — which is OD-58
    working exactly as designed. The test was wrong, not the product. A held day
    is still a fine subject for a LEAVE (that is how HR clears one), so the flag
    is a parameter rather than a blanket filter.
    """
    f = {"work_date": ["between", list(WINDOW)], "docstatus": 0,
         "day_type": "Workday"}
    if submittable_only:
        f["caf_not_full_day"] = 0
    if employee:
        f["employee"] = employee
    return frappe.get_all("Finger Log", filters=f,
                          fields=["name", "employee", "work_date"],
                          order_by="work_date")


def _subject():
    """An employee with workday drafts in the window AND a leave allocation —
    without the allocation a leave application cannot be approved at all."""
    rows = frappe.db.sql("""
        SELECT fl.employee, COUNT(*) n
          FROM `tabFinger Log` fl
          JOIN `tabLeave Allocation` la ON la.employee = fl.employee
                                       AND la.docstatus = 1
                                       AND la.leave_type = %(lt)s
         WHERE fl.work_date BETWEEN %(a)s AND %(b)s
           AND fl.docstatus = 0 AND fl.day_type = 'Workday'
      GROUP BY fl.employee
        HAVING n >= 4
      ORDER BY n DESC LIMIT 1
    """, {"lt": LEAVE_TYPE, "a": WINDOW[0], "b": WINDOW[1]}, as_dict=True)
    return rows[0].employee if rows else None


def _file_leave(employee, date, note):
    """File and approve one day of leave. Returns (name, error)."""
    try:
        la = frappe.new_doc("Leave Application")
        la.employee = employee
        la.leave_type = LEAVE_TYPE
        la.from_date = la.to_date = date
        la.description = note
        la.status = "Approved"
        if la.meta.has_field("leave_approver"):
            la.leave_approver = frappe.db.get_value("Employee", employee,
                                                    "leave_approver")
        la.flags.ignore_permissions = True
        la.insert()
        la.submit()
        return la.name, None
    except Exception as e:
        frappe.db.rollback()
        return None, frappe.utils.strip_html(str(e)).strip()[:220]


def _cells(apr):
    """The auto-filled grid cells, as one comparable value. They are on the
    KRA CHILD ROWS, never on the parent."""
    d = frappe.get_doc("Appraisal", apr)
    return {r.kra: (r.get("caf_date_cell"), r.get("caf_remarks"))
            for r in (d.get("appraisal_kra") or [])}


def _attendance(employee, date):
    return frappe.db.get_value(
        "Attendance", {"employee": employee, "attendance_date": date,
                       "docstatus": ["<", 2]},
        ["name", "status", "leave_type"], as_dict=True)


def run():
    # ⚠️ `bench execute` masks any exception as `NameError: name 'caf' is not
    # defined`, and print_exc() goes to stderr which does not come back through
    # docker exec (caf/scripts/CLAUDE.md). Both traps hit this file already.
    import traceback
    try:
        return _run()
    except Exception:
        frappe.db.rollback()
        print("\n🔴 THREW:\n" + traceback.format_exc())
        return _summary()


def _run():
    frappe.set_user("Administrator")
    _results.clear()

    emp = _subject()
    if not emp:
        skip("IMP-ALL", "no employee has workday drafts in %s..%s with a %s "
                        "allocation — import the window first" % (*WINDOW, LEAVE_TYPE))
        return _summary()

    name = frappe.db.get_value("Employee", emp, "employee_name")
    drafts = _drafts(emp)
    print("subject: %s %s — %d workday draft(s) in %s..%s\n"
          % (emp, name, len(drafts), *WINDOW))

    # ------------------------------------------------------------------ IMP1
    # The roster gate starts at caf_roster_gate_from; August is before it, so
    # this must submit. If it refuses, the gate is blocking everything and the
    # September test proved nothing.
    target = drafts[0]
    try:
        d = frappe.get_doc("Finger Log", target.name)
        d.flags.ignore_permissions = True
        d.submit()
        frappe.db.commit()
        err = None
    except Exception as e:
        frappe.db.rollback()
        err = frappe.utils.strip_html(str(e)).strip()[:200]
    att = _attendance(emp, target.work_date)
    check("IMP1", err is None and att,
          "a freshly imported draft submits and writes Attendance: %s on %s -> "
          "%s%s. August is BEFORE the roster gate, so a refusal here would mean "
          "the gate blocks everything"
          % (target.name, target.work_date,
             (att.name + " " + str(att.status)) if att else "NO ATTENDANCE",
             "" if err is None else " ERROR: " + err))

    # ------------------------------------------------------------------ IMP2
    # Late leave over a day whose Finger Log is still a DRAFT.
    remaining = _drafts(emp)
    if len(remaining) < 2:
        skip("IMP2", "not enough drafts left for the draft-day leave case")
        leave_draft_day = None
    else:
        day = remaining[0]
        leave_draft_day, lerr = _file_leave(emp, day.work_date, "IMP2 late leave over a DRAFT day")
        a2 = _attendance(emp, day.work_date)
        check("IMP2", leave_draft_day and a2 and a2.leave_type == LEAVE_TYPE,
              "late leave over a day whose log is still a DRAFT: %s -> attendance "
              "%s. The leave is the second legitimate source of Attendance (FDR4), "
              "so it must land even with no submitted log%s"
              % (day.work_date,
                 ("%s %s/%s" % (a2.name, a2.status, a2.leave_type)) if a2 else "NONE",
                 "" if leave_draft_day else " — REFUSED: " + str(lerr)))

    # ------------------------------------------------------------------ IMP3
    # The same thing over a day already SUBMITTED — there is an Attendance row
    # to reconcile, which is the half MG's "before or after unblock" asks about.
    remaining = _drafts(emp)
    if not remaining:
        skip("IMP3", "no draft left to submit for the submitted-day leave case")
    else:
        # 🔴 The FIRST version of this swallowed the submit error and carried on.
        # It then reported "attendance none -> On Leave/MC" and PASSED — while
        # testing exactly the same thing as IMP2, because there was never a
        # submitted row to reconcile. A test whose premise silently failed is
        # worse than no test. The premise is now asserted before the case runs.
        # 🔴 Not `remaining[0]` — that is the day IMP2 just put leave on, and a
        # Finger Log may not overwrite an approved absence ("cancel or amend the
        # leave application first"). The first run hit exactly that and reported
        # a SKIP for a guard working correctly. Take a day with nothing on it.
        free = [r for r in remaining if not _attendance(emp, r.work_date)]
    if not remaining:
        pass
    elif not free:
        skip("IMP3", "every remaining draft day already carries leave from IMP2 — "
                     "no clean day for the 'already submitted' case")
        skip("IMP3b", "depends on IMP3's premise")
    else:
        day = free[0]
        serr = None
        try:
            d = frappe.get_doc("Finger Log", day.name)
            d.flags.ignore_permissions = True
            d.submit()
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            serr = frappe.utils.strip_html(str(e)).strip()[:180]
        before = _attendance(emp, day.work_date)
        if not before:
            skip("IMP3", "PREMISE NOT MET — submitting %s left no Attendance to "
                         "reconcile (%s), so the 'already submitted' case cannot be "
                         "exercised on this day and would otherwise have repeated IMP2"
                         % (day.name, serr or "no error, but no row either"))
            skip("IMP3b", "depends on IMP3's premise")
        else:
            lname, lerr = _file_leave(emp, day.work_date,
                                      "IMP3 late leave over a SUBMITTED day")
            after = _attendance(emp, day.work_date)
            check("IMP3", lname and after and after.leave_type == LEAVE_TYPE,
                  "late leave over a day already SUBMITTED: attendance %s/%s -> %s. "
                  "The existing row must be RECONCILED, not duplicated%s"
                  % (before.status, before.leave_type,
                     ("%s/%s" % (after.status, after.leave_type)) if after else "NONE",
                     "" if lname else " — REFUSED: " + str(lerr)))
            dupes = frappe.db.count("Attendance", {"employee": emp,
                                                   "attendance_date": day.work_date,
                                                   "docstatus": ["<", 2]})
            check("IMP3b", dupes == 1,
                  "exactly ONE live Attendance row for %s after both a submitted log "
                  "and an approved leave (found %d)" % (day.work_date, dupes))
    # ------------------------------------------------------------------ IMP4
    if not frappe.db.exists("Appraisal Cycle", CYCLE):
        skip("IMP4", "no appraisal cycle %s on this site" % CYCLE)
        return _summary()

    apr = frappe.db.get_value("Appraisal", {"employee": emp,
                                            "appraisal_cycle": CYCLE}, "name")
    if not apr:
        try:
            a = frappe.new_doc("Appraisal")
            a.employee = emp
            a.appraisal_cycle = CYCLE
            a.company = frappe.db.get_value("Employee", emp, "company")
            a.appraisal_template = frappe.db.get_value("Appraisal Template", {}, "name")
            a.flags.caf_skip_supervisor_check = True
            a.flags.ignore_permissions = True
            a.insert()
            apr = a.name
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            skip("IMP4", "could not create an appraisal: %s"
                 % frappe.utils.strip_html(str(e)).strip()[:180])
            return _summary()

    # ⚠️ `caf_date_cell` and `caf_remarks` live on the KRA GRID ROWS, not on the
    # Appraisal itself — asking the parent for them raised
    # "Unknown column 'caf_date_cell'". They are the auto-filled cells on the
    # Attendance / Punctuality / OT Hours rows (appraisal.py:640).
    doc = frappe.get_doc("Appraisal", apr)
    cells = {r.kra: (r.get("caf_date_cell"), r.get("caf_remarks"))
             for r in (doc.get("appraisal_kra") or [])
             if r.get("caf_date_cell") or r.get("caf_remarks")}
    check("IMP4", bool(apr) and bool(doc.get("appraisal_kra")),
          "an appraisal for %s exists for the subject (%s) with %d KRA row(s); "
          "auto-filled cells: %s"
          % (CYCLE, apr, len(doc.get("appraisal_kra") or []),
             cells or "(none — the subject has only a few days of imported data "
                      "in this month, so there may be nothing to count)"))

    # ------------------------------------------------------------------ IMP5
    # A leave filed AFTER submission must refresh the submitted appraisal.
    # This is the link that silently does nothing when a hook is unwired.
    # 🔴 The first version SKIPPED here because the appraisal was still a Draft —
    # which quietly dropped the most valuable assertion in the file. The appraisal
    # workflow keeps docstatus 0 until the FINAL transition (D54), so reaching a
    # submitted appraisal means walking it: Submit for Review, then Approve.
    # August has ended, so BR6 permits it.
    if doc.docstatus != 1:
        from frappe.model.workflow import apply_workflow
        for action in ("Submit for Review", "Approve"):
            try:
                doc = frappe.get_doc("Appraisal", apr)
                doc.flags.ignore_permissions = True
                apply_workflow(doc, action)
                frappe.db.commit()
            except Exception as e:
                frappe.db.rollback()
                print("       (workflow %r: %s)"
                      % (action, frappe.utils.strip_html(str(e)).strip()[:150]))
        doc = frappe.get_doc("Appraisal", apr)

    remaining = _drafts(emp)
    if doc.docstatus != 1:
        skip("IMP5", "could not walk the appraisal to submitted (state %r) — the "
                     "post-submission refresh cannot be exercised, and this SKIP is "
                     "not a pass" % doc.get("workflow_state"))
    elif not [r for r in remaining if not _attendance(emp, r.work_date)]:
        skip("IMP5", "no day left to file a post-submission leave on")
    else:
        # 🔴 Same trap as IMP3: `remaining[0]` is usually a day IMP2 or IMP3
        # already put leave on, and stock refuses a second application for the
        # same type and date ("has already applied for MC between…"). That is
        # correct, and it made IMP5 report a product failure for a test bug.
        day = [r for r in remaining if not _attendance(emp, r.work_date)][0]
        before = _cells(apr)
        lname, lerr = _file_leave(emp, day.work_date, "IMP5 leave AFTER the appraisal was submitted")
        after = _cells(apr)
        check("IMP5", lname and (after != before),
              "a leave filed AFTER the appraisal was submitted refreshed it: "
              "%r -> %r%s" % (before, after,
                              "" if lname else " — leave REFUSED: " + str(lerr)))

    return _summary()


def _summary():
    ok = sum(1 for _, p, _ in _results if p)
    print("\n%d/%d passed" % (ok, len(_results)))
    bad = [t for t, p, _ in _results if not p]
    if bad:
        print("FAILED: %s" % bad)
    return {"passed": ok, "total": len(_results), "failed": bad}


def cleanup():
    """Remove the whole imported window — logs, their Attendance, and the leave
    and appraisal this suite created. MG, 2026-09-12: *"if all green then can
    remove the 616"*.

    ⚠️ Cancel before delete, and children before parents: a DELETE is blocked by
    ANY referrer, cancelled ones included (quirks #63).
    """
    frappe.set_user("Administrator")
    counts = {"leave": 0, "appraisal": 0, "attendance": 0, "finger_log": 0}

    emps = [r.employee for r in frappe.get_all(
        "Finger Log", filters={"work_date": ["between", list(WINDOW)]},
        fields=["distinct employee as employee"])]

    for la in frappe.get_all("Leave Application",
                             filters={"from_date": ["between", list(WINDOW)]},
                             fields=["name", "docstatus"]):
        try:
            if la.docstatus == 1:
                d = frappe.get_doc("Leave Application", la.name)
                d.flags.ignore_permissions = True
                d.cancel()
            frappe.delete_doc("Leave Application", la.name,
                              ignore_permissions=True, force=True)
            counts["leave"] += 1
        except Exception as e:
            print("  leave %s: %s" % (la.name, str(e)[:110]))

    for a in frappe.get_all("Appraisal", filters={"appraisal_cycle": CYCLE,
                                                  "employee": ["in", emps or [""]]},
                            fields=["name", "docstatus"]):
        try:
            if a.docstatus == 1:
                d = frappe.get_doc("Appraisal", a.name)
                d.flags.ignore_permissions = True
                d.cancel()
            frappe.delete_doc("Appraisal", a.name, ignore_permissions=True, force=True)
            counts["appraisal"] += 1
        except Exception as e:
            print("  appraisal %s: %s" % (a.name, str(e)[:110]))

    for at in frappe.get_all("Attendance",
                             filters={"attendance_date": ["between", list(WINDOW)]},
                             fields=["name", "docstatus"]):
        try:
            if at.docstatus == 1:
                d = frappe.get_doc("Attendance", at.name)
                d.flags.ignore_permissions = True
                d.cancel()
            frappe.delete_doc("Attendance", at.name, ignore_permissions=True, force=True)
            counts["attendance"] += 1
        except Exception as e:
            print("  attendance %s: %s" % (at.name, str(e)[:110]))

    for fl in frappe.get_all("Finger Log",
                             filters={"work_date": ["between", list(WINDOW)]},
                             fields=["name", "docstatus"]):
        try:
            if fl.docstatus == 1:
                d = frappe.get_doc("Finger Log", fl.name)
                d.flags.ignore_permissions = True
                d.cancel()
            frappe.delete_doc("Finger Log", fl.name, ignore_permissions=True, force=True)
            counts["finger_log"] += 1
        except Exception as e:
            print("  finger log %s: %s" % (fl.name, str(e)[:110]))

    frappe.db.commit()
    print("removed: %s" % counts)
    left = frappe.db.count("Finger Log", {"work_date": ["between", list(WINDOW)]})
    print("Finger Logs left in %s..%s: %d" % (*WINDOW, left))
    return counts
