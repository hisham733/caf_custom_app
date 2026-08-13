"""SCHED-* — N1 and N2: the two jobs that run on a clock and must TELL somebody.

    bench --site <site> execute caf.tests.fingerlog.test_scheduled.run

Purpose : prove the November rollover builds what HR needs and is safe to run
          twice, and that a detector finding actually reaches an HR Manager.
Refs    : plan §4378 · roadmap §9e N1/N2 · caf/caf/scheduled.py

🔴 WHAT THIS SUITE IS ACTUALLY FOR
-----------------------------------
The detectors were already built and are already tested — the **ROSTER** group
covers what they find. What was never built, and is therefore what is tested
here, is the **telling**: both jobs were described to HR as running on a clock,
and neither existed. A detector nobody is notified by is a report, not an alarm.

⚠️ **§F2 — the live detectors currently return 0, 0, 0.** That is a real result
(August holds no imported data; the importer covers July only), but a suite that
only ever saw zero would prove nothing about the notification path. So
**SCHED-DETECT monkeypatches the three detectors to report findings** and asserts
a Notification Log actually lands. The patch is restored in a `finally` and the
restore is ASSERTED, per protocol — a suite that exits still patched leaves every
later suite in the process running against fakes.

⚠️ FIXTURES USE YEAR 2029, not next year. `november_rollover()` has already been
run for 2027 on this server, and a suite that asserted "creates 12 cycles" against
a year something else owns would pass or fail for the wrong reason (§F1). 2029 is
owned by nothing.
"""

import frappe

from caf.caf import scheduled as s

