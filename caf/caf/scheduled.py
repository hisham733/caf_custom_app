"""N1 + N2 — the two scheduled jobs this project promised and never built.

Purpose : N1  on 1 November, build next year's skeleton and tell HR to fill in
              the public holidays (plan §4378 "Layer 2").
          N2  weekly, run the roster detectors and tell HR when one fires.
Run     : bench --site <site> execute caf.caf.scheduled.november_rollover_plan
          bench --site <site> execute caf.caf.scheduled.november_rollover
          bench --site <site> execute caf.caf.scheduled.weekly_roster_check
Refs    : plan §4378 · roadmap §9e N1/N2 · OD-71 · OD-71b · framework §6.14

WHY BOTH LIVE IN ONE MODULE
---------------------------
They are the same shape — a job that runs on a clock, finds something a human
must act on, and has to actually TELL somebody. The telling is the part that was
missing from both, so it is written once here (`notify_hr_managers`) rather than
twice.

N1 — 1 NOVEMBER, plan §4378
---------------------------
    "The STRUCTURE of next year's holiday lists is predictable — the weekly off
     day and each group's Saturday pattern carry forward. Only the PUBLIC
     HOLIDAY dates change, because they move each year. So on 1 November, create
     next year's Holiday Lists as drafts ... with the public-holiday rows left
     empty. Same for the Leave Period and the 12 Appraisal Cycles."

⚠️ **"As drafts" cannot mean `docstatus = 0` — a Holiday List is not
submittable.** It means *structurally present and deliberately empty of public
holidays*.

🔴 **AND THE SPEC CANNOT BE BUILT THE WAY IT IS WRITTEN.** §4378 says to generate
next year's pattern lists in November. `generate_holiday_lists()` refuses:

    collect_public_holidays(year)
      -> frappe.throw("No public holidays found for {year} in any shift Holiday List")

It has no mode for a year whose dates are not known yet — which is every year on
1 November, by definition. That is not a defect in the generator; it is the spec
having been written before the generator existed.

✅ **The design already solves it, and better.** `CAF Public Holidays <year>` is
the SOURCE, and the Holiday List `on_update` hook regenerates every pattern list
from it. So the moment HR saves the gazette dates, all four pattern lists appear
with the right rest days and the right alternation — nothing has to pre-build
them. N1's job is therefore narrower than §4378 imagined:

    create the ONE list HR fills in, the Leave Period and the 12 cycles,
    then tell HR the dates are missing.

⚠️ Generating pattern lists in November would also mean generating them **twice**
— once empty, once for real — and the empty pass would sit in the system for two
months looking authoritative. One list HR must obviously fill is safer than four
that look finished.

N2 — WEEKLY, MG 2026-08-13: *"notify anyone with HR Manager role"*
-------------------------------------------------------------------
✅ MG was right that the indicator already exists: the roster page renders three
alarm panels. What it does NOT do is tell anybody — HR has to open the page.
This runs the same three functions on a clock and notifies when one fires.

Changelog
---------
1.0  2026-08-13  N1 and N2 built
"""

from datetime import date

import frappe
from frappe.utils import getdate, nowdate

HR_ROLE = "HR Manager"
CYCLE_STATUS = "Not Started"


# ─────────────────────────────────────────────────────────── the telling
def hr_managers():
    """Enabled users holding HR Manager. The population MG chose for both jobs."""
    users = {r.parent for r in frappe.get_all(
        "Has Role", filters={"role": HR_ROLE, "parenttype": "User"},
        fields=["parent"])}
    return sorted(u for u in users
                  if frappe.db.get_value("User", u, "enabled")
                  and u not in ("Administrator", "Guest"))


