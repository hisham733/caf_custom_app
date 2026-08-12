"""Alternate-Saturday shifts: schema, shifts, holiday lists, assignment.

    bench --site <site> execute caf.scripts.alt_saturday_setup.setup

Framework §6.7 (design) · §6.9 (verified against Ingress) · §6.10 · §6.12 (HR).
Decisions implemented here: OD-67 (mirror shifts), OD-70 (`caf_shift_code`),
I1 (names), I2 (anchor), I3 (forward-only regeneration), I9 (the three fields).

WHAT A MIRROR PAIR IS, AND WHY IT IS NOT A NAME
-----------------------------------------------
Two Shift Types with identical times and rules, differing **only** in which
Saturdays their Holiday List marks as rest. `caf_sat_mirror` links each to the
other, and **that link — never the name — is what the swap validation reads**
(§6.9). The names carry `1st-3rd` / `2nd-4th` because MG asked for the Saturdays
to be visible, but they are documentation: after the first public holiday of a
year the numbers stop being literally true, because a holiday does not advance
the sequence.

THE SEQUENCE, VERIFIED IN THE DATA
----------------------------------
Saturdays alternate between the pair, walked in order from a stored anchor. A
**public holiday is taken by everyone and does NOT advance the walk** — measured:

    2026-03-14  resting: Afiza, Hazwani, Too Poh Chin
    2026-03-21  PUBLIC HOLIDAY
    2026-03-28  resting: Najwa, Nurfarahayu, Seow    <- the exact complement of 03-14

So the calendar cannot be computed from a date alone; it must be walked. That is
also why a public holiday added mid-year would flip every later Saturday, and why
regeneration is **forward-only** (I3).

RE-RUNNABLE: every step checks before it writes, so this can be run repeatedly.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# ---------------------------------------------------------------- the schema
#
# ⚠️ `caf_sat_mirror` and `caf_shift_code` are NOT protected by `read_only`.
# Measured on this site (PROTOCOL §C4b): forcing `read_only = 1` on a field and
# then calling `doc.save()` stores the value anyway — it is a form decoration, not
# a lock. Immutability, if it is wanted, needs a controller guard, the same
# conclusion OD-61 and OD-62 reached. These are left writable and asserted by the
# test suite instead.
FIELDS = {
    "Shift Type": [
        {
            "fieldname": "caf_shift_code",
            "label": "Shift Code",
            "fieldtype": "Data",
            "insert_after": "caf_shift_rules_section",
            "unique": 1,
            "description": (
                "Stable handle for code and tests. Shift Type is autonamed 'prompt', "
                "so its NAME is a human label that HR may change; this does not change. "
                "OD-70."
            ),
        },
        {
            "fieldname": "caf_alt_sat_section",
            "label": "Alternate Saturday",
            "fieldtype": "Section Break",
            "insert_after": "caf_work_sun",
            "collapsible": 1,
        },
        {
            "fieldname": "caf_alt_sat",
            "label": "Alternate Saturday Shift",
            "fieldtype": "Check",
            "insert_after": "caf_alt_sat_section",
            "default": "0",
            "description": (
                "This shift works only some Saturdays, alternating with its mirror. "
                "The Holiday List generator uses this to decide which shifts need a "
                "walked list rather than a plain weekly pattern."
            ),
        },
        {
            "fieldname": "caf_sat_mirror",
            "label": "Mirror Shift",
            "fieldtype": "Link",
            "options": "Shift Type",
            "insert_after": "caf_alt_sat",
            "depends_on": "eval:doc.caf_alt_sat",
            "description": (
                "The other half of the pair. The swap validation reads THIS, never the "
                "shift name. Must be set on both shifts — a one-way link is a "
                "half-configured pair and fails in the direction nobody tests."
            ),
        },
        {
            "fieldname": "caf_sat_anchor_date",
            "label": "Sequence Anchor Date",
            "fieldtype": "Date",
            "insert_after": "caf_sat_mirror",
            "depends_on": "eval:doc.caf_alt_sat",
            "description": (
                "The Saturday the alternation is anchored on. The generator walks "
                "forward from here, skipping public holidays without advancing."
            ),
        },
        {
            "fieldname": "caf_sat_anchor",
            "label": "On the Anchor Saturday",
            "fieldtype": "Select",
            "options": "\nRest\nWork",
            "insert_after": "caf_sat_anchor_date",
            "depends_on": "eval:doc.caf_alt_sat",
            "description": "What THIS shift does on the anchor Saturday. Its mirror does the opposite.",
        },
    ]
}

# `caf_allow_ot` currently sits directly under the section; the code field goes
# above it, so its anchor moves.
RECHAIN = ("caf_allow_ot", "caf_shift_code")


def ensure_fields():
    create_custom_fields(FIELDS, ignore_validate=True)

    fieldname, new_anchor = RECHAIN
    name = frappe.db.get_value("Custom Field",
                               {"dt": "Shift Type", "fieldname": fieldname}, "name")
    if name and frappe.db.get_value("Custom Field", name, "insert_after") != new_anchor:
        frappe.db.set_value("Custom Field", name, "insert_after", new_anchor)

    frappe.clear_cache(doctype="Shift Type")
    frappe.db.commit()

    meta = frappe.get_meta("Shift Type")
    present = [f["fieldname"] for f in FIELDS["Shift Type"]
               if meta.get_field(f["fieldname"])]
    missing = [f["fieldname"] for f in FIELDS["Shift Type"]
               if not meta.get_field(f["fieldname"])]
    print(f"  fields present: {len(present)}/{len(FIELDS['Shift Type'])}")
    for f in present:
        print(f"    ok   {f}")
    for f in missing:
        print(f"    🔴 MISSING {f}")
    return not missing


# ------------------------------------------------------------- the four shifts
#
# 🔴 THE NUMBERS NAME THE SATURDAYS THE SHIFT RESTS ON — MG, 2026-08-12.
# This was ambiguous for three exchanges and would have inverted the calendar for
# all eight employees. It now matches production's own list names (`Alternate
# First Saturday OFF 2026`), so the two systems cannot invert against each other.
#
# The anchor is 2026-01-03, the first Saturday of the year, and it is MEASURED:
# on that date Too Poh Chin, Nur Najwa and Seow Zi Ying rested. It cannot be
# pushed back to 2025 — the practice did not exist then (zero rest Saturdays
# across all 22 Saturdays of 2025-08 to 2025-12) — nor to 2024, which has no
# public-holiday list to walk through.
# 🔴 ANCHORED IN APRIL, NOT JANUARY — MG's decision, 2026-08-12, after the
# January anchor was tried and measured.
#
# January looked like the obvious choice and it is the wrong one. Two things live
# in Jan–Mar that poison a walk started there:
#
#   • the company holiday of 14 February, which HR is correcting SEVEN MONTHS
#     LATE. The roster never knew about it on the day, so the real sequence
#     stepped over it — and telling the walk about it now re-phases everything
#     after, dropping agreement with the Ingress record from 26/32 to 13/32.
#   • February's mislabelled day types — Najwa and Seow recorded as WORKING on
#     21 Feb and never clocking in, and the same shape on the 28th. The
#     observations there cannot referee anything.
#
# April onward is clean, and it already agreed with the walk. So the anchor sits
# in it. 2026-04-11 rather than 04-04, because 04-04 is the company-wide shutdown
# where all six rested and therefore identifies no group at all.
#
# Measured on 2026-04-11: group B (Afiza, Nurfarahayu, Hazwani) rested, group A
# (Too Poh Chin, Najwa, Seow) worked.
ANCHOR = "2026-04-11"

SHIFTS = [
    # (new shift, cloned from, code, rests on the anchor Saturday)
    ("8-5 Alt Sat 1st-3rd",     "Special 8-5",     "ALTSAT_85_A",  False),
    ("8-5 Alt Sat 2nd-4th",     "Special 8-5",     "ALTSAT_85_B",  True),
    ("8:30am Alt Sat 1st-3rd",  "8:30am Schedule", "ALTSAT_830_A", False),
    ("8:30am Alt Sat 2nd-4th",  "8:30am Schedule", "ALTSAT_830_B", True),
]

MIRRORS = [("8-5 Alt Sat 1st-3rd", "8-5 Alt Sat 2nd-4th"),
           ("8:30am Alt Sat 1st-3rd", "8:30am Alt Sat 2nd-4th")]

# What the shift's rules are made of. Everything else stays at stock defaults.
CLONED = ("start_time", "end_time", "caf_allow_ot", "caf_ot_gate_minutes",
          "caf_ot_round_minutes", "caf_lunch_minutes",
          "caf_work_mon", "caf_work_tue", "caf_work_wed", "caf_work_thu",
          "caf_work_fri", "caf_work_sat", "caf_work_sun")


def _slug(name: str) -> str:
    keep = [c.upper() if c.isalnum() else "_" for c in name]
    out = "".join(keep)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def backfill_shift_codes() -> int:
    """Give every existing shift a code, so OD-70's handle is usable at once."""
    changed = 0
    for s in frappe.get_all("Shift Type", fields=["name", "caf_shift_code"]):
        if s.caf_shift_code:
            continue
        frappe.db.set_value("Shift Type", s.name, "caf_shift_code", _slug(s.name))
        changed += 1
    return changed


