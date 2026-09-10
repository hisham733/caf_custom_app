"""T-34 rows 4 + 8 — carry CAF's Shift Types and calendars to another site.

    bench --site <site> execute caf.scripts.shift_holiday_migration.export
    bench --site <site> execute caf.scripts.shift_holiday_migration.run
    bench --site <site> execute caf.scripts.shift_holiday_migration.run --kwargs "{'apply':1}"
    bench --site <site> execute caf.scripts.shift_holiday_migration.verify

`export` runs on the AUTHORITY site (today: development.localhost) and writes
`caf/scripts/data/shift_holiday_payload.json`. Everything else runs on the
TARGET (prod-test, then production) and reads that file. The payload is
COMMITTED, so it travels by git with the app and is diffable in review — which
is the whole reason it is a file and not something an operator carries by hand.

WHY ONE SCRIPT AND NOT TWO — T-34
---------------------------------
The migration policy table names four doctypes that need a script, and says of
two of them:

    row 4  Shift Type + Employee.default_shift   "import the new set, then reassign"
    row 8  Holiday List                          "import + repoint"
    "...and rows 4 and 8 must be in the SAME script, because importing shifts
     and holiday lists without repointing employees adds orphans twice."

That is exactly what happens if they are separate: the shifts land, nobody is on
them, the old calendars stay attached to the employees, and the site looks
migrated while every day still resolves by the old rules.

🔴 NEITHER TRAVELS AS A FIXTURE — FBR87
---------------------------------------
Only Property Setter, Custom Field, Custom DocPerm and the three Workflow
doctypes are exported. `bench migrate` brings the 21 `caf_*` FIELDS on Shift
Type; it brings none of the 18 RECORDS, no Holiday List, and no Employee. The
shape arrives, the content does not. This script is the content.

🔴 PEOPLE ARE MATCHED BY DEVICE ID, NOT BY `HR-EMP-xxxxx` — T-32
----------------------------------------------------------------
`HR-EMP-00096` means "the 96th Employee created on THIS site", so the same id is
a different person on production. `attendance_device_id` is the Ingress user id
and is identical on both by construction. Measured on the authority site: 88 of
89 active employees carry one; the one that does not is Yow Kwee Chin, a
director with no Ingress account at all (FBR74), who also has no shift — so
there is nothing to carry for him and nothing is guessed.

⚠️ Like `shift_reassign`, a row is REFUSED when the device id resolves to an
employee whose name disagrees. A device-id typo that happens to hit a real
person is precisely what the name check catches, and putting somebody on the
wrong shift decides their pay.

⭐ THE CALENDARS ARE NOT COPIED — THEY ARE REGENERATED
-----------------------------------------------------
A Holiday List is 90% derived. Of the 1,784 Holiday rows on the authority site,
the overwhelming majority are `weekly_off` rows that `caf.caf.holiday_lists`
computes from each shift's working week (FBR23), and the rest are the public
holidays, which are one set for everybody (FBR12). So the payload carries only
the DATED public holidays — about 19 a year — and this script then calls the
module that already exists:

    generate_holiday_lists()      one list per DISTINCT WORKING WEEK per year
    sync_employee_holiday_lists() copies the shift's list down (FDR6)

Copying 21 finished lists instead would have shipped 14 that nothing points at,
including six pre-CAF ones (`Holiday List 2026`, `Leave for Emp Group A 2026`,
`Alternate First Saturday Off 2026`) that belong to the old site and must not
follow the app anywhere.

⚠️ AN EXISTING SHIFT IS REPORTED, NOT OVERWRITTEN — OD-88
---------------------------------------------------------
OD-88 settled this for the alternating pairs: `ensure_shifts()` re-applies only
`caf_shift_code` / `caf_alt_sat` / `caf_sat_mirror` and REPORTS drift on the
other thirteen parameters, so an HR edit survives a re-run. The same rule holds
here for all eighteen: a shift that already exists on the target has its
differences printed and is left alone unless `overwrite=1` is passed
deliberately. A migration script that silently reverts what HR changed on
prod-test is worse than one that stops.

⚠️ `process_attendance_after` IS SITE-LOCAL and is deliberately not carried —
it is a date tied to the site's own history. It is inert here anyway
(`enable_auto_attendance = 0` on all eighteen, which readiness check 14
watches), but on a site where somebody ticks that box it decides how far back
the hourly job reaches, and the authority site's date is meaningless there.
"""