def notify_hr_managers(subject, message, doctype=None, name=None):
    """One Notification Log per HR Manager. Returns who was told.

    ⚠️ Deliberately NOT `frappe.sendmail`. This server carries real
    `@caffood.com` addresses (see `scripts/user_import.py`), and a scheduled job
    that emails real people from a dev box is how a test becomes an incident.
    A Notification Log shows in the bell menu and stays until read.

    🔴 **Idempotent on the SUBJECT, and that is not cosmetic.** The data side of
    `november_rollover()` is safely re-runnable, but the first version notified
    on every call — so a scheduler that fired twice, or an operator re-running
    it to check, sent HR the same alert again. An alarm that repeats itself is
    an alarm people learn to ignore, and the whole point of N1 and N2 is that
    somebody acts. A user with the same subject already UNREAD is skipped; once
    they read and dismiss it, a genuine recurrence can notify again.
    Caught by SCHED-NOTIFY, which found 16 logs where it expected 8.
    """
    told, already = [], []
    for user in hr_managers():
        if frappe.db.exists("Notification Log",
                            {"for_user": user, "subject": subject, "read": 0}):
            already.append(user)
            continue
        doc = frappe.new_doc("Notification Log")
        doc.for_user = user
        doc.subject = subject
        doc.email_content = message
        doc.type = "Alert"
        if doctype and name:
            doc.document_type = doctype
            doc.document_name = name
        doc.flags.ignore_permissions = True
        doc.insert()
        told.append(user)
    frappe.db.commit()
    if already:
        print(f"   ({len(already)} already have an unread '{subject}')")
    return told


# ─────────────────────────────────────────────────────────── N1
def next_year(today=None):
    return getdate(today or nowdate()).year + 1


def rollover_state(year):
    """What exists for `year` already. The basis for both plan and apply."""
    from caf.caf.holiday_lists import PH_LIST

    ph = PH_LIST.format(year=year)
    lists = frappe.get_all("Holiday List",
                           filters={"from_date": f"{year}-01-01"}, pluck="name")
    period = frappe.db.get_value("Leave Period", {"from_date": f"{year}-01-01",
                                                  "to_date": f"{year}-12-31"})
    cycles = frappe.get_all("Appraisal Cycle",
                            filters={"start_date": (">=", f"{year}-01-01"),
                                     "end_date": ("<=", f"{year}-12-31")},
                            pluck="name")
    ph_rows = frappe.db.count("Holiday", {"parent": ph}) if ph in lists else 0
    return {"year": year, "public_list": ph, "public_rows": ph_rows,
            "holiday_lists": sorted(lists), "leave_period": period,
            "cycles": sorted(cycles)}


def november_rollover_plan(year=None):
    """🔴 DRY RUN for N1. Writes nothing."""
    year = int(year or next_year())
    s = rollover_state(year)
    print(f"NOVEMBER ROLLOVER — {year}    🔴 DRY RUN, NOTHING WRITTEN")
    print("=" * 78)
    print(f"   Holiday Lists for {year}   : {len(s['holiday_lists'])}")
    for n in s["holiday_lists"]:
        print(f"      {n}")
    print(f"   public holidays entered  : {s['public_rows']}"
          f"   {'<- HR must fill these' if not s['public_rows'] else ''}")
    print(f"   Leave Period             : {s['leave_period'] or '— MISSING —'}")
    print(f"   Appraisal Cycles         : {len(s['cycles'])} of 12")
    print(f"   HR Managers to notify    : {hr_managers()}")
    print(f"\n🔴 Nothing was written.")
    return s


