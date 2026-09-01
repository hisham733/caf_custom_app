"""An OT refusal must name the person, the day, the hours and the DOCUMENT.

    bench --site <site> execute caf.tests.fingerlog.test_ot_messages.run

MG's manual-test finding, 2026-09-01: *"the OT message does not name the blocking
OT Approval."* The three refusals said things like:

    "No OT Approval records found, HR-EMP-00052"
    "OT Approval for HR-EMP-00052 has issue"
    "HR-EMP-00052 OT duration is greater than approved OT"

An employee **id** — the one identifier the supervisor reading it does not have —
no date, no hours, no document, and nothing about what to do. This is the guard
standing between a clocked hour and an unapproved payment, met by somebody at 6pm
who then has to work all of that out for themselves.

WHY THE ASSERTIONS ARE SHAPED THIS WAY
--------------------------------------
Asserting an exact sentence would make the suite fail on every wording change and
teach nobody anything. What is asserted instead is that each message CARRIES THE
FACTS a person needs to act: the name, the date, the hours, the document id, and —
where there is a choice to make — that it says so. Reword freely; drop a fact and
the suite goes red.

Self-cleaning: builds its own OT Approval and Finger Log, removes them in
`finally`.
"""

import frappe
from frappe.utils import strip_html

RESULTS = []
DAY = "2026-06-11"          # a Thursday in June — no imported Finger Logs (F4d)
# ⚠️ A SECOND day for OT6/OT7. `has_previous_submission()` refuses a second
# approval for the same employee AND date, and OT5 leaves a submitted special
# approval on DAY — so the server-side sync assertions need a clean date rather
# than an unpicking of the fixture above.
DAY2 = "2026-06-12"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:24s} {'PASS' if ok else 'FAIL'}  {detail}")


def _facts(msg, *needles):
    """Which of these facts does the message actually carry?"""
    flat = strip_html(msg)
    return {n: (str(n) in flat) for n in needles}


