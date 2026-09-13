"""Cancelling a roster confirmation does NOT take its holidays back. L4 rung 4.6.

    bench --site <site> execute caf.tests.chain.test_roster_holidays.run

🔴 WHY THIS EXISTS
-------------------
When HR confirms a month's roster she can list the new public holidays on the same
form, and submitting it **writes them into the real Holiday List**. If she then
cancels that form — because the month was wrong, or she filed it twice — the
holidays **stay where they were written**.

⭐ **That is deliberate, and it is the right way round.** A Holiday List drives the
alternating-Saturday calendars for the whole company; silently pulling a gazetted
date back out because a form was cancelled would move everybody's Saturdays
without anybody asking. So the form says so instead:

> *"This form is cancelled, but the holidays it recorded are still in the Holiday
> List: … Remove them there if they were wrong — the alternate-Saturday calendars
> will regenerate and report what moved."*

🔴 **The risk is that nobody notices the message.** HR cancels a form, assumes it
undid itself, and a date she never meant to gazette is now moving rest days. The
message is the only thing standing between her and that, which is why it is worth
a test — and a manual row.

⚠️ IT WRITES TO A REAL HOLIDAY LIST and removes the row again in the `finally`,
asserting the list is back to the length it started at. The date used is a
**Wednesday**, deliberately: L4 measured that a weekday holiday moves no
alternate-Saturday calendar at all, so this suite cannot disturb the roster.
"""

import traceback

import frappe
from frappe.utils import getdate, strip_html

from caf.caf.holiday_lists import PH_LIST

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:<26}{'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def _in_list(ph, date):
    return bool(frappe.db.exists("Holiday", {"parent": ph,
                                             "holiday_date": getdate(date)}))


def _count(ph):
    return frappe.db.count("Holiday", {"parent": ph})


def _pick_wednesday(year):
    """A Wednesday in that year with no holiday on it yet. A WEEKDAY on purpose:
    L4 measured that only a SATURDAY holiday moves the alternating calendars."""
    from frappe.utils import add_days
    d = getdate(f"{year}-11-04")
    for _ in range(40):
        if d.weekday() == 2 and not _in_list(PH_LIST.format(year=year), d):
            return str(d)
        d = add_days(d, 1)
    return None


def _drop_form(name):
    doc = frappe.get_doc("Monthly Roster Confirmation", name)
    if doc.docstatus == 1:
        doc.flags.ignore_permissions = True
        doc.cancel()
    frappe.delete_doc("Monthly Roster Confirmation", name, force=True,
                      ignore_permissions=True)


def run():
    frappe.set_user("Administrator")
    year = getdate(frappe.utils.nowdate()).year
    ph = PH_LIST.format(year=year)
    if not frappe.db.exists("Holiday List", ph):
        print(f"SKIPPED — no {ph!r} on this site.")
        return True

    day = _pick_wednesday(year)
    if not day:
        print("SKIPPED — no free Wednesday found to use as a probe holiday.")
        return True

    month_start = day[:8] + "01"
    started_with = _count(ph)
    form = None

    try:
        for r in frappe.get_all("Monthly Roster Confirmation",
                                filters={"month_start": month_start},
                                fields=["name"]):
            _drop_form(r.name)

        doc = frappe.new_doc("Monthly Roster Confirmation")
        doc.month_start = month_start
        # ⚠️ `day_of_week` is the FULL name — "Wednesday", not "Wed". OD-85's
        # entry guard checks the two against each other and refused the first
        # version of this fixture: *"is dated 2026-11-04, which is a Wednesday —
        # not a Wed. One of the two is a typo, and a holiday keyed a day out moves
        # every alternate Saturday after it."* The guard is right; the fixture was
        # wrong, and the refusal is worth seeing in a docstring.
        doc.append("holidays", {"holiday_name": "chain probe — not a real holiday",
                                "holiday_date": day,
                                "day_of_week": getdate(day).strftime("%A")})
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
        doc.submit()
        frappe.db.commit()
        form = doc.name
        doc.reload()

        check("RH1-SUBMIT-WRITES-IT",
              _in_list(ph, day) and doc.holidays[0].added_to_list == 1,
              f"submitting the confirmation wrote {day} into {ph} and marked the "
              f"row `added_to_list`. ⭐ This is the whole point of listing holidays "
              f"on the roster form — HR records the month and gazettes its dates "
              f"in one act")

        # ── cancel it, and watch the holiday stay ──────────────────────────
        before = len(frappe.message_log or [])
        doc.flags.ignore_permissions = True
        doc.cancel()
        frappe.db.commit()
        msgs = [strip_html(str(m.get("message", m)) if isinstance(m, dict) else str(m))
                for m in (frappe.message_log or [])[before:]]

        check("RH2-CANCEL-KEEPS-IT", _in_list(ph, day),
              f"the form is cancelled and {day} is STILL in {ph}. ⭐ Deliberate: a "
              f"Holiday List drives the alternating-Saturday calendars for the "
              f"whole company, and silently withdrawing a gazetted date because a "
              f"form was cancelled would move everybody's Saturdays with nobody "
              f"asking")

        said = " ".join(msgs)
        check("RH3-AND-IT-SAYS-SO",
              "still in the holiday list" in said.lower()
              and "chain probe" in said.lower(),
              f"…and it TELLS her, naming the holiday it left behind: "
              f"{said[:170]!r}. 🔴 This message is the only thing between HR and a "
              f"date she never meant to gazette moving rest days for the rest of "
              f"the year — she cancels a form and reasonably assumes it undid "
              f"itself")

    except Exception:
        print(traceback.format_exc())
        RESULTS.append(("CRASH", False, "see the traceback above"))
    finally:
        frappe.set_user("Administrator")
        try:
            if form:
                _drop_form(form)
            for r in frappe.get_all("Holiday", filters={"parent": ph,
                                                        "holiday_date": getdate(day)},
                                    fields=["name"]):
                frappe.db.delete("Holiday", {"name": r.name})
            frappe.db.commit()
            frappe.clear_document_cache("Holiday List", ph)
        finally:
            now = _count(ph)
            check("RH-RESTORE", now == started_with,
                  f"{ph} is back to {now} holidays (started with {started_with}). "
                  f"⚠️ A suite that leaves a holiday behind moves the whole "
                  f"company's rest days")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
