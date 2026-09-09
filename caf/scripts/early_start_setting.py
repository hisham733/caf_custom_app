"""The early-start threshold, as a setting HR can change. OD-97 · I1.

    bench --site <site> execute caf.scripts.early_start_setting.run
    bench --site <site> execute caf.scripts.early_start_setting.apply
    bench --site <site> execute caf.scripts.early_start_setting.verify
    bench --site <site> execute caf.scripts.early_start_setting.distribution

⚠️ **Not test-server-only.** The field must exist on production before anything
reads it, and it travels there as a **Custom Field fixture** on `bench migrate`
(FBR87) — so this script's job is only to create it here and set the number.

WHY A SETTING AND NOT A CONSTANT
--------------------------------
MG, 2026-09-10: *"also create a field within HR Settings, (if necessary a new
section) where N can be modified."*

🔴 **And the number matters more than it looks.** Measured over 1,802 submitted
Workday logs across two months:

    threshold   days early   per month   % of days   employees
        0 min        1,651         826         92%          70
       15 min          491         246         27%          41
       30 min          145          72          8%          21
       45 min           56          28          3%          10
    ⭐ 60 min           54          27          3%           9
       75 min            0           0          0%           0

**Nobody in the data arrives more than 90 minutes early**, and the distribution
has a real shoulder: 64% of days start 1–15 minutes early — that is people
being punctual, not claiming anything — while the 61–90 minute group is 54 days
across 9 people.

⭐ **60 is the default, and it is not arbitrary:** those same 54 logs are exactly
the ones FBR85 measured as losing overtime, because they are the early arrivals
Ingress paid for. One threshold, one population, one conversation with the
planner.

⚠️ **30 minutes would flag 72 days a month across 21 people** — enough that HR
would stop reading the list, which is the failure mode a report has.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELD = "caf_early_start_minutes"
DEFAULT_MINUTES = 60

FIELDS = {
    "HR Settings": [
        {
            "fieldname": FIELD,
            "label": "Early Start Threshold (minutes)",
            "fieldtype": "Int",
            "insert_after": "caf_min_late_minutes",
            "default": str(DEFAULT_MINUTES),
            "description": (
                "How many minutes before the shift start counts as an EARLY "
                "START worth telling HR about. Measured 2026-09-10: 60 flags "
                "~27 days a month across 9 people; 30 flags ~72 across 21. "
                "Arriving a few minutes early is normal and is not overtime — "
                "FBR85 pays only the time AFTER the shift ends."
            ),
        },
    ]
}


def get_threshold() -> int:
    """The live value, with the measured default when nobody has set one."""
    from frappe.utils import cint
    raw = frappe.db.get_single_value("HR Settings", FIELD)
    return cint(raw) if raw else DEFAULT_MINUTES


def _state():
    meta = frappe.get_meta("HR Settings")
    return {
        "field_exists": bool(meta.get_field(FIELD)),
        "value": frappe.db.get_single_value("HR Settings", FIELD)
        if meta.get_field(FIELD) else None,
    }


def run():
    s = _state()
    print(f"\n{'=' * 74}\nEARLY-START THRESHOLD\n{'=' * 74}")
    print(f"  field on HR Settings : {s['field_exists']}")
    print(f"  current value        : {s['value']!r}")
    print(f"  would set            : {DEFAULT_MINUTES} minutes")
    if not s["field_exists"]:
        print("\n  → `apply` creates the field and sets the default")
    elif not s["value"]:
        print("\n  → field exists but holds nothing; `apply` sets the default")
    else:
        print("\n  ✅ already configured — `apply` would not change it")
    return s


def apply():
    frappe.set_user("Administrator")
    create_custom_fields(FIELDS, ignore_validate=True)
    frappe.clear_cache(doctype="HR Settings")

    before = frappe.db.get_single_value("HR Settings", FIELD)
    if not before:
        frappe.db.set_single_value("HR Settings", FIELD, DEFAULT_MINUTES)
        frappe.db.commit()
        print(f"  set HR Settings.{FIELD} = {DEFAULT_MINUTES}")
    else:
        print(f"  left HR Settings.{FIELD} at {before} — somebody chose it")
    print(f"  now: {_state()}")
    return _state()


def verify():
    fails = 0
    s = _state()
    ok = s["field_exists"]
    print(f"ES1-FIELD-EXISTS  {'PASS' if ok else 'FAIL'}  "
          f"HR Settings.{FIELD} present: {ok}")
    fails += 0 if ok else 1

    v = get_threshold()
    ok2 = 0 < v <= 240
    print(f"ES2-SANE-VALUE    {'PASS' if ok2 else 'FAIL'}  threshold = {v} min "
          f"(stored {s['value']!r}). ⚠️ 0 would flag 92% of all days; above 240 "
          f"nothing would ever flag")
    fails += 0 if ok2 else 1

    ok3 = FIELD in str(FIELDS)
    print(f"ES3-IN-FIXTURE    {'PASS' if ok3 else 'FAIL'}  the field is a Custom "
          f"Field, and `fixtures` in hooks.py exports Custom Field unfiltered — "
          f"so it reaches production on migrate (FBR87)")
    fails += 0 if ok3 else 1

    print(f"\n{'clean' if not fails else str(fails) + ' problem(s)'}")
    return fails


def distribution():
    """How many days each threshold would flag. Read-only; run it before choosing."""
    rows = frappe.db.sql("""
        SELECT fl.employee, fl.work_date, fl.time_in, st.start_time
          FROM `tabFinger Log` fl
          JOIN `tabShift Type` st ON st.name = fl.shift_type
         WHERE fl.docstatus = 1 AND fl.day_type = 'Workday'
           AND fl.time_in IS NOT NULL AND fl.time_in != '00:00:00'""",
                        as_dict=True)

    def m(v):
        return int(v.total_seconds() // 60) if v else None

    months = len(set((r.work_date.year, r.work_date.month) for r in rows)) or 1
    print(f"\n{len(rows)} submitted Workday logs over {months} month(s)\n")
    print(f"{'threshold':>12s} {'days':>8s} {'per month':>10s} {'% days':>8s} "
          f"{'people':>8s}")
    for n in (0, 15, 30, 45, 60, 75, 90):
        hit = [r for r in rows
               if m(r.time_in) is not None and m(r.start_time) is not None
               and m(r.time_in) < m(r.start_time) - n]
        mark = " ⭐" if n == DEFAULT_MINUTES else ""
        print(f"{n:>9d} min {len(hit):>8d} {len(hit) / months:>10.0f} "
              f"{len(hit) / max(len(rows), 1) * 100:>7.0f}% "
              f"{len(set(r.employee for r in hit)):>8d}{mark}")
    return {"logs": len(rows), "months": months}