import io
import json
import os

import frappe
from frappe.utils import getdate

PAYLOAD = os.path.join(os.path.dirname(__file__), "data", "shift_holiday_payload.json")

PH_LIST = "CAF Public Holidays {year}"

# Everything a Shift Type needs on a site that has never seen one of ours.
# `caf_sat_mirror` is a Link to another Shift Type and is carried separately, as
# a CODE, because the target's names are resolved in a second pass.
# `holiday_list` is omitted on purpose: generate_holiday_lists() sets it.
SHIFT_FIELDS = [
    "start_time", "end_time", "color",
    "enable_auto_attendance", "determine_check_in_and_check_out",
    "working_hours_calculation_based_on",
    "begin_check_in_before_shift_start_time", "allow_check_out_after_shift_end_time",
    "mark_auto_attendance_on_holidays",
    "working_hours_threshold_for_half_day", "working_hours_threshold_for_absent",
    "auto_update_last_sync",
    "enable_late_entry_marking", "late_entry_grace_period",
    "enable_early_exit_marking", "early_exit_grace_period",
    "caf_shift_code", "caf_allow_ot", "caf_ot_gate_minutes", "caf_ot_round_minutes",
    "caf_lunch_minutes",
    "caf_work_mon", "caf_work_tue", "caf_work_wed", "caf_work_thu",
    "caf_work_fri", "caf_work_sat", "caf_work_sun",
    "caf_alt_sat", "caf_sat_anchor_date", "caf_sat_anchor",
    "caf_required_punches", "caf_shift_family",
]


_INT_TYPES = {"Int", "Check"}
_FLOAT_TYPES = {"Float", "Currency", "Percent"}


def _norm(fieldname, value):
    """One JSON-safe representation of a field, used on BOTH sides.

    🔴 The first version stringified everything, and the create path threw:
    stock `Shift Type.validate()` does

        round(time_diff(end, start).total_seconds() / 60)
            + (self.allow_check_out_after_shift_end_time or 0)

    which is `int + "60"` when that Int arrives as a string — TypeError, inside
    `validate_circular_shift`, with `bench execute` masking it as
    `NameError: name 'caf' is not defined`. Report mode could never have caught
    it, because report mode never inserts anything. Dates and times still travel
    as strings, because JSON has no type for them and Frappe parses them back.
    """
    if value is None or value == "":
        return None
    ft = frappe.get_meta("Shift Type").get_field(fieldname)
    ft = ft.fieldtype if ft else "Data"
    if ft in _INT_TYPES:
        return int(value)
    if ft in _FLOAT_TYPES:
        return float(value)
    return str(value)


# ---------------------------------------------------------------- the payload

def _load():
    if not os.path.exists(PAYLOAD):
        frappe.throw(
            "%s does not exist. Run `export` on the authority site first — the "
            "payload is committed to git and travels with the app." % PAYLOAD
        )
    payload = json.loads(io.open(PAYLOAD, encoding="utf-8").read())
    # Coerce on the way IN, so a payload written by an older version of this
    # script — or hand-edited — reaches both the comparison and the insert in the
    # same shape. See `_norm`: an Int arriving as a string is what broke the
    # create path the first time.
    for row in payload.get("shifts", []):
        row["fields"] = {f: _norm(f, v) for f, v in row["fields"].items()}
    return payload


