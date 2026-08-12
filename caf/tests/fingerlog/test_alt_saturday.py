"""Alternate Saturdays — the design's own scenarios. OD-67 · R1 · R3 · R5 · OD-66.

    bench --site <site> execute caf.tests.fingerlog.test_alt_saturday.run

WHY MOST OF THIS IS READ-ONLY
-----------------------------
Almost every assertion here interrogates **configuration and resolution**, not
documents, so the suite creates nothing and can eat nothing (§F4). Only ALT7 needs
a fixture, and it lives in **June** — the month the importer never touched — and is
removed in a `finally`.

🔴 THE ONE THAT MATTERS IS ALT3
-------------------------------
A mirror pair carries **identical weekday flags** — both `caf_work_sat = 1`. If
`day_type` still came from those flags the two shifts would be indistinguishable
and the whole design would be inert. ALT3 is the assertion that R1 actually
changed the source of truth; everything else is the machinery around it.
"""

import frappe
from frappe.utils import add_days, getdate

from caf.caf import holiday_lists
from caf.caf.shift_resolution import (get_holiday_list, get_shift_for_date,
                                      is_rest_day, resolve_day_type, works_on)

PAIR_A = "8:30am Alt Sat 1st-3rd"
PAIR_B = "8:30am Alt Sat 2nd-4th"
PROD_A = "8-5 Alt Sat 1st-3rd"
PROD_B = "8-5 Alt Sat 2nd-4th"

GROUP_A = "HR-EMP-00003"        # Too Poh Chin
GROUP_B = "HR-EMP-00004"        # Afiza binti Mustafa

# 🔴 JUNE for the one fixture. July is the importer's (§F4d).
FIX_EMP = "HR-EMP-00016"        # 8am Schedule, Mon-Sat, not one of the eight
D_SAT = "2026-06-06"
NO_SAT_SHIFT = "8am no OT no Sat"

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def saturdays(lo, hi):
    out, d = [], getdate(lo)
    while d <= getdate(hi):
        if d.weekday() == 5:
            out.append(d)
        d = add_days(d, 1)
    return out