def ensure_shifts():
    """Create the four mirror shifts, wire the pairs, set the anchors.

    ⚠️ `caf_work_sat` stays **1** on all four. That flag means "this shift works
    Saturdays at all", which is true of both halves of a pair — WHICH Saturdays is
    the Holiday List's job, and only after R1 does the resolver read it. Until
    then these shifts resolve every Saturday as a workday, which is why employees
    are assigned in a separate step.
    """
    for name, source, code, rests in SHIFTS:
        src = frappe.db.get_value("Shift Type", source, CLONED, as_dict=True)
        if not src:
            frappe.throw(f"Source shift {source!r} not found")

        if frappe.db.exists("Shift Type", name):
            doc = frappe.get_doc("Shift Type", name)
        else:
            doc = frappe.new_doc("Shift Type")
            doc.name = name

        for f in CLONED:
            doc.set(f, src.get(f))
        doc.caf_work_sat = 1
        doc.caf_shift_code = code
        doc.caf_alt_sat = 1
        doc.caf_sat_anchor_date = ANCHOR
        doc.caf_sat_anchor = "Rest" if rests else "Work"
        doc.flags.ignore_permissions = True
        doc.save()

    # Both directions, always. A one-way link is a half-configured pair and it
    # fails in the direction nobody tests.
    for a, b in MIRRORS:
        frappe.db.set_value("Shift Type", a, "caf_sat_mirror", b)
        frappe.db.set_value("Shift Type", b, "caf_sat_mirror", a)

    codes = backfill_shift_codes()
    frappe.db.commit()

    print(f"  shift codes backfilled on {codes} existing shift(s)")
    for name, _, code, rests in SHIFTS:
        row = frappe.db.get_value(
            "Shift Type", name,
            ["caf_shift_code", "caf_alt_sat", "caf_sat_mirror",
             "caf_sat_anchor_date", "caf_sat_anchor", "caf_work_sat",
             "caf_allow_ot", "start_time", "end_time"], as_dict=True)
        back = frappe.db.get_value("Shift Type", row.caf_sat_mirror, "caf_sat_mirror")
        ok = "ok " if back == name else "🔴 ONE-WAY LINK"
        print(f"    {ok} {name:26s} code={row.caf_shift_code:14s} "
              f"anchor={row.caf_sat_anchor:5s} mirror={row.caf_sat_mirror}")
    return True


