"""Rename the alternating-Saturday shifts and their Holiday Lists to A / B.

    bench --site <site> execute caf.scripts.alt_sat_rename.report   # dry run
    bench --site <site> execute caf.scripts.alt_sat_rename.apply
    bench --site <site> execute caf.scripts.alt_sat_rename.verify

WHY THIS EXISTS — T-47, MG's Decision §1, 2026-09-13
----------------------------------------------------
The four alternating shifts were named for the Saturdays they rest on:

    8-5    Alt Sat 1st-3rd / 2nd-4th        8:30am Alt Sat 1st-3rd / 2nd-4th

and `alt_label()` named each year's Holiday List the same way, computed from the
first Saturday the pattern actually rests on. **That computation swings.** One
Saturday public holiday flips every Saturday after it, so the first rest Saturday
moves and the label follows it. On this site it has already happened:

    8:30am Alt Sat 2nd-4th   ->   CAF Alt Sat 1st-3rd 2027
    8:30am Alt Sat 1st-3rd   ->   CAF Alt Sat 2nd-4th 2027

2026 happens to agree, which is why nobody saw it. **No calendar was ever
mis-assigned** — `generate_holiday_lists()` groups on the ANCHOR and points each
group at its own list — but a human reading a shift name beside its list name is
told a lie, and that is what the numbers were for in the first place.

MG, 2026-09-13: *"this was decided early on of the project, while i did not
understand that the 1 and 3 sequence will change... Rename BOTH, to something the
calendar cannot contradict."* The letters come from `caf_shift_code`
(`ALTSAT_85_A` -> `A`), which was already A and B — a human assigns it once and
no calendar operation rewrites it.

WHY IT IS SAFE TO DO ON THE TEST SERVER — MG's condition on the decision
-----------------------------------------------------------------------
*"if name change on test server does not have impact towards export plan towards
prod server"*. Measured before writing this:

    · `shift_holiday_migration` matches EVERY shift by `caf_shift_code`, never by
      name (`_by_code()`, and the employee rows carry `shift_code` too). The name
      is used once, as the name to create with.
    · its payload is EXPORTED FROM THIS SITE, so the next export carries the new
      names with no hand-editing.
    · `holiday_list` is deliberately omitted from the payload —
      `generate_holiday_lists()` builds prod's calendars there.
    · production's Shift Types are named `1`-`10` (FBR83), so no name from here
      can collide with one there.

WHAT MAKES THE RENAME SAFE ON THIS SITE
---------------------------------------
`frappe.rename_doc` rewrites every Link field that points at the renamed record.
Measured here: 189 links across Finger Log, Attendance, Employee, Shift
Assignment and `caf_sat_mirror`. Nothing is deleted and nothing is recomputed —
`verify()` asserts the calendars are byte-identical after the rename.
"""

import frappe
from frappe.utils import getdate, nowdate

from caf.caf.holiday_lists import (PATTERN_LIST, alt_label, alt_saturday_rest_days,
                                   working_week)

SHIFT_RENAMES = {
    "8-5 Alt Sat 1st-3rd":     "8-5 Alt Sat A",
    "8-5 Alt Sat 2nd-4th":     "8-5 Alt Sat B",
    "8:30am Alt Sat 1st-3rd":  "8:30am Alt Sat A",
    "8:30am Alt Sat 2nd-4th":  "8:30am Alt Sat B",
}

# Which years' Holiday Lists exist and must travel with the shifts.
YEARS = (2025, 2026, 2027)


def _old_label(rest_saturdays):
    """The label `alt_label()` used to produce, so old names can be found.

    Kept HERE and not in `holiday_lists`, because it is only needed to locate
    what this script is replacing.
    """
    if not rest_saturdays:
        return "Alt Sat"
    first = min(rest_saturdays)
    nth = (first.day - 1) // 7 + 1
    return "Alt Sat 1st-3rd" if nth % 2 else "Alt Sat 2nd-4th"