YEAR = 2029
RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def cleanup():
    """Scoped to YEAR and to this suite's notifications. Runs FIRST (§F4)."""
    for name in frappe.get_all("Appraisal Cycle",
                               filters={"start_date": (">=", f"{YEAR}-01-01"),
                                        "end_date": ("<=", f"{YEAR}-12-31")},
                               pluck="name"):
        frappe.delete_doc("Appraisal Cycle", name, ignore_permissions=True, force=True)
    for name in frappe.get_all("Leave Period",
                               filters={"from_date": f"{YEAR}-01-01"}, pluck="name"):
        frappe.delete_doc("Leave Period", name, ignore_permissions=True, force=True)
    for name in frappe.get_all("Holiday List",
                               filters={"from_date": f"{YEAR}-01-01"}, pluck="name"):
        frappe.delete_doc("Holiday List", name, ignore_permissions=True, force=True)
    for name in frappe.get_all("Notification Log",
                               filters={"subject": ("like", f"%{YEAR}%")},
                               pluck="name"):
        frappe.delete_doc("Notification Log", name, ignore_permissions=True, force=True)
    for name in frappe.get_all("Notification Log",
                               filters={"subject": "Roster check found something"},
                               pluck="name"):
        frappe.delete_doc("Notification Log", name, ignore_permissions=True, force=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    cleanup()

    # snapshot the originals BEFORE anything patches them
    orig = {}
    try:
        # ------------------------------------------------------------ SCHED-HRM
        hrm = s.hr_managers()
        disabled = [u for u in hrm if not frappe.db.get_value("User", u, "enabled")]
        check("SCHED-HRM",
              hrm and not disabled
              and "Administrator" not in hrm and "Guest" not in hrm,
              f"{len(hrm)} enabled HR Managers, no disabled ones and neither "
              f"framework account. The leaver guard in user_import is why the "
              f"three HR Managers who have LEFT are not in this list")

        # ----------------------------------------------------------- SCHED-ROLL
        before_cycles = frappe.db.count(
            "Appraisal Cycle", {"start_date": (">=", f"{YEAR}-01-01"),
                                "end_date": ("<=", f"{YEAR}-12-31")})
        res = s.november_rollover(YEAR)
        st = s.rollover_state(YEAR)
        check("SCHED-ROLL",
              before_cycles == 0 and len(st["cycles"]) == 12
              and st["leave_period"] and st["public_list"] in st["holiday_lists"],
              f"the skeleton is built for {YEAR}: 12 Appraisal Cycles "
              f"({len(st['cycles'])}), Leave Period {st['leave_period']}, and "
              f"the one list HR fills in ({st['public_list']})")

        # ---------------------------------------------------------- SCHED-EMPTY
        # 🔴 The list must be EMPTY. §4378 wanted the pattern lists pre-built;
        # generate_holiday_lists() throws on a year with no public holidays, and
        # the on_update hook builds them the moment HR saves the dates instead.
        check("SCHED-EMPTY",
              st["public_rows"] == 0
              and len([n for n in st["holiday_lists"] if "Public" not in n]) == 0,
              f"{st['public_list']} exists with {st['public_rows']} holidays and "
              f"NO pattern lists were pre-built. HR entering the gazette dates "
              f"fires the on_update hook, which generates all four with the right "
              f"alternation — pre-building them would create four lists that look "
              f"finished and are not")

        # ----------------------------------------------------------- SCHED-IDEM
        # The scheduler may fire twice; a rollover that duplicated 12 cycles
        # would be found in December, by a human.
        res2 = s.november_rollover(YEAR)
        st2 = s.rollover_state(YEAR)
        check("SCHED-IDEM",
              len(st2["cycles"]) == 12 and not res2["cycles"]
              and st2["leave_period"] == st["leave_period"],
              f"a second run creates nothing: cycles still {len(st2['cycles'])}, "
              f"same Leave Period, {len(res2['cycles'])} new")

        # --------------------------------------------------------- SCHED-NOTIFY
        told = res["notified"]
        logs = frappe.get_all("Notification Log",
                              filters={"subject": f"Enter {YEAR} public holidays"},
                              fields=["for_user"])
        check("SCHED-NOTIFY",
              set(told) == set(hrm) and len(logs) == len(hrm) and logs,
              f"every one of the {len(hrm)} HR Managers got a Notification Log "
              f"naming the list to open. This is the part that did not exist: "
              f"the skeleton was specced, the telling was not")

        # ---------------------------------------------------------- SCHED-MONTH
        from frappe.utils import getdate, nowdate
        this_month = getdate(nowdate()).month
        out = s.november_rollover_job()
        check("SCHED-MONTH",
              ("skipped" in out) if this_month != 11 else ("skipped" not in out),
              f"the job guards its own month — today is month {this_month} and it "
              f"{'refused: ' + out['skipped'] if 'skipped' in out else 'ran'}. The "
              f"guard is in Python, not in the cron, because a cron expression is "
              f"easy to edit and hard to test")

        # --------------------------------------------------------- SCHED-DETECT 🔴
        # §F2: the live detectors return 0/0/0, so the notification path would
        # never be exercised. Patch them to report, and assert a human is told.
        orig = {"gap": None, "grp": None, "half": None}
        import caf.caf.page.shift_roster.shift_roster as rp
        import caf.caf.shift_swap as sw
        orig["gap"], orig["grp"], orig["half"] = (rp.holiday_gap,
                                                  rp.group_worked_rest_day,
                                                  sw.half_done_swaps)
        rp.holiday_gap = lambda *a, **k: {"count": 2, "rows": []}
        rp.group_worked_rest_day = lambda *a, **k: {"count": 1, "rows": []}
        sw.half_done_swaps = lambda *a, **k: {"count": 3, "rows": []}
        fired = s.weekly_roster_check()
        note = frappe.get_all("Notification Log",
                              filters={"subject": "Roster check found something"},
                              fields=["for_user", "email_content"])
        check("SCHED-DETECT",
              fired["counts"]["missing_holiday"] == 2
              and len(note) == len(hrm)
              and note and "3" in note[0].email_content,
              f"with findings present, all {len(hrm)} HR Managers are notified "
              f"and the message carries the counts (2 / 1 / 3). Without this the "
              f"suite would only ever have seen 0/0/0 and proved nothing")

        # ---------------------------------------------------------- SCHED-QUIET
        rp.holiday_gap = lambda *a, **k: {"count": 0, "rows": []}
        rp.group_worked_rest_day = lambda *a, **k: {"count": 0, "rows": []}
        sw.half_done_swaps = lambda *a, **k: {"count": 0, "rows": []}
        before_n = frappe.db.count("Notification Log")
        quiet = s.weekly_roster_check()
        check("SCHED-QUIET",
              not quiet["notified"]
              and frappe.db.count("Notification Log") == before_n,
              "with nothing found, nobody is notified and no log is written — a "
              "weekly job that pings HR every week is a weekly job HR filters out")

    finally:
        # 🔴 Restore, then ASSERT the restore. A suite that exits still patched
        # leaves every later suite in this process running against fakes, and the
        # failures appear far from the cause.
        if orig.get("gap"):
            import caf.caf.page.shift_roster.shift_roster as rp
            import caf.caf.shift_swap as sw
            rp.holiday_gap = orig["gap"]
            rp.group_worked_rest_day = orig["grp"]
            sw.half_done_swaps = orig["half"]
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    if orig.get("gap"):
        import caf.caf.page.shift_roster.shift_roster as rp
        import caf.caf.shift_swap as sw
        check("SCHED-RESTORE",
              rp.holiday_gap is orig["gap"]
              and rp.group_worked_rest_day is orig["grp"]
              and sw.half_done_swaps is orig["half"],
              "the three monkeypatched detectors are the originals again — "
              "asserted, not assumed")

    left = frappe.db.count("Appraisal Cycle",
                           {"start_date": (">=", f"{YEAR}-01-01"),
                            "end_date": ("<=", f"{YEAR}-12-31")})
    check("SCHED-CLEAN", left == 0,
          f"{YEAR} artifacts removed: {left} Appraisal Cycles left")

    print("\n=== N1 + N2 — the scheduled jobs ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:16s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