def run():
    cleanup()
    try:
        # ------------------------------------------------------------- ALT3 🔴
        # Both shifts have caf_work_sat = 1. Only the Holiday List can separate
        # them, so this fails the instant day_type goes back to reading the flags.
        flags = {s: frappe.db.get_value("Shift Type", s, "caf_work_sat")
                 for s in (PAIR_A, PAIR_B)}
        sats = saturdays("2026-04-11", "2026-06-30")
        verdicts = [(d, is_rest_day(get_holiday_list(GROUP_A, PAIR_A, d), d, PAIR_A),
                     is_rest_day(get_holiday_list(GROUP_B, PAIR_B, d), d, PAIR_B))
                    for d in sats]
        opposed = [v for v in verdicts if v[1] != v[2]]
        check("ALT3", all(flags.values()) and len(opposed) == len(verdicts),
              f"a mirror pair resolves ONE DATE TWO WAYS on all {len(verdicts)} "
              f"Saturdays tested, while carrying identical flags "
              f"(caf_work_sat={flags}) — only the Holiday List can tell them apart, "
              f"which is the whole of R1")

        # ------------------------------------------------------------- ALT1 🔴
        # A public holiday is taken by everyone and does NOT advance the walk, so
        # the Saturday after it is the COMPLEMENT of the Saturday before it.
        ph_sat = getdate("2026-03-21")          # HARI RAYA PUASA, a Saturday
        before, after = add_days(ph_sat, -7), add_days(ph_sat, 7)
        rest_ph = is_rest_day(get_holiday_list(GROUP_A, PAIR_A, ph_sat), ph_sat, PAIR_A)
        b = is_rest_day(get_holiday_list(GROUP_A, PAIR_A, before), before, PAIR_A)
        a_ = is_rest_day(get_holiday_list(GROUP_A, PAIR_A, after), after, PAIR_A)
        dt_ph, _ = resolve_day_type(GROUP_A, ph_sat)
        check("ALT1", dt_ph == "Holiday" and b == a_,
              f"{ph_sat} resolves {dt_ph} for everyone, and it does NOT advance the "
              f"sequence: {before}={'rest' if b else 'work'} ➜ {after}="
              f"{'rest' if a_ else 'work'} — the same, because the alternation "
              f"waited. ⚠️ if the holiday advanced it, these two would differ")

        # ------------------------------------------------------------- ALT2
        # A 5-Saturday month must alternate straight through into the next month:
        # the sequence is a running walk, not an nth-of-month rule.
        may = saturdays("2026-05-01", "2026-05-31")
        chain = [is_rest_day(get_holiday_list(GROUP_A, PAIR_A, d), d, PAIR_A)
                 for d in may + saturdays("2026-06-01", "2026-06-13")]
        alternates = all(chain[i] != chain[i + 1] for i in range(len(chain) - 1))
        check("ALT2", len(may) == 5 and alternates,
              f"May 2026 has {len(may)} Saturdays and the pattern alternates through "
              f"all of them and on into June without resetting: "
              f"{['rest' if c else 'work' for c in chain]}")

        # ------------------------------------------------------------- ALT5 🔴
        # A one-way mirror link is a half-configured pair, and it fails in the
        # direction nobody tests.
        broken = []
        for s in (PAIR_A, PAIR_B, PROD_A, PROD_B):
            m = frappe.db.get_value("Shift Type", s, "caf_sat_mirror")
            if not m or frappe.db.get_value("Shift Type", m, "caf_sat_mirror") != s:
                broken.append(s)
        check("ALT5", not broken,
              f"every mirror link is BIDIRECTIONAL: {len(broken)} broken of 4. "
              f"The swap validation reads this field, never the shift name")

        # ------------------------------------------------------------ ALT-YEAR
        # OD-66. After R1 the list carries every rest day, so a date outside the
        # list's year would return NO rest days at all — silently.
        hl25 = get_holiday_list(FIX_EMP, "8am Schedule", "2025-06-07")
        hl26 = get_holiday_list(FIX_EMP, "8am Schedule", "2026-03-21")
        dt25, _ = resolve_day_type(FIX_EMP, "2025-06-07")
        check("ALT-YEAR", "2025" in (hl25 or "") and "2026" in (hl26 or "")
              and dt25 == "Holiday",
              f"a 2025 date resolves against {hl25} (not {hl26}) and 2025-06-07 "
              f"HARI RAYA HAJI is correctly {dt25} — without the year hop it would "
              f"search the 2026 list, find nothing and say Workday")

        # ----------------------------------------------------------- ALT-GUARD
        # Refusing to walk a year it cannot see is the difference between a wrong
        # calendar and a loud one: one Saturday holiday missed inverts the rest.
        try:
            holiday_lists.alt_saturday_rest_days(2024, "2024-01-06", True)
            threw = ""
        except Exception as e:
            threw = str(e)
        check("ALT-GUARD", "2024" in threw and "does not exist" in threw,
              f"walking a year with no public-holiday list REFUSES rather than "
              f"guessing: {threw[:110] or '🔴 it did not throw'}")

        # ---------------------------------------------------------- ALT-ANCHOR
        anchor = frappe.db.get_value("Shift Type", PAIR_A,
                                     ["caf_sat_anchor_date", "caf_sat_anchor"],
                                     as_dict=True)
        ad = getdate(anchor.caf_sat_anchor_date)
        actual = is_rest_day(get_holiday_list(GROUP_A, PAIR_A, ad), ad, PAIR_A)
        mirror_actual = is_rest_day(get_holiday_list(GROUP_B, PAIR_B, ad), ad, PAIR_B)
        check("ALT-ANCHOR", actual == (anchor.caf_sat_anchor == "Rest")
              and mirror_actual != actual,
              f"the anchor is honoured: {PAIR_A} is configured "
              f"{anchor.caf_sat_anchor!r} on {ad} and resolves "
              f"{'rest' if actual else 'work'}; its mirror does the opposite")

        # ------------------------------------------------------------- ALT-IDEM
        before_rows = frappe.db.count("Holiday", {"parent": "CAF Alt Sat 1st-3rd 2026"})
        holiday_lists.generate_holiday_lists(2026)
        after_rows = frappe.db.count("Holiday", {"parent": "CAF Alt Sat 1st-3rd 2026"})
        check("ALT-IDEM", before_rows == after_rows and before_rows > 0,
              f"regenerating is stable: {before_rows} rows ➜ {after_rows}. "
              f"January's re-run must not shift anybody's Saturdays")

        # ------------------------------------------------------------- ALT7 🔴
        # Stock's daily job flips an expired assignment to Inactive with a raw
        # db_set. Before R5 that removed it from resolution, so re-resolving a
        # historical date fell back to default_shift and returned Workday.
        clash = frappe.db.count("Shift Assignment",
                                {"employee": FIX_EMP, "start_date": D_SAT,
                                 "docstatus": ("<", 2)})
        sa = frappe.new_doc("Shift Assignment")
        sa.employee = FIX_EMP
        sa.company = frappe.db.get_value("Employee", FIX_EMP, "company")
        sa.shift_type = NO_SAT_SHIFT
        sa.start_date = sa.end_date = D_SAT
        sa.status = "Active"
        sa.flags.ignore_permissions = True
        sa.insert()
        sa.submit()

        active_dt, active_shift = resolve_day_type(FIX_EMP, D_SAT)
        # exactly what stock's scheduled job does — no hook, no Version
        frappe.db.set_value("Shift Assignment", sa.name, "status", "Inactive",
                            update_modified=False)
        frappe.db.commit()
        expired_dt, expired_shift = resolve_day_type(FIX_EMP, D_SAT)

        check("ALT7", clash == 0 and active_dt == "Restday" and expired_dt == "Restday"
              and expired_shift == NO_SAT_SHIFT,
              f"an EXPIRED assignment still tells the truth about its own past date: "
              f"Active ➜ {active_dt} via {active_shift}; after stock's daily job "
              f"marks it Inactive ➜ {expired_dt} via {expired_shift}. "
              f"Before R5 the second was Workday, and a punchless Workday is an "
              f"Absent that FBR37 counts")

        # ------------------------------------------------------------- ALT-LOCK
        df = frappe.get_meta("Shift Assignment").get_field("status")
        check("ALT-LOCK", not df.allow_on_submit,
              f"and a PERSON can no longer set it: status.allow_on_submit="
              f"{df.allow_on_submit} (R3). Stock still writes it through db_set, "
              f"which is what the expiry job and on_cancel use")
    finally:
        cleanup()
        frappe.db.commit()

    print("\n=== Alternate Saturdays — OD-67 / R1 / R3 / R5 / OD-66 ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:11s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed


def cleanup():
    """Scoped to this suite's employee AND its single June date (§F4)."""
    for r in frappe.get_all("Shift Assignment",
                            filters={"employee": FIX_EMP, "start_date": D_SAT},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Shift Assignment", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Shift Assignment", r.name, ignore_permissions=True,
                          force=True)
    frappe.db.commit()
