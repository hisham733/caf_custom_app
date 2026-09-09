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
from frappe.utils import getdate

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

# 🔴 THE CODE IS THE IDENTITY; THE NAME IS ONLY THE FIRST NAME IT IS GIVEN.
#
# OD-96, 2026-09-09. Before this, every entry below held a NAME, and that made
# the four shifts unrenameable: after an HR rename, `frappe.db.exists(name)`
# would find nothing and this script would **create the old shifts again**,
# silently, alongside the renamed ones.
#
# Now the tuple carries the code, and `_resolve()` finds the live shift by code
# first, falling back to the seed name only when the shift does not exist yet —
# which is the one moment a name is genuinely needed, at creation.
#
# (code, seed name used only at creation, source code, rests on the anchor)
SHIFTS = [
    ("ALTSAT_85_A",  "8-5 Alt Sat 1st-3rd",    "SPECIAL_8_5",     False),
    ("ALTSAT_85_B",  "8-5 Alt Sat 2nd-4th",    "SPECIAL_8_5",     True),
    ("ALTSAT_830_A", "8:30am Alt Sat 1st-3rd", "8_30AM_SCHEDULE", False),
    ("ALTSAT_830_B", "8:30am Alt Sat 2nd-4th", "8_30AM_SCHEDULE", True),
]

MIRRORS = [("ALTSAT_85_A", "ALTSAT_85_B"),
           ("ALTSAT_830_A", "ALTSAT_830_B")]


def _resolve(code, seed_name=None):
    """The live Shift Type for a code, or None if it does not exist yet.

    ⚠️ Deliberately NOT `shift_resolution.by_code`, which throws. Here a missing
    shift is the normal case on a fresh site — it is what `ensure_shifts()`
    exists to fix — so this returns None and lets the caller create it.
    """
    name = frappe.db.get_value("Shift Type", {"caf_shift_code": code}, "name")
    if name:
        return name
    # A shift created before codes existed, or one seeded by an older run.
    if seed_name and frappe.db.exists("Shift Type", seed_name):
        return seed_name
    return None

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


# 🔴 OD-88 — WHAT THIS SCRIPT OWNS, AND WHAT IT MUST NOT TOUCH AGAIN.
#
# MG, 2026-09-04: *"if HR manager manually change lunch = 30 min on both clones …
# and if for whatever reason CAF app is reinstalled OR bench_migrate is called,
# then OT = True again, silently?"*
#
# The migrate half of that was unfounded — this module is in no hook, no
# `after_migrate`, and nothing calls it (FBR76, verified by grep over the whole
# app). But the **re-run** half was real, and it was worse than it looked: the
# first version re-copied all 13 CLONED parameters from the source on EVERY
# invocation, including an invocation whose only purpose was to repair a mirror
# link. So a run meant to fix a one-way link silently reverted HR's lunch and OT
# settings, with no error and no log entry.
#
# The split below is the fix (OD-88, MG 2026-09-04: *"Yes. Copy on creation only;
# report drift instead of reverting it"*):
#
#   THE SCRIPT OWNS          because it is a structural invariant, not a setting
#     caf_shift_code           identity; `unique`, and code/tests hold it (OD-70)
#     caf_alt_sat              declares the shift is half of a pair
#     caf_sat_mirror           MUST be mutual — a one-way link fails in the
#                              direction nobody tests (FBR57), and repairing it
#                              is the main reason to re-run this at all
#
#   HR OWNS — reported, never overwritten
#     the 13 CLONED parameters start/end, lunch, OT gate and rounding, workdays
#     caf_sat_anchor_date      🔴 changing this RE-PHASES every later Saturday
#     caf_sat_anchor           🔴 same — and flipping one half without the other
#                              means nobody works that Saturday
#
# ⚠️ The anchor moved from "always written" to "written once" deliberately. It is
# the single value that decides which group rests on which Saturday, and a silent
# rewrite of it is the "run away" failure OD-71 exists to prevent. If it is ever
# genuinely wrong, `resync_from_source()` is the deliberate, named act that fixes
# it — nobody should reach it by re-running `setup()`.
PAIRING = ("caf_shift_code", "caf_alt_sat", "caf_sat_mirror")
HR_OWNED = CLONED + ("caf_sat_anchor_date", "caf_sat_anchor")