# ------------------------------------------------- the holiday HR forgot to add
#
# 🔴 CONFIRMED BY HR, 2026-08-12. A company holiday before Chinese New Year
# (Tue 17 / Wed 18 Feb) that was never entered. The evidence is in the punches:
# all eight employees recorded as WORKING and not one clocked in — a shape that
# occurs on exactly one other day in three months, 21 March, the confirmed public
# holiday, which looks identical.
#
# ⚠️ It is not cosmetic. The alternation is WALKED and a public holiday does not
# advance it, so a holiday the list does not know about makes the sequence advance
# when it should have waited — and every Saturday after it is inverted. Measured
# before this was added: the generated calendar diverged from reality from
# 14 February onward. This is precisely the "run away" HR asked to be protected
# from, and it is why OD-71 exists.
COMPANY_HOLIDAYS = [
    ("2026-02-14", "COMPANY HOLIDAY (Chinese New Year eve week) — added 2026-08-12, HR confirmed"),
]


def ensure_company_holidays() -> int:
    added = 0
    for day, desc in COMPANY_HOLIDAYS:
        year = int(day[:4])
        for lst in (f"CAF Public Holidays {year}",):
            if not frappe.db.exists("Holiday List", lst):
                continue
            if frappe.db.exists("Holiday", {"parent": lst, "holiday_date": day}):
                continue
            doc = frappe.get_doc("Holiday List", lst)
            doc.append("holidays", {"holiday_date": day, "weekly_off": 0,
                                    "description": desc})
            doc.flags.ignore_permissions = True
            doc.save()
            added += 1
    frappe.db.commit()
    print(f"  company holidays added to the canonical list: {added}")
    return added