def november_rollover(year=None, notify=True):
    """N1. Idempotent — safe to run twice, and the scheduler may well do so."""
    from caf.caf.holiday_lists import PH_LIST

    year = int(year or next_year())
    before = rollover_state(year)

    # 1. The ONE list HR fills in. Empty by design — see the module header.
    #    The pattern lists are NOT created here: the `on_update` hook on this
    #    document builds them the moment HR saves the gazette dates, with the
    #    correct rest days and alternation.
    ph = PH_LIST.format(year=year)
    made = {}
    if not frappe.db.exists("Holiday List", ph):
        doc = frappe.new_doc("Holiday List")
        doc.holiday_list_name = ph
        doc.from_date = date(year, 1, 1)
        doc.to_date = date(year, 12, 31)
        doc.flags.ignore_permissions = True
        # ⚠️ `caf_regenerating` stops the on_update hook from firing on an empty
        # list and throwing through `collect_public_holidays`. Nothing to
        # regenerate from yet — that is the whole point of this document.
        frappe.flags.caf_regenerating = True
        try:
            doc.insert()
        finally:
            frappe.flags.caf_regenerating = False
        made[ph] = doc.name

    # 2. Leave Period
    period = before["leave_period"]
    if not period:
        doc = frappe.new_doc("Leave Period")
        doc.from_date = f"{year}-01-01"
        doc.to_date = f"{year}-12-31"
        doc.company = frappe.db.get_value("Employee", {"status": "Active"}, "company")
        doc.is_active = 1
        doc.flags.ignore_permissions = True
        doc.insert()
        period = doc.name

    # 3. Twelve Appraisal Cycles, named as the existing ones are: YYYY-MM
    cycles = []
    for m in range(1, 13):
        name = f"{year}-{m:02d}"
        if frappe.db.exists("Appraisal Cycle", name):
            continue
        last = 31 if m in (1, 3, 5, 7, 8, 10, 12) else (30 if m != 2 else
                                                        (29 if year % 4 == 0 and
                                                         (year % 100 or not year % 400)
                                                         else 28))
        doc = frappe.new_doc("Appraisal Cycle")
        doc.cycle_name = name
        doc.start_date = date(year, m, 1)
        doc.end_date = date(year, m, last)
        doc.status = CYCLE_STATUS
        doc.company = frappe.db.get_value("Employee", {"status": "Active"}, "company")
        doc.flags.ignore_permissions = True
        doc.insert()
        cycles.append(doc.name)
    frappe.db.commit()

    after = rollover_state(year)
    told = []
    if notify and not after["public_rows"]:
        told = notify_hr_managers(
            f"Enter {year} public holidays",
            f"Next year's skeleton is ready: {len(after['holiday_lists'])} Holiday "
            f"Lists, the {year} Leave Period and {len(after['cycles'])} Appraisal "
            f"Cycles.<br><br><b>{year} public holidays have not been entered.</b> "
            f"Open <b>{after['public_list']}</b> and add them from the gazette. "
            f"Every other list rebuilds itself the moment you save — the alternate "
            f"Saturdays included.<br><br>Until then, any date in {year} resolves "
            f"against a list with no public holidays on it.",
            "Holiday List", after["public_list"])

    print(f"holiday lists : {len(made)}  {sorted(made.values())}")
    print(f"leave period  : {period}")
    print(f"cycles created: {len(cycles)}  (now {len(after['cycles'])} of 12)")
    print(f"notified      : {told or '(nobody — public holidays already entered)'}")
    return {"lists": made, "period": period, "cycles": cycles, "notified": told}


def november_rollover_job():
    """Scheduler entry point. Guards the month so a mis-set cron cannot fire it.

    ⚠️ The guard is here rather than in the cron because a cron expression is
    easy to edit and hard to test; this refuses out loud and leaves a trace.
    """
    today = getdate(nowdate())
    if today.month != 11:
        frappe.log_error(f"november_rollover_job called in month {today.month}",
                         "CAF year rollover")
        return {"skipped": f"month {today.month}, not November"}
    return november_rollover()


# ─────────────────────────────────────────────────────────── N2
def weekly_roster_check(notify=True):
    """N2. Runs the roster detectors and TELLS somebody when one fires."""
    from caf.caf.page.shift_roster.shift_roster import (group_worked_rest_day,
                                                        holiday_gap)
    from caf.caf.shift_swap import half_done_swaps

    gap = holiday_gap() or {}
    group = group_worked_rest_day() or {}
    half = half_done_swaps() or {}
    counts = {"missing_holiday": gap.get("count", 0),
              "group_rest_work": group.get("count", 0),
              "half_done_swaps": half.get("count", 0)}
    total = sum(counts.values())

    told = []
    if notify and total:
        bits = []
        if counts["missing_holiday"]:
            bits.append(f"<b>{counts['missing_holiday']}</b> day(s) rostered as "
                        f"work that almost nobody attended — a public holiday may "
                        f"be missing from the Holiday List")
        if counts["group_rest_work"]:
            bits.append(f"<b>{counts['group_rest_work']}</b> rest day(s) a whole "
                        f"group worked")
        if counts["half_done_swaps"]:
            bits.append(f"<b>{counts['half_done_swaps']}</b> half-done trade(s) — "
                        f"one person's roster moved and the other's did not")
        told = notify_hr_managers(
            "Roster check found something",
            "The weekly roster check found:<br><br>" +
            "<br>".join(f"&bull; {b}" for b in bits) +
            "<br><br>Open <b>Shift &amp; Saturday Roster</b> for the detail.")

    print(f"missing holiday : {counts['missing_holiday']}")
    print(f"group rest work : {counts['group_rest_work']}")
    print(f"half-done swaps : {counts['half_done_swaps']}")
    print(f"notified        : {told or '(nothing to report)'}")
    return {"counts": counts, "notified": told}