def _drift(name, source_code, rests):
    """What this shift holds vs what a fresh clone would hold. Reports only."""
    source = _resolve(source_code)
    if not source or not name:
        return []
    src = frappe.db.get_value("Shift Type", source, CLONED, as_dict=True)
    cur = frappe.db.get_value("Shift Type", name, HR_OWNED, as_dict=True)
    if not src or not cur:
        return []
    want = dict(src)
    want["caf_work_sat"] = 1
    want["caf_sat_anchor_date"] = getdate(ANCHOR)
    want["caf_sat_anchor"] = "Rest" if rests else "Work"

    out = []
    for f in HR_OWNED:
        a, b = cur.get(f), want.get(f)
        if f == "caf_sat_anchor_date":
            a = getdate(a) if a else None
        if str(a) != str(b):
            out.append((f, a, b))
    return out


def ensure_shifts():
    """Create the four mirror shifts, wire the pairs, set the anchors ONCE.

    🔴 **Re-runnable, and re-running it changes nothing HR set.** See the OD-88
    note above: on a shift that already exists this touches only the three
    PAIRING fields and reports everything else as drift.

    ⚠️ `caf_work_sat` stays **1** on all four at creation. That flag means "this
    shift works Saturdays at all", which is true of both halves of a pair — WHICH
    Saturdays is the Holiday List's job, and only after R1 does the resolver read
    it. Until then these shifts resolve every Saturday as a workday, which is why
    employees are assigned in a separate step.
    """
    created, existing = [], []

    for code, seed_name, source_code, rests in SHIFTS:
        source = _resolve(source_code)
        if not source:
            frappe.throw(f"Source shift with code {source_code!r} not found")

        # 🔴 By CODE, not by name — so an HR rename does not make this create a
        # duplicate of a shift that already exists under its new label (OD-96).
        name = _resolve(code)
        if name:
            existing.append((name, source, rests))
            # PAIRING only. Never the parameters, never the anchor.
            frappe.db.set_value("Shift Type", name, {
                "caf_shift_code": code,
                "caf_alt_sat": 1,
            }, update_modified=False)
            continue

        src = frappe.db.get_value("Shift Type", source, CLONED, as_dict=True)
        doc = frappe.new_doc("Shift Type")
        doc.name = seed_name
        for f in CLONED:
            doc.set(f, src.get(f))
        doc.caf_work_sat = 1
        doc.caf_shift_code = code
        doc.caf_alt_sat = 1
        doc.caf_sat_anchor_date = ANCHOR
        doc.caf_sat_anchor = "Rest" if rests else "Work"
        doc.flags.ignore_permissions = True
        doc.insert()
        created.append(seed_name)

    # Both directions, always — this IS the script's job. A one-way link is a
    # half-configured pair and it fails in the direction nobody tests.
    for code_a, code_b in MIRRORS:
        a, b = _resolve(code_a), _resolve(code_b)
        if not (a and b):
            continue
        frappe.db.set_value("Shift Type", a, "caf_sat_mirror", b, update_modified=False)
        frappe.db.set_value("Shift Type", b, "caf_sat_mirror", a, update_modified=False)

    codes = backfill_shift_codes()
    frappe.db.commit()
    frappe.clear_cache(doctype="Shift Type")

    print(f"  created {len(created)}: {created or 'none'}")
    print(f"  already present, parameters left alone: {len(existing)}")
    print(f"  shift codes backfilled on {codes} other shift(s)")

    for code, _seed, _src, rests in SHIFTS:
        name = _resolve(code)
        if not name:
            print(f"    🔴 MISSING {code}")
            continue
        row = frappe.db.get_value(
            "Shift Type", name,
            ["caf_shift_code", "caf_alt_sat", "caf_sat_mirror",
             "caf_sat_anchor_date", "caf_sat_anchor", "caf_work_sat",
             "caf_allow_ot", "caf_lunch_minutes", "start_time", "end_time"],
            as_dict=True)
        back = frappe.db.get_value("Shift Type", row.caf_sat_mirror, "caf_sat_mirror")
        ok = "ok " if back == name else "🔴 ONE-WAY LINK"
        print(f"    {ok} {name:26s} code={row.caf_shift_code:14s} "
              f"anchor={row.caf_sat_anchor:5s} mirror={row.caf_sat_mirror}")

    report_drift()
    return True


