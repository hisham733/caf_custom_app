"""Split `caf_lunch_minutes`'s double duty — add the punch-requirement gate.

    bench --site <site> execute caf.scripts.required_punches_setup.run
    bench --site <site> execute caf.scripts.required_punches_setup.run --kwargs "{'apply':1}"

MG's decision, 2026-08-22 (`ShiftTypeDesign_2026-08-22.md`).

THE PROBLEM THIS ENDS
---------------------
`caf_lunch_minutes` answered two different questions with one number:

    "how much lunch do I deduct?"    net_minutes() · compute()'s fallback
    "must there be a lunch punch?"   required_punches()

For 8 employees those answers differ — they TAKE lunch (deduct it) and never TAP
for it (do not demand it). The only way to say the second today is
`caf_lunch_minutes = 0`, which also stops the deduction and inflates their hours by
an hour a day. Hence a separate field for the gate.

Measured cost of leaving it: **214 held days across 8 people**, none of which can
ever become an Attendance record, and a held-draft worklist that is ~97% noise —
so the six genuine miss-punches inside it are invisible.

THE THREE OPTIONS
-----------------
    In + Out + Lunch pair   the default — 12 of 14 shifts, unchanged behaviour
    In + Out only           drivers · Chen — lunch still DEDUCTED, just not demanded
    In OR Out only          at least one punch — Mun Geet · Nin Geet · Seriramulu

⚠️ Only three, not four. Measured 1 May–16 Aug: **nobody is out-only as a habit** —
it appears only as a stray (2–6 days in 58–104) for otherwise-normal people. The two
who matter (Seriramulu 10 in-only + 3 out-only, Ehsan 16 + 12) are visibly MIXED, so
splitting in-only from out-only would force HR to answer a question with no stable
answer. It also lets the long-distance driver's Friday `out` share an option with
his Monday `in` (S3).

⚠️ `In OR Out only` FORCES `caf_allow_ot = 0` — enforced in `overrides/shift_type.py`.
On a single punch `work = net` is an ASSUMPTION, not a measurement; overtime on top
would stack an unverifiable number on an unverified one.
"""

import frappe

FIELDS = [
    {
        "dt": "Shift Type",
        "fieldname": "caf_required_punches",
        "label": "Required Punches",
        "fieldtype": "Select",
        "options": "\n".join(["In + Out + Lunch pair", "In + Out only",
                              "In OR Out only"]),
        "default": "In + Out + Lunch pair",
        "insert_after": "caf_lunch_minutes",
        "description": (
            "Which punches a day must have before it can become an Attendance "
            "record. <b>Lunch is still DEDUCTED either way</b> — this only decides "
            "what must be RECORDED. 'In OR Out only' credits the full contracted "
            "day from a single punch and therefore forbids overtime."),
    },
    {
        "dt": "Shift Type",
        "fieldname": "caf_shift_family",
        "label": "Shift Family",
        "fieldtype": "Data",
        "insert_after": "caf_shift_code",
        "description": (
            "Grouping for HR only — nothing reads it. The convention is the "
            "CONTRACTED DAY: start · end · lunch. Shifts in one family produce the "
            "same contracted hours, so moving somebody between them changes the "
            "rules but never the pay basis."),
    },
]

# MG + HR, 2026-08-22. Built from the machine's own record, 1 May – 16 Aug 2026.
ASSIGNMENTS = {
    "In OR Out only": [
        ("HR-EMP-00062", "Mun Geet Ow Yong", "60 in-only of 64 days"),
        ("HR-EMP-00008", "Ow Yong Nin Geet", "66 in-only of 68 days"),
        ("HR-EMP-00075", "Seriramulu A/L Apanah", "10 in-only + 3 out-only of 13"),
    ],
    "In + Out only": [
        ("HR-EMP-00006", "Chen Xiao Natalie", "64 in+out of 71 days"),
        ("HR-EMP-00065", "Muhammad Aliff", "59 in+out of 76 days"),
        ("HR-EMP-00013", "Mohd Hairy", "56 in+out of 79 days"),
        ("HR-EMP-00139", "Meor Danial Rieza", "50 in+out of 73 days"),
        ("HR-EMP-00099", "Mohammad Ehsan", "13 in+out · 16 in-only · 12 out-only "
                                           "— ⚠️ erratic, HR's call, re-check in a month"),
    ],
}


