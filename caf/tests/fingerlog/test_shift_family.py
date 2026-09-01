"""The shift-family label, and the clone invariant the eight employees rest on.

    bench --site <site> execute caf.tests.fingerlog.test_shift_family.run

MG + HR, 2026-09-01: *"shift_type not a 'tree' but cheaply group by start + end +
lunch duration."* Two things are asserted here, and each one has already been
wrong once or would have been expensive to get wrong:

  SF1..SF3   the LABEL, because `str(timedelta)` drops the leading zero and the
             first dry run produced `6:00:-14:30 · 60` on all fourteen shifts
  SF5..SF7   the CLONE, because the whole safety argument for moving eight people
             is *"same contracted day, only the gate differs"*. If a clone ever
             drifts from its source on start, end, lunch, weekday flags or
             holiday list, that argument silently stops being true and somebody's
             pay basis moves without anyone deciding it should.

Self-cleaning: builds its own throwaway shift, removes it in `finally`.
"""

from datetime import time, timedelta

import frappe

from caf.caf.overrides.shift_type import _hhmm, derive_family

RESULTS = []
PREFIX = "ZZ Test Shift Family"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:26s} {'PASS' if ok else 'FAIL'}  {detail}")


def run():
    frappe.set_user("Administrator")
    made = []
    try:
        # ── SF1 — 🔴 the bug that shipped in the first dry run ──────────────
        td = _hhmm(timedelta(hours=6))
        check("SF1-TIMEDELTA-PADS", td == "06:00",
              f"a Time field read from the DATABASE arrives as a timedelta, whose "
              f"str() is '6:00:00' with NO leading zero — so str(t)[:5] gives "
              f"'6:00:'. _hhmm gives {td!r}. Measured 2026-09-01: this produced "
              f"'6:00:-14:30 · 60' on all 14 shifts before it was fixed")

        # ── SF2 — …and a form value still works ────────────────────────────
        check("SF2-TIME-OBJECT-WORKS", _hhmm(time(8, 30)) == "08:30",
              "a datetime.time — what a freshly-typed form value is — still gives "
              "'08:30'. This is WHY SF1's bug survives casual testing: the answer "
              "depends on whether the value came from the DB or the form")

        # ── SF3 — the label is start · end · lunch, and nothing else ────────
        label = derive_family(frappe._dict({
            "start_time": timedelta(hours=8, minutes=30),
            "end_time": timedelta(hours=17, minutes=30),
            "caf_lunch_minutes": 60}))
        check("SF3-LABEL-SHAPE", label == "08:30-17:30 · 60",
              f"the family is the CONTRACTED DAY: {label!r}. Chosen because "
              f"net_minutes() is exactly end - start - lunch, so two shifts in one "
              f"family produce the same contracted hours — moving somebody between "
              f"them changes the RULES and never the pay basis")

        # ── SF4 — lunch separates two shifts with identical hours ──────────
        a = derive_family(frappe._dict({"start_time": timedelta(hours=8, minutes=30),
                                        "end_time": timedelta(hours=17),
                                        "caf_lunch_minutes": 60}))
        b = derive_family(frappe._dict({"start_time": timedelta(hours=8, minutes=30),
                                        "end_time": timedelta(hours=17),
                                        "caf_lunch_minutes": 0}))
        check("SF4-LUNCH-SPLITS", a != b,
              f"`8.30am Roster` ({a}) and `8:30am no Sat` ({b}) run the same clock "
              f"hours but contract different WORK — 8h against 8.5h. Grouping on "
              f"start+end alone would have hidden that")

        # ── SF5 — a new shift is never family-less ─────────────────────────
        name = f"{PREFIX} — auto"
        if frappe.db.exists("Shift Type", name):
            frappe.delete_doc("Shift Type", name, force=True, ignore_permissions=True)
        d = frappe.new_doc("Shift Type")
        d.__newname = name
        d.start_time = "07:15:00"
        d.end_time = "16:45:00"
        d.caf_lunch_minutes = 45
        d.flags.ignore_permissions = True
        d.insert(ignore_permissions=True)
        made.append(name)
        check("SF5-AUTOFILL-ON-INSERT", d.caf_shift_family == "07:15-16:45 · 45",
              f"a shift saved with no family gets one: {d.caf_shift_family!r}. The "
              f"hook fills it so nobody has to remember, and HR is not asked to "
              f"type a value that is already implied by three fields they set")

        # ── SF6 — …but HR's own wording is never overwritten ───────────────
        d.caf_shift_family = "Bakery early"
        d.save(ignore_permissions=True)
        d.reload()
        check("SF6-RESPECTS-HR-LABEL", d.caf_shift_family == "Bakery early",
              f"a label a person typed survives the next save: "
              f"{d.caf_shift_family!r}. Fill-when-blank, never overwrite — "
              f"otherwise the field is not HR's to own and the 'HR can group them "
              f"their way' half of MG's decision is a lie")

        # ── SF7 — 🔴 the clone invariant the eight people rest on ───────────
        from caf.scripts.shift_punch_rule_rollout import NEW_SHIFTS
        SAME = ("start_time", "end_time", "caf_lunch_minutes", "holiday_list",
                "caf_work_mon", "caf_work_tue", "caf_work_wed", "caf_work_thu",
                "caf_work_fri", "caf_work_sat", "caf_work_sun")
        drift, checked = [], 0
        for spec in NEW_SHIFTS:
            if not frappe.db.exists("Shift Type", spec["name"]):
                continue                      # not rolled out on this site yet
            new = frappe.db.get_value("Shift Type", spec["name"], SAME, as_dict=True)
            src = frappe.db.get_value("Shift Type", spec["clone_of"], SAME, as_dict=True)
            checked += 1
            drift += [f"{spec['name']}.{f}" for f in SAME
                      if str(new[f]) != str(src[f])]
        check("SF7-CLONE-STAYS-IDENTICAL", checked > 0 and not drift,
              f"{checked} punch-rule shift(s) still match their source on the "
              f"contracted day, the weekday flags and the holiday list "
              f"({drift or 'no drift'}). This is the ENTIRE safety argument for "
              f"moving 8 people: same hours, same rest days, only the gate "
              f"differs. Editing one of these shifts' times would break it "
              f"silently, and nothing else would notice")

    finally:
        frappe.set_user("Administrator")
        for s in made:
            if frappe.db.exists("Shift Type", s):
                frappe.delete_doc("Shift Type", s, force=True, ignore_permissions=True)
        frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