# ------------------------------------------------------------ the eight people
#
# HR confirmed the management six on 2026-08-12 (question 4 of
# `ALT_SAT_FEB2026_for_HR_verification.html`). Derived from January 2026 and
# checked against the April anchor: on 2026-04-11 group B rested and group A
# worked, which is exactly how the two shifts are anchored.
#
# ⚠️ The production pair go on the SAME shift, by MG's decision. That reproduces
# what they actually do — Ingress shows them off together or working together on
# 24 of 32 Saturdays, mirroring only in June — so `8-5 Alt Sat 2nd-4th` is not a
# covering pair for them. Its mirror exists so a COVER can be expressed: moving
# one of them to the other shift for a date makes him work while the other rests.
ASSIGNMENTS = {
    # management six — 8:30am Schedule
    "HR-EMP-00003": ("8:30am Alt Sat 1st-3rd", "Too Poh Chin"),
    "HR-EMP-00005": ("8:30am Alt Sat 1st-3rd", "Nur Najwa Farhana"),
    "HR-EMP-00009": ("8:30am Alt Sat 1st-3rd", "Seow Zi Ying"),
    "HR-EMP-00004": ("8:30am Alt Sat 2nd-4th", "Afiza binti Mustafa"),
    "HR-EMP-00007": ("8:30am Alt Sat 2nd-4th", "Nurfarahayu Binti Ahmad"),
    "HR-EMP-00010": ("8:30am Alt Sat 2nd-4th", "Hazwani Farhana"),
    # production pair — Special 8-5, both on the same side
    "HR-EMP-00042": ("8-5 Alt Sat 2nd-4th", "Nur Ezzatul Allieya"),
    "HR-EMP-00096": ("8-5 Alt Sat 2nd-4th", "Noor Arifah Binti Ibrahim"),
}