def _alt_groups():
    """The same grouping `generate_holiday_lists()` uses: anchor, not name."""
    shifts = frappe.get_all(
        "Shift Type", filters={"caf_alt_sat": 1},
        fields=["name", "caf_shift_code", "caf_sat_anchor_date", "caf_sat_anchor",
                "caf_work_mon", "caf_work_tue", "caf_work_wed", "caf_work_thu",
                "caf_work_fri", "caf_work_sat", "caf_work_sun"])
    groups = {}
    for s in shifts:
        if not (s.caf_sat_anchor_date and s.caf_sat_anchor):
            continue
        key = (working_week(s), getdate(s.caf_sat_anchor_date),
               s.caf_sat_anchor == "Rest")
        groups.setdefault(key, []).append(s.name)
    return groups


def _list_renames():
    """{old Holiday List name: new name} for every year that has one."""
    out = {}
    for key, owners in _alt_groups().items():
        _pattern, anchor, rests = key
        new_label = alt_label(owners, anchor, rests)
        for year in YEARS:
            try:
                rest_sats = alt_saturday_rest_days(year, anchor, rests)
            except Exception as e:                 # a year whose PH list is absent
                print("   (skipping %d: %s)" % (year, str(e)[:80]))
                continue
            old = PATTERN_LIST.format(label=_old_label(rest_sats), year=year)
            new = PATTERN_LIST.format(label=new_label, year=year)
            if old == new or not frappe.db.exists("Holiday List", old):
                continue
            out[old] = new
    return out


def _snapshot():
    """Every alternating list's dates, so the rename can be proved content-safe."""
    snap = {}
    for n in frappe.get_all("Holiday List",
                            filters={"name": ("like", "CAF Alt Sat%")}, pluck="name"):
        rows = frappe.get_all("Holiday", filters={"parent": n},
                              fields=["holiday_date", "weekly_off", "description"],
                              order_by="holiday_date")
        snap[n] = [(str(r.holiday_date), r.weekly_off, r.description) for r in rows]
    return snap


def report():
    """Dry run: what would be renamed, and what links travel with it."""
    print("=== Shift Types ===")
    for old, new in SHIFT_RENAMES.items():
        if not frappe.db.exists("Shift Type", old):
            print("   - %-26s (absent — already renamed?)" % old)
            continue
        code = frappe.db.get_value("Shift Type", old, "caf_shift_code")
        links = sum(frappe.db.count(dt, {f: old}) for dt, f in (
            ("Finger Log", "shift_type"), ("Attendance", "shift"),
            ("Employee", "default_shift"), ("Shift Assignment", "shift_type"),
            ("Shift Type", "caf_sat_mirror")))
        print("   %-26s -> %-20s  code=%-14s links=%d" % (old, new, code, links))

    print("\n=== Holiday Lists ===")
    renames = _list_renames()
    if not renames:
        print("   (none — already renamed, or no alternating shifts)")
    for old, new in sorted(renames.items()):
        shifts = frappe.get_all("Shift Type", filters={"holiday_list": old}, pluck="name")
        emps = frappe.db.count("Employee", {"holiday_list": old})
        print("   %-26s -> %-22s  shifts=%s employees=%d"
              % (old, new, shifts or "[]", emps))

    print("\n=== What the new label is derived from ===")
    for key, owners in sorted(_alt_groups().items(), key=lambda kv: str(kv[0])):
        _p, anchor, rests = key
        print("   anchor %s %-5s  %-26s -> %s"
              % (anchor, "Rest" if rests else "Work",
                 ", ".join(owners), alt_label(owners, anchor, rests)))
    return {"shifts": SHIFT_RENAMES, "lists": renames}


