"""ROSTER-* — the monthly confirmation and the Finger Log gate.  OD-71.

    bench --site <site> execute caf.tests.fingerlog.test_monthly_roster.run

🔴 THE ASSERTION THAT EARNS ITS PLACE IS ROSTER-DAY
---------------------------------------------------
MG's checksum, 2026-08-13: *"HR manager will enter holiday name, holiday date,
holiday day (M/T/Sun) — on save, validate the day and the date match. You never
know."* The same shape as `work + short = net`: a value that could be derived is
asked for anyway, so a typo has something to disagree with. **A holiday keyed one
day out inverts every alternate Saturday after it** (§6.13a, measured), and the
day is the cheapest possible place to catch it.

⚠️ THIS SUITE MUTATES TWO THINGS AND ASSERTS THE RESTORE
--------------------------------------------------------
`ROSTER-SUBMIT` appends a real holiday to `CAF Public Holidays 2026`, which fires
OD-74 and moves the calendars — so the fixture Saturday is in **December**
(2026-12-19, clear of `test_alt_saturday`'s 12-12), and `ROSTER-RESTORE`
compares against a snapshot taken before anything was touched. The gate tests set
`HR Settings.caf_roster_gate_from`, a **Single**, restored in the `finally`.
"""

import frappe
from frappe.utils import getdate

from caf.caf.doctype.monthly_roster_confirmation import monthly_roster_confirmation as mrc
from caf.caf.holiday_lists import PH_LIST, _alt_lists, rest_saturdays_in

GATE_EMP = "HR-EMP-00020"        # Chan Wai Khong — 8am Schedule, no alt Saturday
D_LOG = "2026-06-16"             # Tuesday. 06-17 is AWAL MUHARRAM (§F1c)
MONTH = "2026-06-01"
CONF = "ROSTER-2026-06"