def export():
    """Read this site and write the payload. Changes nothing."""
    shifts = []
    for name in sorted(s.name for s in frappe.get_all("Shift Type")):
        doc = frappe.get_doc("Shift Type", name)
        if not doc.caf_shift_code:
            print("  ⚠️ SKIPPED %r — no caf_shift_code, so the target could not "
                  "match it (OD-96)" % name)
            continue
        row = {"label": name, "fields": {}}
        for f in SHIFT_FIELDS:
            row["fields"][f] = _norm(f, doc.get(f))
        mirror = doc.get("caf_sat_mirror")
        row["mirror_code"] = (
            frappe.db.get_value("Shift Type", mirror, "caf_shift_code") if mirror else None
        )
        shifts.append(row)

    holidays, ph_notes = {}, []
    for year in sorted({h.name[-4:] for h in frappe.get_all(
            "Holiday List", filters={"name": ["like", "CAF Public Holidays %"]})}):
        src = PH_LIST.format(year=year)
        rows = frappe.get_all("Holiday",
                              filters={"parent": src},
                              fields=["holiday_date", "description", "weekly_off"],
                              order_by="holiday_date")
        dated = [r for r in rows if not r.weekly_off]
        weekly = len(rows) - len(dated)
        if weekly:
            ph_notes.append(
                "%s carries %d weekly_off row(s) as well as %d dated holidays. Only "
                "the dated ones are exported — a public-holiday list is a list of "
                "gazette dates, and the weekly rows are what generate_holiday_lists() "
                "computes per working week (FBR23). Worth looking at on the authority "
                "site." % (src, weekly, len(dated)))
        holidays[str(year)] = [
            {"holiday_date": str(r.holiday_date), "description": r.description or ""}
            for r in dated
        ]

    placements, unmatchable = [], []
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "employee_name", "attendance_device_id",
                                    "default_shift"], order_by="name"):
        if not e.default_shift:
            unmatchable.append({"employee": e.name, "employee_name": e.employee_name,
                                "why": "no default_shift on the authority site"})
            continue
        if not e.attendance_device_id:
            unmatchable.append({"employee": e.name, "employee_name": e.employee_name,
                                "why": "no attendance_device_id, so no cross-site "
                                       "identity exists (T-32)"})
            continue
        placements.append({
            "device_id": str(e.attendance_device_id),
            "employee_name": e.employee_name,
            "shift_code": frappe.db.get_value("Shift Type", e.default_shift,
                                              "caf_shift_code"),
        })

    payload = {
        "generated_on": frappe.utils.now(),
        "generated_from": frappe.local.site,
        "shifts": shifts,
        "public_holidays": holidays,
        "placements": placements,
        "unmatchable": unmatchable,
        "notes": ph_notes,
    }

    os.makedirs(os.path.dirname(PAYLOAD), exist_ok=True)
    io.open(PAYLOAD, "w", encoding="utf-8", newline="\n").write(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    print("\nwrote %s" % PAYLOAD)
    print("  %d shift(s) · %d year(s) of public holidays (%s) · %d placement(s)"
          % (len(shifts), len(holidays),
             ", ".join("%s:%d" % (y, len(v)) for y, v in sorted(holidays.items())),
             len(placements)))
    for u in unmatchable:
        print("  ⚠️ not carried: %s %s — %s"
              % (u["employee"], u["employee_name"], u["why"]))
    for n in ph_notes:
        print("  ⚠️ %s" % n)
    print("\n🔴 COMMIT the payload — it is the record of what production was given.")
    # ⚠️ a summary, not the payload: `bench execute` prints whatever is returned,
    # and returning it dumped 34KB of JSON into the terminal on the first run.
    return {"shifts": len(shifts), "years": sorted(holidays),
            "placements": len(placements), "unmatchable": len(unmatchable),
            "path": PAYLOAD}


# ------------------------------------------------------------------- the plan

def _shift_plan(payload):
    """What each shift in the payload would do on THIS site."""
    plan = []
    for row in payload["shifts"]:
        code = row["fields"]["caf_shift_code"]
        existing = frappe.db.get_value("Shift Type", {"caf_shift_code": code}, "name")
        drift = {}
        if existing:
            doc = frappe.get_doc("Shift Type", existing)
            for f, want in row["fields"].items():
                got = _norm(f, doc.get(f))
                if got != want:
                    drift[f] = (got, want)
        plan.append({"code": code, "label": row["label"], "existing": existing,
                     "drift": drift, "mirror_code": row.get("mirror_code"),
                     "fields": row["fields"]})
    return plan


def _placement_plan(payload):
    """Device id -> employee on THIS site, and what their shift would become."""
    plan = []
    for p in payload["placements"]:
        hits = frappe.get_all("Employee",
                              filters={"attendance_device_id": p["device_id"]},
                              fields=["name", "employee_name", "status",
                                      "default_shift", "holiday_list"])
        want_shift = frappe.db.get_value("Shift Type",
                                         {"caf_shift_code": p["shift_code"]}, "name")
        problem = None
        emp = None
        if not hits:
            problem = "no employee on this site carries device id %r" % p["device_id"]
        elif len(hits) > 1:
            problem = ("%d employees carry device id %r: %s — ambiguous, refusing"
                       % (len(hits), p["device_id"], [h.name for h in hits]))
        else:
            emp = hits[0]
            got = " ".join((emp.employee_name or "").split()).lower()
            want = " ".join(p["employee_name"].split()).lower()
            if got != want:
                problem = ("device %s is %r here but %r on the authority site — the "
                           "id and the name disagree, so one of them is wrong"
                           % (p["device_id"], emp.employee_name, p["employee_name"]))
        if not problem and not want_shift:
            problem = ("no Shift Type on this site carries caf_shift_code %r — import "
                       "the shifts first" % p["shift_code"])
        plan.append({"device": p["device_id"], "expected": p["employee_name"],
                     "employee": emp, "want_shift": want_shift,
                     "shift_code": p["shift_code"], "problem": problem})
    return plan


# ----------------------------------------------------------------- the report

def run(apply=0, overwrite=0, years=None, current_year=None):
    payload = _load()
    apply, overwrite = int(apply), int(overwrite)

    print("\n%s\nSHIFT + CALENDAR MIGRATION  (T-34 rows 4+8)\n%s" % ("=" * 78, "=" * 78))
    print("payload generated %s from %s"
          % (payload["generated_on"], payload["generated_from"]))
    print("this site: %s\n" % frappe.local.site)

    # --- shifts --------------------------------------------------------------
    splan = _shift_plan(payload)
    create = [p for p in splan if not p["existing"]]
    drifted = [p for p in splan if p["existing"] and p["drift"]]
    same = [p for p in splan if p["existing"] and not p["drift"]]
    print("SHIFT TYPES: %d to create · %d already correct · %d differ"
          % (len(create), len(same), len(drifted)))
    for p in create:
        print("   + %-28s %s" % (p["label"], p["code"]))
    for p in drifted:
        print("   ~ %-28s %s  EXISTS as %r and differs on %d field(s):"
              % (p["label"], p["code"], p["existing"], len(p["drift"])))
        for f, (got, want) in sorted(p["drift"].items()):
            print("       %-38s here=%-22r payload=%r" % (f, got, want))
        if not overwrite:
            print("       ⚪ left alone (OD-88). Pass overwrite=1 to take the payload's "
                  "values — but read the list above first: on prod-test these are "
                  "HR's edits.")

    # --- public holidays -----------------------------------------------------
    print("\nPUBLIC HOLIDAYS")
    ph_todo = {}
    for year, rows in sorted(payload["public_holidays"].items()):
        name = PH_LIST.format(year=year)
        if frappe.db.exists("Holiday List", name):
            here = {str(r.holiday_date) for r in frappe.get_all(
                "Holiday", filters={"parent": name, "weekly_off": 0},
                fields=["holiday_date"])}
            missing = [r for r in rows if r["holiday_date"] not in here]
            extra = here - {r["holiday_date"] for r in rows}
            print("   %-28s exists · %d dated here · %d in payload · %d missing · "
                  "%d here-only" % (name, len(here), len(rows), len(missing), len(extra)))
            if extra:
                print("       ⚠️ %d date(s) exist here and NOT in the payload — this "
                      "site knows something the authority site does not. Left alone: "
                      "%s" % (len(extra), sorted(extra)[:6]))
            if missing:
                ph_todo[year] = missing
        else:
            print("   %-28s MISSING · %d date(s) to create" % (name, len(rows)))
            ph_todo[year] = rows

    # --- placements ----------------------------------------------------------
    pplan = _placement_plan(payload)
    refused = [p for p in pplan if p["problem"]]
    movers = [p for p in pplan
              if not p["problem"] and p["employee"].default_shift != p["want_shift"]]
    already = len(pplan) - len(refused) - len(movers)
    print("\nEMPLOYEE PLACEMENT: %d to move · %d already right · %d REFUSED"
          % (len(movers), already, len(refused)))
    for p in movers[:200]:
        print("   → device %-8s %-34s %s  →  %s"
              % (p["device"], p["expected"][:34],
                 p["employee"].default_shift or "(none)", p["want_shift"]))
    for p in refused:
        print("   🔴 device %-8s %-34s %s" % (p["device"], p["expected"][:34], p["problem"]))

    for u in payload.get("unmatchable", []):
        print("   ⚪ not in the payload at all: %s — %s" % (u["employee_name"], u["why"]))
    for n in payload.get("notes", []):
        print("   ⚠️ %s" % n)

    todo = len(create) + len(ph_todo) + len(movers) + (len(drifted) if overwrite else 0)
    if not apply:
        print("\n%s\n%d change(s) pending. Nothing was written." % ("-" * 78, todo))
        print("Run with --kwargs \"{'apply':1}\" to write them.")
        return {"pending": todo, "create": len(create), "drift": len(drifted),
                "movers": len(movers), "refused": len(refused)}

    return _apply(payload, splan, ph_todo, pplan, overwrite, years, current_year)


# ------------------------------------------------------------------ the write

def _apply(payload, splan, ph_todo, pplan, overwrite, years, current_year):
    frappe.set_user("Administrator")
    made, updated, holidays_written, moved, skipped = [], [], [], [], []

    # 1 · the shifts, without their mirror and without a holiday list ----------
    #     Both are Links that cannot resolve yet: the mirror is another shift in
    #     this same batch, and the calendars do not exist until step 3.
    for p in splan:
        if p["existing"]:
            if overwrite and p["drift"]:
                doc = frappe.get_doc("Shift Type", p["existing"])
                for f, (_got, want) in p["drift"].items():
                    doc.set(f, want)
                doc.flags.ignore_permissions = True
                doc.save()
                doc.add_comment("Comment",
                                "shift_holiday_migration overwrote %d field(s) from the "
                                "payload generated %s on %s: %s"
                                % (len(p["drift"]), payload["generated_on"],
                                   payload["generated_from"],
                                   ", ".join(sorted(p["drift"]))))
                updated.append(p["label"])
            continue
        doc = frappe.new_doc("Shift Type")
        doc.name = p["label"]
        for f, v in p["fields"].items():
            doc.set(f, v)
        doc.flags.ignore_permissions = True
        doc.insert()
        made.append(p["label"])

    frappe.db.commit()

    # 2 · the mirrors, now that both halves exist -----------------------------
    for p in splan:
        if not p.get("mirror_code"):
            continue
        me = frappe.db.get_value("Shift Type", {"caf_shift_code": p["code"]}, "name")
        other = frappe.db.get_value("Shift Type",
                                    {"caf_shift_code": p["mirror_code"]}, "name")
        if not me or not other:
            skipped.append("mirror %s -> %s: one half is missing"
                           % (p["code"], p["mirror_code"]))
            continue
        if frappe.db.get_value("Shift Type", me, "caf_sat_mirror") != other:
            frappe.db.set_value("Shift Type", me, "caf_sat_mirror", other)

    frappe.db.commit()

    # 3 · the gazette dates ---------------------------------------------------
    for year, rows in sorted(ph_todo.items()):
        name = PH_LIST.format(year=year)
        if frappe.db.exists("Holiday List", name):
            doc = frappe.get_doc("Holiday List", name)
        else:
            doc = frappe.new_doc("Holiday List")
            doc.holiday_list_name = name
            doc.from_date = "%s-01-01" % year
            doc.to_date = "%s-12-31" % year
        have = {str(h.holiday_date) for h in doc.holidays}
        for r in rows:
            if r["holiday_date"] in have:
                continue
            doc.append("holidays", {"holiday_date": r["holiday_date"],
                                    "description": r["description"], "weekly_off": 0})
            holidays_written.append("%s %s" % (name, r["holiday_date"]))
        doc.flags.ignore_permissions = True
        doc.save()

    frappe.db.commit()

    # 4 · the derived calendars, built by the module that owns them -----------
    from caf.caf import holiday_lists

    known = sorted(int(y) for y in payload["public_holidays"])
    current_year = int(current_year or getdate(frappe.utils.nowdate()).year)

    # 🔴 ONLY THE CURRENT YEAR AND LATER, and there are two independent reasons.
    #
    # 1. T-34's own policy: history is ⚪ leave. A migration lands in the current
    #    year and resolves forward; `resolve_day_type()` asks the employee's list
    #    for the WORK DATE's own year, so a year nobody will resolve needs no list.
    #
    # 2. ⚠️ It is not merely unnecessary, it THROWS. `alt_saturday_rest_days()`
    #    walks fortnightly from `caf_sat_anchor_date`, and refuses to walk
    #    backwards: "The anchor 2026-04-11 is after 2025; nothing to walk". So
    #    asking regenerate() for 2025 while the anchor sits in 2026 is a hard
    #    error, not a no-op. Found here on 2026-09-11 by the create-path proof.
    #    It is latent in `holiday_lists` and would bite anyone back-generating a
    #    year — logged rather than worked around, because the refusal is correct.
    wanted = [y for y in known if y >= current_year]
    skipped_years = [y for y in known if y < current_year]
    if not wanted:
        frappe.throw("The payload carries public holidays for %s and this site's "
                     "current year is %s — nothing to generate. Pass current_year "
                     "explicitly if that is deliberate." % (known, current_year))
    years = years or ",".join(str(y) for y in wanted)
    print("\nregenerating calendars for %s (current_year=%s)" % (years, current_year))
    if skipped_years:
        print("  ⚪ %s not generated — earlier than the current year, and T-34 "
              "leaves history alone" % skipped_years)
    holiday_lists.regenerate(years=years, current_year=current_year)

    # 5 · the people ----------------------------------------------------------
    for p in pplan:
        if p["problem"]:
            skipped.append("device %s: %s" % (p["device"], p["problem"]))
            continue
        e = p["employee"]
        if e.default_shift == p["want_shift"]:
            continue
        was = e.default_shift
        frappe.db.set_value("Employee", e.name, "default_shift", p["want_shift"])
        frappe.get_doc("Employee", e.name).add_comment(
            "Comment",
            "shift_holiday_migration: default_shift %s → %s (caf_shift_code %s), "
            "from the payload generated %s on %s. Matched by attendance_device_id %s "
            "(T-32 — HR-EMP ids are per-site). The holiday list follows in the same "
            "run (FDR6)."
            % (was or "(none)", p["want_shift"], p["shift_code"],
               payload["generated_on"], payload["generated_from"], p["device"]))
        moved.append((e.name, e.employee_name, was, p["want_shift"]))

    frappe.db.commit()

    # 6 · and the calendars follow the people, not the other way round --------
    #     Step 5 changed default_shift, so the copy-down has to run AFTER it or
    #     everyone who moved keeps the list of the shift they left.
    synced = holiday_lists.sync_employee_holiday_lists(current_year)
    frappe.db.commit()

    print("\n%s" % ("=" * 78))
    print("created %d shift(s): %s" % (len(made), made))
    print("overwrote %d shift(s): %s" % (len(updated), updated))
    print("wrote %d public-holiday row(s)" % len(holidays_written))
    print("moved %d employee(s):" % len(moved))
    for m in moved[:200]:
        print("    %s %-34s %s → %s" % (m[0], (m[1] or "")[:34], m[2] or "(none)", m[3]))
    print("holiday lists copied down onto %d employee(s)" % synced)
    print("skipped %d:" % len(skipped))
    for s in skipped:
        print("    %s" % s)
    return {"created": made, "overwrote": updated, "moved": len(moved),
            "synced": synced, "skipped": skipped}


# ----------------------------------------------------------------- the proof

def verify():
    """Both directions: what must now be true, and what must no longer be."""
    payload = _load()
    fails = 0

    def check(tag, ok, detail):
        nonlocal fails
        print("%-22s %s  %s" % (tag, "PASS" if ok else "FAIL", detail))
        if not ok:
            fails += 1

    codes = [s["fields"]["caf_shift_code"] for s in payload["shifts"]]
    here = {c: frappe.db.get_value("Shift Type", {"caf_shift_code": c}, "name")
            for c in codes}
    missing = [c for c, n in here.items() if not n]
    check("SHM-SHIFTS", not missing,
          "%d of %d payload shifts exist by caf_shift_code; missing %s"
          % (len(codes) - len(missing), len(codes), missing))

    # OD-96: a shift is resolved by code, so two shifts sharing one is fatal.
    dupes = {}
    for c in codes:
        n = frappe.db.count("Shift Type", {"caf_shift_code": c})
        if n > 1:
            dupes[c] = n
    check("SHM-CODES-UNIQUE", not dupes,
          "caf_shift_code is unique per shift; duplicates %s" % dupes)

    # FBR57: an alternating pair must be mutual, or one half alternates with nobody.
    broken = []
    for s in payload["shifts"]:
        if not s.get("mirror_code"):
            continue
        me = here.get(s["fields"]["caf_shift_code"])
        want = here.get(s["mirror_code"])
        got = frappe.db.get_value("Shift Type", me, "caf_sat_mirror") if me else None
        if got != want:
            broken.append((s["fields"]["caf_shift_code"], got, want))
    check("SHM-MIRRORS", not broken, "every alternating pair points at its partner; "
                                     "broken %s" % broken)

    for year, rows in sorted(payload["public_holidays"].items()):
        name = PH_LIST.format(year=year)
        have = {str(h.holiday_date) for h in frappe.get_all(
            "Holiday", filters={"parent": name, "weekly_off": 0},
            fields=["holiday_date"])}
        want = {r["holiday_date"] for r in rows}
        check("SHM-PH-%s" % year, not (want - have),
              "%d of %d gazette dates present; missing %s"
              % (len(want & have), len(want), sorted(want - have)[:5] or "none"))

    plan = _placement_plan(payload)
    wrong = [p for p in plan
             if not p["problem"] and p["employee"].default_shift != p["want_shift"]]
    refused = [p for p in plan if p["problem"]]
    check("SHM-PLACEMENT", not wrong,
          "%d of %d placements landed; %d refused (reported, never guessed)"
          % (len(plan) - len(wrong) - len(refused), len(plan), len(refused)))

    # 🔴 FDR6 — the half that is silent when it is wrong. Stock reads the
    # EMPLOYEE's list; a shift moved without its calendar means the person works
    # the new Saturdays while their leave is counted against the old ones.
    stale = []
    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "employee_name", "default_shift",
                                    "holiday_list"]):
        if not e.default_shift:
            continue
        want = frappe.db.get_value("Shift Type", e.default_shift, "holiday_list")
        if want and want != e.holiday_list:
            stale.append((e.employee_name, e.default_shift, e.holiday_list, want))
    check("SHM-FDR6", not stale,
          "every employee's holiday_list matches their shift's; stale %d %s"
          % (len(stale), stale[:4]))

    # ⚠️ readiness check 14 watches this too, but a migration is exactly when a
    # stock default could slip back in.
    auto = frappe.get_all("Shift Type", filters={"enable_auto_attendance": 1},
                          fields=["name"])
    check("SHM-NO-AUTO-ATT", not auto,
          "no Shift Type has enable_auto_attendance ticked; %s"
          % [a.name for a in auto])

    print("\n%s" % ("clean" if not fails else "%d problem(s)" % fails))
    return fails
