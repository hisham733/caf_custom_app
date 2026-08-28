"""The punch-requirement rule — three shapes, and the money guard on the third.

    bench --site <site> execute caf.tests.fingerlog.test_required_punches.run

MG's decision, 2026-08-22 (`ShiftTypeDesign_2026-08-22.md`). Splits
`caf_lunch_minutes`'s double duty: it keeps answering *"how much lunch do I
deduct?"*, and the new `caf_required_punches` answers *"what must be recorded?"*.

The cost of the old shape was 214 held days across 8 people — days that could never
become an Attendance record, inside a worklist so full of them that the six genuine
miss-punches were invisible.

Self-cleaning: builds its own throwaway shifts and logs, removes them in `finally`.
"""

import frappe
from frappe.utils import add_days, getdate, nowdate

from caf.caf import work_hours

RESULTS = []
PREFIX = "ZZ Test Punch Rule"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:30s} {'PASS' if ok else 'FAIL'}  {detail}")


def _shift(name, rule, allow_ot=0):
    full = f"{PREFIX} — {name}"
    if frappe.db.exists("Shift Type", full):
        frappe.delete_doc("Shift Type", full, force=True, ignore_permissions=True)
    d = frappe.new_doc("Shift Type")
    d.name = full
    d.__newname = full
    d.start_time = "08:00:00"
    d.end_time = "16:30:00"
    d.caf_lunch_minutes = 60          # ← lunch is DEDUCTED on every one of these
    d.caf_required_punches = rule
    d.caf_allow_ot = allow_ot
    for f in ("caf_work_mon", "caf_work_tue", "caf_work_wed", "caf_work_thu",
              "caf_work_fri"):
        setattr(d, f, 1)
    d.flags.ignore_permissions = True
    d.insert(ignore_permissions=True)
    return full


def _missing(shift, **punches):
    params = frappe.db.get_value(
        "Shift Type", shift,
        ["caf_lunch_minutes", "caf_required_punches", "start_time", "end_time"],
        as_dict=True)
    doc = frappe._dict({"time_in": "00:00:00", "break": "00:00:00",
                        "resume": "00:00:00", "out": "00:00:00"})
    doc.update(punches)
    return work_hours.missing_punches(doc, params)


def run():
    frappe.set_user("Administrator")
    made = []
    try:
        full = _shift("full", "In + Out + Lunch pair"); made.append(full)
        inout = _shift("inout", "In + Out only");        made.append(inout)
        either = _shift("either", "In OR Out only");     made.append(either)

        # ── RP1 — the default is unchanged ─────────────────────────────────
        m1 = _missing(full, time_in="08:00:00", out="16:30:00")
        check("RP1-FULL-NEEDS-LUNCH", m1 == ["break", "resume"],
              f"'In + Out + Lunch pair' still demands the pair — in+out alone is "
              f"missing {m1}. 12 of 14 shifts keep exactly today's behaviour")

        # ── RP2 — in+out satisfies the driver rule ─────────────────────────
        m2 = _missing(inout, time_in="08:00:00", out="16:30:00")
        check("RP2-INOUT-ACCEPTS-NO-LUNCH", m2 == [],
              f"'In + Out only' accepts in+out with no lunch pair ({m2}). This is "
              f"the rule for the drivers and Chen — 214 held days, none of which "
              f"needed new arithmetic")

        # ── RP3 — …but still demands both ends ─────────────────────────────
        m3 = _missing(inout, time_in="08:00:00")
        check("RP3-INOUT-STILL-NEEDS-OUT", m3 == ["out"],
              f"'In + Out only' still refuses a day with no tap-out ({m3}) — it "
              f"relaxes the LUNCH requirement, not the day's boundaries")

        # ── RP4 — one punch is enough on the third rule ────────────────────
        m4a = _missing(either, time_in="08:00:00")
        m4b = _missing(either, out="16:30:00")
        check("RP4-EITHER-ACCEPTS-ONE", m4a == [] and m4b == [],
              f"'In OR Out only' accepts in-alone {m4a} and out-alone {m4b}. One "
              f"option rather than two, because nobody is purely out-only — "
              f"Seriramulu is 10 in-only AND 3 out-only, so a split would force a "
              f"choice with no stable answer")

        # ── RP5 — an all-zero day is still an ABSENCE, not incomplete ──────
        m5 = _missing(either)
        check("RP5-EITHER-ALLZERO-IS-ABSENT", m5 == [],
              f"an all-zero row on 'In OR Out only' is still complete BY ABSENCE "
              f"({m5}) — he did not come, which is an observation, not a gap. If "
              f"this broke, every rest day for these 3 people would be held")

        # ── RP6 — 🔴 the money guard ───────────────────────────────────────
        refused = False
        try:
            d = frappe.get_doc("Shift Type", either)
            d.caf_allow_ot = 1
            d.flags.ignore_permissions = True
            d.save(ignore_permissions=True)
        except Exception as e:
            refused = "cannot also allow overtime" in frappe.utils.strip_html(str(e))
        check("RP6-EITHER-FORBIDS-OT", refused,
              "a shift crediting a full day from ONE punch cannot also allow "
              "overtime. On that rule the hours are ASSUMED, not measured — OT "
              "would stack an unverifiable number on an unverified one. Enforced "
              "server-side because the form lock is escapable by API, Data Import "
              "and bench execute")

        # ── RP7 — an unset shift behaves exactly as before ─────────────────
        legacy = _shift("legacy", None); made.append(legacy)
        m7 = _missing(legacy, time_in="08:00:00", out="16:30:00")
        check("RP7-UNSET-FALLS-BACK", m7 == ["break", "resume"],
              f"a shift with the new field UNSET falls back to the old "
              f"caf_lunch_minutes gate ({m7}) — every existing shift keeps its "
              f"behaviour until somebody chooses otherwise. Nothing changes by "
              f"surprise on migrate")

    finally:
        frappe.set_user("Administrator")
        for s in made:
            if frappe.db.exists("Shift Type", s):
                frappe.delete_doc("Shift Type", s, force=True,
                                  ignore_permissions=True)
        frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