D_HOL = "2026-12-19"             # a Saturday, late: small blast radius
D_HOL_MONTH = "2026-12-01"
CONF_DEC = "ROSTER-2026-12"
HOL_NAME = "TEST — monthly roster suite"

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def throws(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return ""
    except Exception as e:
        return str(e)


def snapshot():
    return {n: rest_saturdays_in(n) for n in _alt_lists(2026)}


def set_gate(value):
    """⚠️ A Single's value survives `frappe.clear_cache(doctype=...)`.

    That clears the META cache; the stored value has its own document cache, and
    the first version of this suite set the gate to None, read it back as the
    previous value, and crashed in a test that was asserting the opposite. Clear
    both, commit, and let the caller assert the precondition.
    """
    frappe.db.set_single_value("HR Settings", mrc.GATE_FIELD, value or "")
    frappe.db.commit()
    frappe.clear_document_cache("HR Settings", "HR Settings")
    frappe.clear_cache(doctype="HR Settings")
    return mrc.gate_from()


def new_conf(month, **kw):
    doc = frappe.new_doc("Monthly Roster Confirmation")
    doc.month_start = month
    for k, v in kw.items():
        doc.set(k, v)
    doc.flags.ignore_permissions = True
    return doc


def drop_ph(day):
    doc = frappe.get_doc("Holiday List", PH_LIST.format(year=getdate(day).year))
    keep = [h for h in doc.holidays if getdate(h.holiday_date) != getdate(day)]
    if len(keep) != len(doc.holidays):
        doc.holidays = keep
        doc.flags.ignore_permissions = True
        doc.save()
        frappe.db.commit()


def cleanup():
    for name in (CONF, CONF_DEC):
        if frappe.db.exists("Monthly Roster Confirmation", name):
            doc = frappe.get_doc("Monthly Roster Confirmation", name)
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc("Monthly Roster Confirmation", name,
                              ignore_permissions=True, force=True)
    for r in frappe.get_all("Finger Log",
                            filters={"employee": GATE_EMP, "work_date": D_LOG},
                            fields=["name", "docstatus"]):
        for att in frappe.get_all("Attendance", filters={"caf_finger_log": r.name},
                                  fields=["name", "docstatus"]):
            a = frappe.get_doc("Attendance", att.name)
            a.flags.ignore_permissions = True
            a.flags.ignore_links = True
            if a.docstatus == 1:
                a.cancel()
            frappe.delete_doc("Attendance", att.name, ignore_permissions=True,
                              force=True)
        doc = frappe.get_doc("Finger Log", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Finger Log", r.name, ignore_permissions=True, force=True)
    drop_ph(D_HOL)
    frappe.db.commit()


def make_log():
    doc = frappe.new_doc("Finger Log")
    doc.employee = GATE_EMP
    doc.employee_name = frappe.db.get_value("Employee", GATE_EMP, "employee_name")
    doc.work_date = D_LOG
    doc.time_in, doc.out = "08:00:00", "17:00:00"
    doc.set("break", "12:00:00")
    doc.resume = "13:00:00"
    doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


def run():
    frappe.set_user("Administrator")
    cleanup()
    base = snapshot()
    # 🔴 Through `gate_from()`, not the raw single value — and the first version
    # read it raw and made this suite NON-RE-RUNNABLE (§F5): it passed, then
    # failed, then passed. Clearing a Date on a Single stores a sentinel that
    # reads back as `0001-01-01`, so run N wrote "" and run N+1 read year 1 and
    # compared it against a normalised None. The MEANING is what has to be
    # restored, and the meaning is what `gate_from()` returns.
    gate_before = mrc.gate_from()

    try:
        # ----------------------------------------------------------- ROSTER-DAY 🔴
        # 2026-12-19 is a SATURDAY. Key it as a Monday and the form must refuse,
        # naming BOTH so HR can see which one is the typo.
        bad = new_conf(D_HOL_MONTH, holidays=[{
            "holiday_name": HOL_NAME, "holiday_date": D_HOL,
            "day_of_week": "Monday"}])
        err = throws(bad.insert)
        check("ROSTER-DAY", "Saturday" in err and "Monday" in err,
              f"a holiday dated {D_HOL} but keyed 'Monday' is REFUSED, and the "
              f"message names both: {frappe.utils.strip_html(err)[:120] or '🔴 it saved'}")

        # -------------------------------------------------------- ROSTER-DAY-OK
        good = new_conf(D_HOL_MONTH, holidays=[{
            "holiday_name": HOL_NAME, "holiday_date": D_HOL,
            "day_of_week": "Saturday"}])
        good.insert()
        check("ROSTER-DAY-OK", good.name == CONF_DEC and not good.holidays[0].already_in_list,
              f"with the right day it saves as {good.name} — one per month, so a "
              f"second form for December collides by name rather than quietly "
              f"existing twice. `already_in_list` reads "
              f"{good.holidays[0].already_in_list}")

        # ----------------------------------------------------------- ROSTER-SAT
        # (b) is a CONFIRMATION, pre-filled from the generated calendar.
        sats = good.saturdays or []
        dec_sats = {str(r.saturday) for r in sats}
        check("ROSTER-SAT", sats and len(dec_sats) == 4
              and all(r.generated in ("Rest", "Work") for r in sats)
              and all(r.agreed for r in sats),
              f"the Saturday table pre-filled itself from the generated calendar: "
              f"{len(sats)} rows over {len(dec_sats)} Saturdays, every one "
              f"pre-ticked and read-only. HR confirms; HR does not re-enter — the "
              f"manual step is where February's errors came from")

        # -------------------------------------------------------- ROSTER-SUBMIT 🔴
        # The whole chain: form -> Holiday List -> OD-74 -> calendars move.
        good.submit()
        in_list = frappe.db.exists("Holiday", {
            "parent": PH_LIST.format(year=2026), "holiday_date": getdate(D_HOL)})
        after = snapshot()
        moved = sum(len(base[n] ^ after.get(n, set())) for n in base)
        check("ROSTER-SUBMIT", in_list and moved > 0,
              f"submitting appended it to CAF Public Holidays 2026 and the "
              f"alternate-Saturday calendars MOVED — {moved} Saturdays — without "
              f"anyone calling the generator. Form ➜ list ➜ OD-74 ➜ calendar, "
              f"end to end")

        # --------------------------------------------------------- ROSTER-BOTH
        clash = new_conf("2026-11-01", no_new_holidays=1, holidays=[{
            "holiday_name": "x", "holiday_date": "2026-11-02",
            "day_of_week": "Monday"}])
        err2 = throws(clash.insert)
        check("ROSTER-BOTH", "cannot both be true" in err2 or "Untick" in err2,
              f"'nothing new' AND a list of new things is refused: "
              f"{frappe.utils.strip_html(err2)[:90] or '🔴 it saved'}")

        # -------------------------------------------------------- ROSTER-EMPTY
        blank = new_conf("2026-11-01")
        err3 = throws(blank.insert)
        check("ROSTER-EMPTY", "tick" in err3.lower(),
              f"and an UNANSWERED form is refused too — the thing this exists to "
              f"prevent: {frappe.utils.strip_html(err3)[:90] or '🔴 it saved'}")

        # ----------------------------------------------------- ROSTER-GATE-OFF 🔴
        # Off by default. Every imported row and every fixture predates the form,
        # so a gate with no start date would refuse the entire dataset.
        now = set_gate(None)
        log = make_log()
        err_off = throws(log.submit)
        log.reload()
        check("ROSTER-GATE-OFF", now is None and log.docstatus == 1,
              f"with no start date the gate is OFF (gate_from()={now}) and {D_LOG} "
              f"submits normally (docstatus {log.docstatus})"
              f"{' — 🔴 ' + frappe.utils.strip_html(err_off)[:70] if err_off else ''}. "
              f"D-NEW-1: pre-implementation data is not governed by the new rules")
        cleanup()

        # ------------------------------------------------------ ROSTER-GATE-ON 🔴
        set_gate("2026-06-01")
        log2 = make_log()
        err4 = throws(log2.submit)
        log2.reload()
        check("ROSTER-GATE-ON", err4 and log2.docstatus == 0
              and "June 2026" in err4 and "href" in err4,
              f"with the gate on, {D_LOG} SAVES but cannot submit (docstatus "
              f"{log2.docstatus}) — the draft is HR's queue. The message names "
              f"the month and carries a LINK, so the way out is a click and not a "
              f"support call: {frappe.utils.strip_html(err4)[:100]}")

        # ---------------------------------------------------- ROSTER-GATE-PASS
        conf = new_conf(MONTH, no_new_holidays=1)
        conf.insert()
        conf.submit()
        log2.reload()
        log2.flags.ignore_permissions = True
        log2.submit()
        check("ROSTER-GATE-PASS", log2.docstatus == 1,
              f"and once {conf.name} is SUBMITTED the same log goes through "
              f"(docstatus {log2.docstatus}). The gate is keyed on the WORK "
              f"DATE's month, never on today")

        # --------------------------------------------------- ROSTER-GATE-DRAFT
        # A draft confirmation must not open the gate — the whole point is that
        # somebody submitted it.
        cleanup()
        draft = new_conf(MONTH, no_new_holidays=1)
        draft.insert()
        log3 = make_log()
        err5 = throws(log3.submit)
        check("ROSTER-GATE-DRAFT", bool(err5),
              f"a DRAFT confirmation does not open the gate: "
              f"{frappe.utils.strip_html(err5)[:80] or '🔴 it submitted'}")

    finally:
        frappe.set_user("Administrator")
        set_gate(gate_before)
        cleanup()
        frappe.db.commit()

    # ------------------------------------------------------- ROSTER-RESTORE 🔴
    end = snapshot()
    gate_now = mrc.gate_from()
    cal_diff = {n: sorted(base.get(n, set()) ^ end.get(n, set()))
                for n in set(base) | set(end)}
    cal_diff = {n: v for n, v in cal_diff.items() if v}
    gate_ok = gate_now == gate_before
    check("ROSTER-RESTORE", not cal_diff and gate_ok,
          f"the live calendars and the gate setting are back as found — calendar "
          f"differences: {cal_diff or 'none'}; gate {gate_before!r} ➜ {gate_now!r}. "
          f"This suite appends a REAL holiday and flips a REAL setting; leaving "
          f"either would corrupt every later suite silently")

    print("\n=== Monthly roster confirmation + the Finger Log gate (OD-71) ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:20s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