def _cleanup(emp):
    for dt, field in (("Finger Log", "work_date"), ("OT Approval", "work_date")):
        for r in frappe.get_all(dt, filters={field: ("in", [DAY, DAY2])},
                                fields=["name"]):
            doc = frappe.get_doc(dt, r.name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.flags.ignore_links = True
                doc.cancel()
            frappe.delete_doc(dt, r.name, force=True, ignore_permissions=True)
    frappe.db.commit()


def _log(emp, ot_hours):
    d = frappe.new_doc("Finger Log")
    d.employee = emp
    d.work_date = DAY
    d.time_in = "08:00:00"
    d.set("break", "12:00:00")
    d.resume = "13:00:00"
    d.out = "20:00:00"
    d.overtime = ot_hours          # FBR2 — hour.minute, not decimal
    d.flags.ignore_permissions = True
    d.insert(ignore_permissions=True)
    return d


def _approval(emp, hours, kind="normal", submit=True):
    """Build an approval for exactly `hours`, derived from the employee's shift.

    ⚠️ Two traps, both hit while writing this:

    1. The child table is **`emp_list`**, not `ot_table`. Appending to a fieldname
       that does not exist fails with a bare
       `AttributeError: 'NoneType' object has no attribute 'options'` — Frappe
       looked the field up, got None, and asked it for its options.
    2. **`OT Approval` recomputes `ot_duration` and refuses a value that
       disagrees** — *"The OT Duration for Employee X is incorrect. The correct OT
       Duration should be -8."* The formula is

           ot_duration = (ot_end - start_work) / 3600 - <the shift's work hours>

       so 🔴 **`start_work` is the start of the WORKING DAY, not the start of the
       overtime.** Passing the shift's *end* time there gives a negative duration,
       which is what -8 was. Both times are derived from the shift below so the
       arithmetic agrees by construction, and `hours` must be a multiple of 0.5
       because `convertTo_nearest` rounds to that.
    """
    shift = frappe.db.get_value("Employee", emp, "default_shift")
    s = frappe.db.get_value("Shift Type", shift, ["start_time", "end_time"],
                            as_dict=True)

    def mins(v):
        return int(v.total_seconds() // 60) if hasattr(v, "total_seconds") \
            else int(str(v)[:2]) * 60 + int(str(v)[3:5])

    def hhmm(m):
        return f"{m // 60:02d}:{m % 60:02d}:00"

    start_work = mins(s.start_time)
    ot_end = mins(s.end_time) + int(round(hours * 60))

    a = frappe.new_doc("OT Approval")
    a.type = kind
    a.work_date = DAY
    a.ot_department = frappe.db.get_value("Employee", emp, "department")
    a.append("emp_list", {"emp_id": emp, "work_date": DAY,
                          "start_work": hhmm(start_work),
                          "ot_end": hhmm(ot_end), "ot_duration": hours})
    a.flags.ignore_permissions = True
    a.insert(ignore_permissions=True)
    if submit:
        a.submit()
    return a


def run():
    frappe.set_user("Administrator")
    # Somebody on a shift that ALLOWS OT, or ot_in_hour is 0 and nothing fires.
    emp = frappe.db.sql("""
        SELECT e.name, e.employee_name FROM `tabEmployee` e
          JOIN `tabShift Type` s ON s.name = e.default_shift
         WHERE e.status='Active' AND s.caf_allow_ot = 1
         LIMIT 1""", as_dict=True)
    if not emp:
        print("🔴 no active employee on an OT-allowing shift — cannot test")
        return False
    emp = emp[0]
    print(f"using {emp.name} {emp.employee_name}\n")

    try:
        _cleanup(emp.name)

        # ── OT1 — no approval at all ───────────────────────────────────────
        log = _log(emp.name, 2.30)          # 2 h 30
        try:
            log.submit()
            msg = ""
        except Exception as e:
            msg = strip_html(str(e))
        f = _facts(msg, emp.employee_name, DAY, log.ot_in_hour)
        check("OT1-NO-APPROVAL-NAMES-ALL", all(f.values()) and "draft" in msg.lower(),
              f"the refusal carries the NAME, the DATE and the HOURS {f}, and says "
              f"the log stays a draft so nothing is lost. It used to say only "
              f"'No OT Approval records found, {emp.name}'")

        # ── OT2 — approved, but for fewer hours ────────────────────────────
        appr = _approval(emp.name, 1.0)
        log.reload()
        try:
            log.submit()
            msg = ""
        except Exception as e:
            msg = strip_html(str(e))
        f = _facts(msg, emp.employee_name, DAY, appr.name, "1.0")
        check("OT2-NAMES-THE-DOCUMENT", f.get(appr.name) and all(f.values()),
              f"🔴 THE ONE MG ASKED FOR — the refusal NAMES the blocking OT "
              f"Approval ({appr.name}) alongside the name, date and both figures "
              f"{f}. Previously it named none of them")
        check("OT2-OFFERS-A-CHOICE",
              "special" in msg.lower() and "ingress" in msg.lower(),
              "…and it says what to do about it: amend the approval / file a "
              "special approval if the hours were genuinely worked, or correct "
              "the punches in Ingress if the clock is wrong. Two different "
              "decisions, and the message no longer leaves the supervisor to "
              "guess which one they are making")

        # ── OT3 — a DRAFT approval authorises nothing ──────────────────────
        appr.cancel()
        draft = _approval(emp.name, 5.0, submit=False)
        log.reload()
        try:
            log.submit()
            msg = ""
        except Exception as e:
            msg = strip_html(str(e))
        # A draft parent has draft children, so the child filter excludes it and
        # this presents as "no approval" — which is CORRECT and is the point:
        # an unsubmitted approval must be worth exactly nothing.
        check("OT3-DRAFT-AUTHORISES-NOTHING",
              bool(msg) and str(log.ot_in_hour) in strip_html(msg),
              f"a DRAFT approval for 5 h does not let 2.5 h through — the log is "
              f"still refused, naming the hours. An approval nobody submitted must "
              f"be worth nothing, or the submit step means nothing")

        # ── OT4 — the re-resolve twin says the same thing ──────────────────
        # HR meets both in one worklist; two descriptions of one problem is how
        # somebody comes to believe there are two problems.
        frappe.delete_doc("OT Approval", draft.name, force=True,
                          ignore_permissions=True)
        from caf.caf.re_resolve import _ot_coverage
        log.reload()
        _final, _appr, _ovr, problem = _ot_coverage(log)
        f = _facts(problem or "", emp.employee_name, DAY, log.ot_in_hour)
        check("OT4-RERESOLVE-AGREES", bool(problem) and all(f.values()),
              f"the non-throwing twin used by re-resolve carries the same facts "
              f"{f} — it writes `caf_hr_review_note`, which is what HR actually "
              f"reads. It used to say only 'OT of 2.5h has no OT Approval'")

        # ── OT5 — a special approval still works ───────────────────────────
        special = _approval(emp.name, 1.5, kind="special_approve")
        log.reload()
        log.submit()
        log.reload()
        check("OT5-SPECIAL-STILL-PASSES",
              log.docstatus == 1 and float(log.final_ot) == 1.5
              and log.ot_approval_id == special.name and log.has_overwrite == 1,
              f"a special approval still overrides the clock: final_ot="
              f"{log.final_ot} from {log.ot_approval_id}, has_overwrite="
              f"{log.has_overwrite}. The messages changed; the money rules did not")

        # ── OT6 — 🔴 the invariant is now SERVER-side, not JavaScript ──────
        # MG, 2026-09-01: the intended design is that a row's work_date equals
        # the header's — `ot_approval.js` says so — and it was enforced only in
        # the browser. Measured: every human-created approval satisfies it; all
        # 77 rows that violate it were imported by Administrator on one day.
        #
        # The cost of JS-only: an approval created by API, Data Import or bench
        # gets BLANK row dates, so `check_ot_approval` matches nothing and the
        # overtime is refused as "no approval" — while a submitted approval sits
        # there looking correct. Built here without the form, which is exactly
        # the path that used to break.
        shift = frappe.db.get_value("Employee", emp.name, "default_shift")
        st = frappe.db.get_value("Shift Type", shift, ["start_time", "end_time"],
                                 as_dict=True)

        def _m(v):
            return int(v.total_seconds() // 60) if hasattr(v, "total_seconds") \
                else int(str(v)[:2]) * 60 + int(str(v)[3:5])

        def _s(m):
            return f"{m // 60:02d}:{m % 60:02d}:00"

        api = frappe.new_doc("OT Approval")
        api.type = "normal"
        api.work_date = DAY2
        api.ot_department = frappe.db.get_value("Employee", emp.name, "department")
        api.append("emp_list", {"emp_id": emp.name,
                                "start_work": _s(_m(st.start_time)),
                                "ot_end": _s(_m(st.end_time) + 60),
                                "ot_duration": 1.0})
        api.flags.ignore_permissions = True
        api.insert(ignore_permissions=True)
        check("OT6-SERVER-SETS-ROW-DATE",
              str(api.emp_list[0].work_date) == DAY2,
              f"an OT Approval built WITHOUT the form still gets its row date "
              f"({api.emp_list[0].work_date}) — the sync moved from "
              f"ot_approval.js into validate(). Before this, such a row carried "
              f"no date at all, matched no Finger Log, and the employee's OT was "
              f"refused as 'no approval' while the approval sat there submitted")

        # ── OT7 — and a future work_date is refused server-side too ───────
        future = frappe.new_doc("OT Approval")
        future.type = "normal"
        future.work_date = frappe.utils.add_days(frappe.utils.nowdate(), 7)
        future.ot_department = api.ot_department
        future.append("emp_list", {"emp_id": emp.name,
                                   "start_work": _s(_m(st.start_time)),
                                   "ot_end": _s(_m(st.end_time) + 60),
                                   "ot_duration": 1.0})
        future.flags.ignore_permissions = True
        refused = ""
        try:
            future.insert(ignore_permissions=True)
        except Exception as e:
            refused = strip_html(str(e))
        check("OT7-NO-FUTURE-APPROVAL", "future" in refused.lower(),
              f"approving overtime for a day that has not happened is refused "
              f"server-side — {refused[:90]!r}. That guard was also JavaScript "
              f"only, so a script could authorise next month's overtime today")

        frappe.delete_doc("OT Approval", api.name, force=True,
                          ignore_permissions=True)

    finally:
        frappe.set_user("Administrator")
        _cleanup(emp.name)

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