def backfill_zero_lunch_shifts(apply=0):
    """🔴 Preserve the behaviour of shifts that never wanted a lunch punch.

    Adding the Custom Field with `default: "In + Out + Lunch pair"` made Frappe
    stamp that value onto EVERY existing Shift Type — which is right for the 12
    shifts carrying `caf_lunch_minutes = 60` (it matches what they already did) and
    WRONG for the two carrying 0.

    `special` and `8:30am no Sat` have always needed only in+out, because demanding
    a lunch punch on a shift with no lunch would manufacture a false miss-punch on
    every row. The default silently reversed that.

    Caught by `test_chunk3_decisions` OD-58c, which asserts exactly this property —
    an existing test that already knew the rule and refused the change. Without it
    the director on `special` would have started being held every day.
    """
    changed = []
    for s in frappe.get_all("Shift Type",
                            filters={"caf_lunch_minutes": ("in", [0, None])},
                            fields=["name", "caf_required_punches"]):
        if s.caf_required_punches == "In + Out only":
            continue
        print(f"    {s.name:26s} {s.caf_required_punches!r} → 'In + Out only'")
        if apply:
            frappe.db.set_value("Shift Type", s.name, "caf_required_punches",
                                "In + Out only", update_modified=False)
        changed.append(s.name)
    return changed


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")
    acted = []

    for spec in FIELDS:
        exists = frappe.db.exists("Custom Field",
                                  {"dt": spec["dt"], "fieldname": spec["fieldname"]})
        print(f"  {spec['fieldname']:24s} {'exists' if exists else '🔴 MISSING'}")
        if apply and not exists:
            from frappe.custom.doctype.custom_field.custom_field import create_custom_field
            create_custom_field(spec["dt"], spec, ignore_validate=True)
            acted.append(spec["fieldname"])

    print("\n  Zero-lunch shifts whose behaviour the default would have changed:")
    zero = backfill_zero_lunch_shifts(apply)
    if not zero:
        print("    (none — all correct)")
    else:
        acted.extend(f"backfilled {z}" for z in zero)

    print("\n  Shifts and their punch rule:")
    for s in frappe.get_all("Shift Type",
                            fields=["name", "caf_lunch_minutes", "caf_allow_ot",
                                    "caf_required_punches"], order_by="name"):
        n = frappe.db.count("Employee", {"status": "Active", "default_shift": s.name})
        print(f"    {s.name:26s} lunch={s.caf_lunch_minutes or 0:<4} "
              f"ot={s.caf_allow_ot or 0}  rule={s.caf_required_punches or '(unset)'}"
              f"  emp={n}")

    print("\n  Employees needing a non-default rule:")
    for rule, people in ASSIGNMENTS.items():
        for emp, name, why in people:
            cur = frappe.db.get_value("Employee", emp, "default_shift")
            cur_rule = frappe.db.get_value("Shift Type", cur,
                                           "caf_required_punches") if cur else None
            flag = "ok" if cur_rule == rule else "🔴 needs a shift with this rule"
            print(f"    {name:24s} {rule:18s} on {cur or '—':22s} {flag}")
            print(f"      evidence: {why}")

    if not apply:
        print("\n(report only — pass apply=1 to add the fields)")
        return {"missing_fields": [f["fieldname"] for f in FIELDS
                                   if not frappe.db.exists(
                                       "Custom Field",
                                       {"dt": f["dt"], "fieldname": f["fieldname"]})]}

    frappe.db.commit()
    frappe.clear_cache()
    print(f"\nDONE — added {acted or 'nothing (already present)'}")
    return {"added": acted}