def apply():
    """Rename, then regenerate in place and prove the calendars did not move."""
    before = _snapshot()
    list_renames = _list_renames()

    print("=== Renaming Holiday Lists ===")
    for old, new in sorted(list_renames.items()):
        frappe.rename_doc("Holiday List", old, new, force=True,
                          merge=False, show_alert=False)
        print("   %s -> %s" % (old, new))

    print("\n=== Renaming Shift Types ===")
    for old, new in SHIFT_RENAMES.items():
        if not frappe.db.exists("Shift Type", old):
            print("   - %s (absent)" % old)
            continue
        frappe.rename_doc("Shift Type", old, new, force=True,
                          merge=False, show_alert=False)
        print("   %s -> %s" % (old, new))

    frappe.db.commit()

    # Regenerate so the generator's own names and the renamed documents agree.
    # 🔴 If the rename and `alt_label()` disagree this CREATES a second list and
    # leaves the renamed one orphaned — which is why verify() counts them.
    #
    # ⚠️ Use `regenerate()`, not a loop of `generate_holiday_lists()`. It carries
    # `repoint=(year == current_year)`; a bare loop repoints every Shift Type at
    # the LAST year generated, which on 2026-09-13 parked eight live employees on
    # a 2027 calendar. Measured, then undone.
    # ⚠️ And only years the anchor can reach — `alt_saturday_rest_days()` throws
    # on a year that precedes `caf_sat_anchor_date`, which is what made the first
    # run of this script die (invisibly: `bench execute` swallows the real
    # exception in an `eval` fallback and reports `NameError: name 'caf'`).
    from caf.caf import holiday_lists
    current_year = getdate(nowdate()).year
    anchor_year = min((getdate(k[1]).year for k in _alt_groups()), default=current_year)
    years = [y for y in YEARS
             if y >= anchor_year
             and frappe.db.exists("Holiday List", "CAF Public Holidays %d" % y)]
    print("\n=== Regenerating (repoint on %d) ===" % current_year)
    print("   years: %s  (anchor year %d)" % (years, anchor_year))
    holiday_lists.regenerate(years=",".join(str(y) for y in years),
                             current_year=current_year)
    frappe.db.commit()

    # The rename must move NAMES and nothing else. Compare every list that
    # existed before against wherever it now lives — so a re-run, where nothing
    # is renamed, still proves the regeneration did not bend a calendar.
    after = _snapshot()
    moved = []
    for old, rows in before.items():
        new = list_renames.get(old, old)
        if after.get(new) != rows:
            moved.append((old, new))
    print("\n=== Content check ===")
    print("   lists compared: %d" % len(before))
    print("   lists whose dates changed: %d %s" % (len(moved), moved or ""))
    return {"renamed_lists": list_renames, "moved": moved}


def verify():
    """Assert the site is consistent after the rename. Safe to re-run."""
    ok = True

    def check(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        print("   %s %s" % ("PASS" if cond else "FAIL", msg))

    for old, new in SHIFT_RENAMES.items():
        check(not frappe.db.exists("Shift Type", old), "gone: %s" % old)
        check(frappe.db.exists("Shift Type", new), "exists: %s" % new)

    stale = frappe.get_all("Holiday List",
                           filters={"name": ("like", "CAF Alt Sat 1st%")}, pluck="name")
    stale += frappe.get_all("Holiday List",
                            filters={"name": ("like", "CAF Alt Sat 2nd%")}, pluck="name")
    check(not stale, "no 1st-3rd / 2nd-4th Holiday List left: %s" % (stale or "none"))

    # every alternating shift points at a list named for its own code letter
    for s in frappe.get_all("Shift Type", filters={"caf_alt_sat": 1},
                            fields=["name", "caf_shift_code", "holiday_list"]):
        letter = (s.caf_shift_code or "").rsplit("_", 1)[-1]
        check(s.holiday_list and ("Alt Sat %s " % letter) in s.holiday_list,
              "%s (%s) -> %s" % (s.name, s.caf_shift_code, s.holiday_list))

    # and the name a human reads cannot contradict the list any more
    for s in frappe.get_all("Shift Type", filters={"caf_alt_sat": 1},
                            fields=["name", "caf_shift_code"]):
        letter = (s.caf_shift_code or "").rsplit("_", 1)[-1]
        check(s.name.endswith("Alt Sat %s" % letter),
              "shift name agrees with its code: %s / %s" % (s.name, s.caf_shift_code))

    # nothing still links to a dead name
    for dt, field in (("Finger Log", "shift_type"), ("Attendance", "shift"),
                      ("Employee", "default_shift"), ("Shift Assignment", "shift_type"),
                      ("Shift Type", "caf_sat_mirror")):
        n = sum(frappe.db.count(dt, {field: old}) for old in SHIFT_RENAMES)
        check(n == 0, "%s.%s has no row on an old name (%d)" % (dt, field, n))

    print("\n   %s" % ("ALL PASS" if ok else "SOMETHING FAILED"))
    return ok