def assign_employees():
    """Point the eight at their alternate-Saturday shift, and copy the list down.

    ⚠️ `Employee.default_shift` has NO date dimension, so this changes how their
    whole history resolves, not just the future. That is acceptable here and only
    here: **D-NEW-1** — pre-implementation data is not used for appraisal or OT —
    and the four shifts carry no rest Saturdays before the April anchor anyway.
    Stored `day_type` values are untouched; only a re-resolve would rewrite them.
    """
    changed = []
    for emp, (shift, who) in ASSIGNMENTS.items():
        before = frappe.db.get_value("Employee", emp,
                                     ["default_shift", "holiday_list"], as_dict=True)
        if not before:
            print(f"    🔴 {emp} {who} NOT FOUND")
            continue
        want_list = frappe.db.get_value("Shift Type", shift, "holiday_list")
        frappe.db.set_value("Employee", emp, "default_shift", shift)
        # FDR6 — every stock function (leave day counting, `is_holiday`) reads the
        # EMPLOYEE's list and knows nothing about shifts, so it is copied down.
        frappe.db.set_value("Employee", emp, "holiday_list", want_list)
        changed.append((emp, who, before.default_shift, shift, want_list))

    frappe.db.commit()
    print(f"  assigned {len(changed)} employee(s)")
    for emp, who, was, now, lst in changed:
        print(f"    {emp} {who[:26]:26s} {was:18s} -> {now:24s} list={lst}")
    return changed


def clear_seeded_assignments(dry_run: bool = True):
    """Remove the eight's seeded rest-Saturday assignments. **They are now wrong.**

    Each one points at a no-Saturday shift for a single date, and a Shift
    Assignment BEATS `default_shift` — so every one of them overrides the
    alternation the new shift now carries. 46 dates, measured.

    They existed because the pattern had nowhere else to live. It has somewhere
    now, and that is the whole point of OD-67: a Shift Assignment goes back to
    meaning **an exception** — a swap or a cover — rather than routine bookkeeping.

    ⚠️ Cancelling fires `on_cancel`, so Chunk 4 re-resolves each affected Finger
    Log and Chunk 5 refreshes any appraisal downstream of it. That is intended —
    it is what makes the stored data agree with the new design — but it does
    rewrite stored `day_type` values, so the dry run reports first.
    """
    rows = []
    for emp in ASSIGNMENTS:
        for sa in frappe.get_all("Shift Assignment",
                                 filters={"employee": emp, "docstatus": 1},
                                 fields=["name", "start_date", "end_date", "shift_type"],
                                 order_by="start_date"):
            # single-day only: a seeded row is always one date. Anything spanning
            # a range was filed by a person and is not ours to remove.
            if sa.start_date == sa.end_date:
                rows.append((emp, sa))

    print(f"  {'WOULD REMOVE' if dry_run else 'REMOVING'} {len(rows)} seeded assignment(s)")
    if dry_run:
        for emp, sa in rows[:6]:
            print(f"    {emp} {sa.start_date} {sa.shift_type}")
        print("    ... run with dry_run=0 to apply")
        return len(rows)

    removed, failed = 0, {}
    for emp, sa in rows:
        sp = f"sa_{sa.name.replace('-', '_')}"[:60]
        frappe.db.savepoint(sp)          # per row — a bare rollback once cost 5,600 rows
        try:
            doc = frappe.get_doc("Shift Assignment", sa.name)
            doc.flags.ignore_permissions = True
            doc.cancel()
            frappe.delete_doc("Shift Assignment", sa.name,
                              ignore_permissions=True, force=True)
            removed += 1
        except Exception as e:
            frappe.db.rollback(save_point=sp)
            failed[f"{emp} {sa.start_date}"] = str(e).split("\n")[0][:110]

    frappe.db.commit()
    print(f"  removed {removed}, failed {len(failed)}")
    for k, v in list(failed.items())[:8]:
        print(f"    🔴 {k}: {v}")
    return removed


def apply_clear_seeded_assignments():
    """`clear_seeded_assignments` for real. Separate entry point because
    `bench execute --args` does not survive PowerShell (PROTOCOL §A3), so the
    argument lives in the module instead."""
    return clear_seeded_assignments(dry_run=False)


def setup():
    """Phase 1 — schema, shifts, lists. Touches no employee."""
    from caf.caf import holiday_lists

    ensure_fields()
    ensure_shifts()
    ensure_company_holidays()
    made = holiday_lists.generate_holiday_lists(2026)
    print(f"  holiday lists for 2026: {made}")