def report_drift():
    """Every place a live shift differs from a fresh clone of its source.

    🔴 **A difference here is NOT automatically a fault.** HR changing a lunch
    break on one half of a pair is exactly the kind of edit this script stopped
    reverting. What it is, is *visible* — which is the whole of OD-88. Read the
    list, decide, and if a value genuinely should come back from the source, say
    so out loud with `resync_from_source`.
    """
    print("\n  ── drift from source (reported, NOT corrected) ──")
    total = 0
    for code, _seed, source_code, rests in SHIFTS:
        name = _resolve(code)
        if not name:
            continue
        source = _resolve(source_code)
        rows = _drift(name, source_code, rests)
        total += len(rows)
        if not rows:
            print(f"    ok  {name:26s} matches a fresh clone of {source}")
            continue
        print(f"    ⚠️  {name:26s} {len(rows)} field(s) differ from {source}:")
        for f, is_now, would_be in rows:
            flag = "🔴 " if f.startswith("caf_sat_anchor") else "   "
            print(f"        {flag}{f:22s} is {str(is_now):12s} "
                  f"a fresh clone would be {would_be}")
    if total:
        print(f"\n    {total} difference(s). ⚠️ If HR set them, that is correct and "
              f"nothing should be done.\n    Only if they are genuinely wrong: "
              f"bench execute caf.scripts.alt_saturday_setup.resync_from_source")
    return total


def resync_from_source(dry_run: bool = True):
    """🔴 THE DELIBERATE ACT. Push the source's parameters back onto the clones.

    This is what `ensure_shifts()` used to do silently on every run. It is kept
    because there is a real case for it — the source was corrected and the clones
    should follow — but it is now a separate, named command with a dry run, so it
    can only happen because somebody decided it should.

    ⚠️ It rewrites the ANCHOR too, and a changed anchor re-phases every Saturday
    after it. Read `report_drift()` first.
    """
    plan = []
    for code, _seed, source_code, rests in SHIFTS:
        name = _resolve(code)
        if name:
            for f, is_now, would_be in _drift(name, source_code, rests):
                plan.append((name, f, is_now, would_be))

    print(f"  {'WOULD OVERWRITE' if dry_run else 'OVERWRITING'} {len(plan)} value(s)")
    for name, f, is_now, would_be in plan:
        print(f"    {name:26s} {f:22s} {is_now} → {would_be}")
    if dry_run:
        print("    ... run apply_resync_from_source to apply")
        return len(plan)

    for name, f, _is_now, would_be in plan:
        frappe.db.set_value("Shift Type", name, f, would_be)
    for name in {p[0] for p in plan}:
        frappe.get_doc("Shift Type", name).add_comment(
            "Comment",
            f"alt_saturday_setup.resync_from_source — parameters pushed back "
            f"from the source shift. OD-88: this is a deliberate act, never a "
            f"side effect of re-running setup().")
    frappe.db.commit()
    frappe.clear_cache(doctype="Shift Type")
    print(f"  DONE — {len(plan)} value(s) overwritten")
    return len(plan)


def apply_resync_from_source():
    """`resync_from_source` for real — separate entry point because
    `bench execute --kwargs` does not survive PowerShell (PROTOCOL §A3)."""
    return resync_from_source(dry_run=False)


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


# ------------------------------------------------------------------------- R7
#
# HR's answer, 2026-08-12: **only the eight in `AltSat_swap.csv` have alternate
# Saturdays.** These four do not, and their seeded assignments came from the
# seeder trusting Ingress rows for dates that had not happened yet.
#
#   Rajaindran   works Mon–Sat  (the rejoiner of OD-55 — two Ingress users, two
#                                Employee records, and a shift change this year)
#   Dina Laila   works Mon–Sat  (all 20 of her rows are FUTURE-dated; her past
#                                Saturdays are 0 of 4 rested)
#   Chen         works Mon–FRI  (53 of 54 past Saturdays rested — her default
#                                shift is simply wrong, and one no-Sat shift
#                                replaces 33 assignments)
#   Hisham       not in HR's list, 2 of 54 past Saturdays rested
NOT_ALT_SAT = {
    "HR-EMP-00109": (None, "Rajaindran — Mon-Sat, keeps 8-4.30 no OT"),
    "HR-EMP-00186": (None, "Dina Laila — Mon-Sat, keeps 8.30am Roster"),
    "HR-EMP-00094": (None, "Hisham — Mon-Sat, keeps 8.30am Roster"),
    # 🔴 the only one whose DEFAULT SHIFT is wrong. `8am no OT no Sat` matches her
    # `6am Schedule` on OT eligibility (both caf_allow_ot = 0), which is the trap
    # `pick_rest_shift()` documents: two of the three no-Saturday shifts revoke OT,
    # and all rest-day work is OT (FBR4).
    "HR-EMP-00006": ("8am no OT no Sat", "Chen Xiao Natalie — Mon-Fri"),
}


def fix_non_alt_employees(dry_run: bool = True):
    """R7 — correct the three shifts and drop assignments that assert nothing true."""
    plan = []
    for emp, (new_shift, why) in NOT_ALT_SAT.items():
        cur = frappe.db.get_value("Employee", emp,
                                  ["employee_name", "default_shift"], as_dict=True)
        if not cur:
            continue
        rows = frappe.get_all("Shift Assignment",
                              filters={"employee": emp, "docstatus": 1},
                              fields=["name", "start_date", "end_date", "shift_type"])
        single = [r for r in rows if r.start_date == r.end_date]
        plan.append((emp, cur, new_shift, why, single))

    total = sum(len(p[4]) for p in plan)
    print(f"  {'WOULD FIX' if dry_run else 'FIXING'} {len(plan)} employee(s), "
          f"{total} assignment(s)")
    for emp, cur, new_shift, why, single in plan:
        move = f"{cur.default_shift} -> {new_shift}" if new_shift else "shift unchanged"
        print(f"    {emp} {str(cur.employee_name)[:26]:26s} {len(single):3d} rows  "
              f"{move:36s} {why}")
    if dry_run:
        print("    ... run apply_fix_non_alt_employees to apply")
        return total

    removed, failed = 0, {}
    for emp, cur, new_shift, why, single in plan:
        if new_shift:
            want_list = frappe.db.get_value("Shift Type", new_shift, "holiday_list")
            frappe.db.set_value("Employee", emp, "default_shift", new_shift)
            if want_list:
                frappe.db.set_value("Employee", emp, "holiday_list", want_list)
        for sa in single:
            sp = f"r7_{sa.name.replace('-', '_')}"[:60]
            frappe.db.savepoint(sp)
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


def apply_fix_non_alt_employees():
    return fix_non_alt_employees(dry_run=False)


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


# ────────────────────────────────────────────── the CAF scripts contract
#
# `run()` reports and writes nothing; `verify()` proves the state. Both were
# missing until OD-88, which is why this module was the one production script
# `test_data_scripts` did not cover — its only entry point wrote.


def run():
    """Report only. What exists, how it is paired, and where it has drifted."""
    print(f"\n{'=' * 74}\nALTERNATE-SATURDAY SHIFTS — current state\n{'=' * 74}")
    for code, seed_name, source_code, rests in SHIFTS:
        name = _resolve(code)
        if not name:
            print(f"  🔴 MISSING code {code} (would be created as {seed_name!r} "
                  f"from {source_code})")
            continue
        row = frappe.db.get_value(
            "Shift Type", name,
            ["caf_shift_code", "caf_alt_sat", "caf_sat_mirror",
             "caf_sat_anchor_date", "caf_sat_anchor", "caf_lunch_minutes",
             "caf_allow_ot", "holiday_list"], as_dict=True)
        emps = frappe.db.count("Employee",
                               {"default_shift": name, "status": "Active"})
        back = frappe.db.get_value("Shift Type", row.caf_sat_mirror,
                                   "caf_sat_mirror") if row.caf_sat_mirror else None
        print(f"\n  {name}")
        print(f"    code={row.caf_shift_code}  anchor={row.caf_sat_anchor} on "
              f"{row.caf_sat_anchor_date}  active employees={emps}")
        print(f"    mirror={row.caf_sat_mirror} "
              f"{'(mutual ok)' if back == name else '🔴 ONE-WAY'}")
        print(f"    lunch={row.caf_lunch_minutes} ot={row.caf_allow_ot} "
              f"list={row.holiday_list}")
    n = report_drift()
    print(f"\n(report only — `setup` creates what is missing and repairs pairing; "
          f"it does NOT touch the {n} drifted value(s))")
    return {"drift": n}


def verify():
    """Four assertions, and the third is the one OD-88 exists for."""
    fails = 0

    # ⚠️ SHIFTS and MIRRORS hold CODES since OD-96, so every lookup resolves
    # first. Comparing a code against a `caf_sat_mirror` (which stores a NAME)
    # is what this function did on its first run after the migration, and it
    # reported four false failures.
    missing = [c for c, _seed, _src, _r in SHIFTS if not _resolve(c)]
    ok = not missing
    print(f"AS1-SHIFTS-EXIST      {'PASS' if ok else 'FAIL'}  "
          f"missing codes: {missing or 'none'} — all four alternate-Saturday shifts")
    fails += 0 if ok else 1

    broken = []
    for code_a, code_b in MIRRORS:
        a, b = _resolve(code_a), _resolve(code_b)
        if not (a and b):
            broken.append(f"{code_a}/{code_b} — one half does not exist")
            continue
        if frappe.db.get_value("Shift Type", a, "caf_sat_mirror") != b:
            broken.append(f"{a} does not name {b}")
        if frappe.db.get_value("Shift Type", b, "caf_sat_mirror") != a:
            broken.append(f"{b} does not name {a}")
    ok = not broken
    print(f"AS2-MIRRORS-MUTUAL    {'PASS' if ok else 'FAIL'}  {broken or 'both pairs mutual'} "
          f"— a one-way link fails in the direction nobody tests (FBR57)")
    fails += 0 if ok else 1

    opposite = []
    for code_a, code_b in MIRRORS:
        a, b = _resolve(code_a), _resolve(code_b)
        if not (a and b):
            continue
        if (frappe.db.get_value("Shift Type", a, "caf_sat_anchor")
                == frappe.db.get_value("Shift Type", b, "caf_sat_anchor")):
            opposite.append(f"{a}/{b} anchor the SAME way")
    ok = not opposite
    print(f"AS3-ANCHORS-OPPOSITE  {'PASS' if ok else 'FAIL'}  "
          f"{opposite or 'each pair anchors Rest against Work'} — if both rest, "
          f"nobody covers that Saturday")
    fails += 0 if ok else 1

    # 🔴 The assertion OD-96 turns on: the CODE must resolve to exactly one live
    # shift, whatever HR has renamed it to.
    codes = {c: _resolve(c) for c, _seed, _src, _r in SHIFTS}
    ok = all(codes.values())
    print(f"AS4-CODES-RESOLVE     {'PASS' if ok else 'FAIL'}  {codes} — the code is "
          f"the identity; the name is only the first label it was given (OD-70/96)")
    fails += 0 if ok else 1

    print(f"\n{'clean' if not fails else str(fails) + ' problem(s)'}")
    return fails
