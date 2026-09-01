"""Create the four punch-rule Shift Types and move the eight employees onto them.

    bench --site <site> execute caf.scripts.shift_punch_rule_rollout.run
    bench --site <site> execute caf.scripts.shift_punch_rule_rollout.run --kwargs "{'apply':1}"
    bench --site <site> execute caf.scripts.shift_punch_rule_rollout.refresh_held_drafts
    bench --site <site> execute caf.scripts.shift_punch_rule_rollout.verify

MG's decision, `ShiftTypeDesign_2026-08-22.md` §8. The FIELD (`caf_required_punches`)
and the OT guard shipped in `bca6281` and are green; this is the DATA half —
`required_punches_setup.run` reported *"needs a shift with this rule"* for all eight
because no such shift existed yet.

⚠️ **Not test-server-only.** Production carries the same eight people on the same
three source shifts. Report first, read it, then apply.

WHY A NEW SHIFT PER RULE RATHER THAN EDITING THE EXISTING ONE
-------------------------------------------------------------
`8:30am Schedule` carries **31 active employees**. Setting its punch rule to
`In + Out only` would relax the gate for all 31 to fix 4 — and `overrides/shift_type.
warn_on_mixed_population()` exists precisely to say so. MG's rule, 2026-08-22: *an
employee follows every parameter of the shift they are assigned to*, so a shift must
never hold two people who need different treatment. Hence a clone per rule.

Each new shift is an **exact copy** of the shift its people are on today — same
`start_time`, `end_time`, `caf_lunch_minutes`, weekday flags and `holiday_list` — with
exactly one thing changed (two for Seriramulu). That is what makes the move safe:

    net_minutes() = end - start - lunch      -> identical, so contracted hours are identical
    caf_work_<dow> + holiday_list            -> identical, so every day_type is identical
    caf_alt_sat = 0, caf_sat_mirror = NULL   -> the new shifts do not alternate (MG, 2026-09-01)

so the ONLY behaviour that changes is the gate, which is the point.

🔴 `Employee.default_shift` HAS NO DATE DIMENSION
------------------------------------------------
Moving it re-points the employee's WHOLE history, not just the future. Accepted here
for the same reason `alt_saturday_setup.assign_employees()` accepted it, plus one
measured check: because the clone is parameter-identical, a re-resolve of any past
date returns the same `day_type`, the same `caf_work_hours` and the same `short`. The
only field that could have moved is Seriramulu's OT — measured 2026-09-01,
**0 of his 38 logs carry any overtime at all** (raw or credited), so the OT flag
flip changes no existing number either.

Stored values are not rewritten by this script. `refresh_held_drafts()` below does
that, deliberately and separately.

SERIRAMULU'S OT — CONFIRMED, NOT INFERRED
-----------------------------------------
He is on `8am Schedule`, which has `caf_allow_ot = 1`, and `In OR Out only` forbids
overtime. Rather than infer it from the move, HR was asked. MG, 2026-09-01:
*"Seriramulu is a special case, where he only finger log machine, log for in once a
week (on average) — yes he has no OT."* His 13 punched days in three and a half
months are consistent with that.
"""

import frappe
from frappe.utils import cint

from caf.caf.overrides.shift_type import derive_family
from caf.caf.work_hours import PUNCH_EITHER, PUNCH_IN_OUT

# Fields that must NEVER be carried from the source shift onto the clone.
# `caf_alt_sat` and its three companions because the new shifts do not alternate
# (MG, 2026-09-01) and `shift_roster.alt_shifts()` selects on `caf_alt_sat = 1` —
# a stray 1 here would silently enrol these people in the mirror-group roster
# check. `last_sync_of_checkin` because it is a per-shift watermark, not a setting.
CLEAR_ON_CLONE = {
    "caf_alt_sat": 0,
    "caf_sat_mirror": None,
    "caf_sat_anchor": None,
    "caf_sat_anchor_date": None,
    "last_sync_of_checkin": None,
}

# One entry per NEW shift. `clone_of` is also the ASSERTION: every employee listed
# must actually be on that shift today, or the plan was written against stale data
# and the run refuses. See `_preconditions()`.
NEW_SHIFTS = [
    {
        "name": "8:30am In or Out",
        "code": "8_30AM_IN_OR_OUT",
        "clone_of": "8:30am Schedule",
        "rule": PUNCH_EITHER,
        "allow_ot": 0,
        "people": [
            ("HR-EMP-00062", "Mun Geet Ow Yong", "60 in-only of 64 days"),
            ("HR-EMP-00008", "Ow Yong Nin Geet", "66 in-only of 68 days"),
        ],
    },
    {
        "name": "8am In or Out",
        "code": "8AM_IN_OR_OUT",
        "clone_of": "8am Schedule",
        "rule": PUNCH_EITHER,
        # 🔴 The one parameter that is NOT cloned. `8am Schedule` allows OT;
        # `In OR Out only` forbids it, and Shift Type.validate() would throw if
        # this were left at 1 — which is the guard doing its job, not a bug.
        "allow_ot": 0,
        "people": [
            ("HR-EMP-00075", "Seriramulu A/L Apanah", "10 in-only + 3 out-only of 13"),
        ],
    },
    {
        "name": "8:30am In and Out",
        "code": "8_30AM_IN_AND_OUT",
        "clone_of": "8:30am Schedule",
        "rule": PUNCH_IN_OUT,
        "allow_ot": None,               # clone whatever the source says (0)
        "people": [
            ("HR-EMP-00065", "Muhammad Aliff Bin Mohd Azhar", "59 in+out of 76 days"),
            ("HR-EMP-00013", "Mohd Hairy Bin Abd Latif", "56 in+out of 79 days"),
            ("HR-EMP-00139", "Meor Danial Rieza Bin  Meor Zamzuri", "50 in+out of 73 days"),
            ("HR-EMP-00099", "Mohammad Ehsan Bin Firdaus",
             "13 in+out · 16 in-only · 12 out-only — ⚠️ erratic, HR's call, "
             "re-check a month after go-live"),
        ],
    },
    {
        "name": "8am In and Out no Sat",
        "code": "8AM_IN_AND_OUT_NO_SAT",
        "clone_of": "8am no OT no Sat",
        "rule": PUNCH_IN_OUT,
        "allow_ot": None,
        "people": [
            ("HR-EMP-00006", "Chen Xiao Natalie", "64 in+out of 71 days"),
        ],
    },
]

EMPLOYEES = [(e, who, why, s["name"], s["clone_of"])
             for s in NEW_SHIFTS for e, who, why in s["people"]]


# --------------------------------------------------------------- shift family

def backfill_families(apply=0):
    """Give every shift a family label. Report-only unless `apply`."""
    changed = []
    for s in frappe.get_all("Shift Type",
                            fields=["name", "start_time", "end_time",
                                    "caf_lunch_minutes", "caf_shift_family"],
                            order_by="start_time, end_time, name"):
        want = derive_family(s)
        if (s.caf_shift_family or "") == want:
            continue
        if s.caf_shift_family:
            # Somebody typed something. Leave it — the field is HR's to own.
            print(f"    = {s.name:26s} keeps HR's label {s.caf_shift_family!r} "
                  f"(derived would be {want!r})")
            continue
        print(f"    + {s.name:26s} family -> {want}")
        if apply:
            frappe.db.set_value("Shift Type", s.name, "caf_shift_family", want,
                                update_modified=False)
        changed.append(s.name)
    return changed


# --------------------------------------------------------------- preconditions

def _preconditions():
    """Refuse loudly if the ground has moved since the design was written.

    Four things are checked, and each one has a way of being false in a way that
    would make the run wrong rather than merely noisy:

      the field exists     — `required_punches_setup` must have run first
      the source exists    — a renamed shift would clone the wrong parameters
      the people are on it — somebody moved since 2026-08-22, so their evidence
                             (the punch counts in `people`) no longer describes
                             the shift they are actually on
      nobody is amended    — an employee already on a target shift means a partial
                             earlier run; reported, not treated as an error
    """
    problems, notes = [], []

    if not frappe.db.exists("Custom Field",
                            {"dt": "Shift Type", "fieldname": "caf_required_punches"}):
        problems.append("caf_required_punches does not exist — run "
                        "caf.scripts.required_punches_setup.run --kwargs \"{'apply':1}\" first")
        return problems, notes

    targets = {s["name"] for s in NEW_SHIFTS}
    for spec in NEW_SHIFTS:
        if not frappe.db.exists("Shift Type", spec["clone_of"]):
            problems.append(f"source shift {spec['clone_of']!r} does not exist")

    for emp, who, _why, want_shift, clone_of in EMPLOYEES:
        cur = frappe.db.get_value("Employee", emp,
                                  ["employee_name", "status", "default_shift"],
                                  as_dict=True)
        if not cur:
            problems.append(f"{emp} {who} NOT FOUND")
            continue
        if cur.status != "Active":
            problems.append(f"{emp} {who} is {cur.status}, not Active")
        if cur.default_shift == want_shift:
            notes.append(f"{emp} {who} is ALREADY on {want_shift} — earlier run")
        elif cur.default_shift != clone_of:
            problems.append(
                f"{emp} {who} is on {cur.default_shift!r}, but the plan assumed "
                f"{clone_of!r}. Their punch evidence describes the old shift — "
                f"re-check with HR before moving them")
    return problems, notes


# --------------------------------------------------------------- create + move

def _create_shift(spec):
    """Clone the source Shift Type, change only the rule (and Seriramulu's OT).

    `copy_doc` rather than a hand-listed field copy: it walks the meta, so a field
    added to Shift Type later is carried without anyone remembering to add it here.
    It also honours `no_copy`, which is what keeps the watermark fields out.
    """
    src = frappe.get_doc("Shift Type", spec["clone_of"])
    doc = frappe.copy_doc(src)
    doc.__newname = spec["name"]
    doc.caf_shift_code = spec["code"]
    doc.caf_required_punches = spec["rule"]
    if spec["allow_ot"] is not None:
        doc.caf_allow_ot = cint(spec["allow_ot"])
    for field, value in CLEAR_ON_CLONE.items():
        doc.set(field, value)
    doc.caf_shift_family = derive_family(src)
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


MOVE_TRAIL = "Default shift moved by caf.scripts.shift_punch_rule_rollout"


def _note_move(emp, was, now, why):
    """The audit trail, because `db.set_value` writes NO Version (OD-26).

    `re_resolve.py` established the pattern: where a change has to go through
    `db_set` — here because saving an Employee runs the whole stock controller
    over legacy records that were never clean — the **comment is the trail**. A
    person's shift decides their hours, their rest days and what their appraisal
    counts; changing it with no before/after record is the audit hole OD-26 exists
    to close.

    Idempotent, so re-running the rollout does not stack duplicate comments.
    """
    if frappe.db.exists("Comment", {"reference_doctype": "Employee",
                                    "reference_name": emp,
                                    "content": ("like", f"%{MOVE_TRAIL}%")}):
        return False
    frappe.get_doc("Employee", emp).add_comment("Comment", (
        f"{MOVE_TRAIL}: default shift <b>{was}</b> ➜ <b>{now}</b>. "
        f"Punch rule only — start, end, lunch, weekday flags and holiday list are "
        f"identical, so contracted hours and every day_type are unchanged. "
        f"Evidence: {why}. MG + HR, ShiftTypeDesign_2026-08-22.md §8."))
    return True


def stamp_move_trail(apply=0):
    """Add the move comment to anybody already moved without one.

    Exists because the first apply on the dev site ran before `_note_move` did —
    the trail is worth having on those eight too, and on production this is a
    no-op because `run` writes the comment as it moves.
    """
    apply = cint(apply)
    frappe.set_user("Administrator")
    added = []
    for emp, who, why, want_shift, clone_of in EMPLOYEES:
        cur = frappe.db.get_value("Employee", emp, "default_shift")
        if cur != want_shift:
            continue
        has = frappe.db.exists("Comment", {"reference_doctype": "Employee",
                                           "reference_name": emp,
                                           "content": ("like", f"%{MOVE_TRAIL}%")})
        print(f"    {'has trail' if has else '+ ADD    '}  {emp} {who[:30]}")
        if not has and apply and _note_move(emp, clone_of, want_shift, why):
            added.append(emp)
    if apply:
        frappe.db.commit()
    print(f"\n{'added ' + str(len(added)) if apply else '(report only — pass apply=1)'}")
    return {"added": added}


def _held(employees):
    """Draft Finger Logs held by the gate, per employee. The number MG is fixing."""
    rows = frappe.get_all("Finger Log",
                          filters={"employee": ("in", employees), "docstatus": 0,
                                   "caf_not_full_day": 1},
                          fields=["employee", "name"])
    out = {}
    for r in rows:
        out[r.employee] = out.get(r.employee, 0) + 1
    return out


def run(apply=0):
    apply = cint(apply)
    frappe.set_user("Administrator")

    problems, notes = _preconditions()
    for n in notes:
        print(f"  note: {n}")
    if problems:
        print("\n🔴 STOP — the plan does not match the site:")
        for p in problems:
            print(f"    {p}")
        return {"blocked": problems}
    print("✅ preconditions: the field exists, all 4 source shifts exist, and all "
          "8 employees are where the design said they were")

    print("\n  Shift families (start · end · lunch):")
    backfill_families(apply)

    print("\n  New shifts:")
    made = []
    for spec in NEW_SHIFTS:
        src = frappe.db.get_value(
            "Shift Type", spec["clone_of"],
            ["start_time", "end_time", "caf_lunch_minutes", "caf_allow_ot",
             "holiday_list", "caf_work_sat"], as_dict=True)
        ot = src.caf_allow_ot if spec["allow_ot"] is None else spec["allow_ot"]
        ot_note = ""
        if spec["allow_ot"] is not None and cint(src.caf_allow_ot) != cint(spec["allow_ot"]):
            ot_note = f"  🔴 OT {src.caf_allow_ot} -> {spec['allow_ot']} (HR confirmed)"
        exists = frappe.db.exists("Shift Type", spec["name"])
        print(f"    {'exists' if exists else '+ CREATE'}  {spec['name']:24s} "
              f"clone of {spec['clone_of']:20s} rule={spec['rule']:22s} "
              f"ot={ot} sat={src.caf_work_sat} list={src.holiday_list}{ot_note}")
        for _e, who, why in spec["people"]:
            print(f"                {who[:34]:34s} {why}")
        if apply and not exists:
            made.append(_create_shift(spec))

    print("\n  Employee moves:")
    moved = []
    for emp, who, why, want_shift, clone_of in EMPLOYEES:
        cur = frappe.db.get_value("Employee", emp, "default_shift")
        if cur == want_shift:
            print(f"    =  {emp} {who[:30]:30s} already on {want_shift}")
            continue
        want_list = frappe.db.get_value("Shift Type", want_shift, "holiday_list") \
            if frappe.db.exists("Shift Type", want_shift) else \
            frappe.db.get_value("Shift Type", clone_of, "holiday_list")
        print(f"    -> {emp} {who[:30]:30s} {cur:22s} -> {want_shift:22s} list={want_list}")
        if apply:
            frappe.db.set_value("Employee", emp, "default_shift", want_shift)
            # FDR6 — stock's leave day counting and `is_holiday()` read the
            # EMPLOYEE's list and know nothing about shifts, so it is copied down.
            # A no-op here (the clone carries the source's list) but asserted
            # rather than assumed, because a silent mismatch changes leave maths.
            frappe.db.set_value("Employee", emp, "holiday_list", want_list)
            _note_move(emp, cur, want_shift, why)
            moved.append(emp)

    held = _held([e for e, *_ in EMPLOYEES])
    print(f"\n  Held drafts today (caf_not_full_day = 1): {sum(held.values())}")
    for emp, who, _why, _s, _c in EMPLOYEES:
        print(f"    {emp} {who[:30]:30s} {held.get(emp, 0):3d}")
    print("  ⚠️ These are STORED verdicts — moving the shift does not rewrite them."
          "\n     Run `refresh_held_drafts` to re-save them under the new rule.")

    if not apply:
        print("\n(report only — pass apply=1 to create the shifts and move the people)")
        return {"to_create": [s["name"] for s in NEW_SHIFTS
                              if not frappe.db.exists("Shift Type", s["name"])],
                "to_move": len([1 for e, _w, _y, s, _c in EMPLOYEES
                                if frappe.db.get_value("Employee", e, "default_shift") != s]),
                "held": sum(held.values())}

    frappe.db.commit()
    frappe.clear_cache()
    print(f"\nDONE — created {made or 'nothing (already present)'}; moved {len(moved)}")
    return {"created": made, "moved": moved}


# --------------------------------------------------------- the held backlog

def refresh_held_drafts(apply=0, employees=None):
    """Re-save the held DRAFTS so the new punch rule reaches the backlog.

    Separate from `run` and separately approved, because it is the only part that
    rewrites stored values. `run` changes what the rules ARE; this re-asks the
    question of days already answered.

    **Drafts only, on purpose.** `Finger Log.validate()` recomputes `day_type`,
    `caf_work_hours`, `short`, `ot_in_hour` and `caf_not_full_day` on any save
    while `docstatus != 1`, so a plain `save()` is the whole mechanism. Submitted
    logs are NOT touched here — those go through `caf.caf.re_resolve`, and none of
    them is held anyway (a held day cannot submit: `before_submit` throws, OD-58).

    ⚠️ It does not SUBMIT anything. A day that stops being held becomes a day HR
    *can* decide, not one already decided. Submission stays a human act — or the
    next import's, which updates its own drafts.
    """
    apply = cint(apply)
    frappe.set_user("Administrator")
    employees = employees or [e for e, *_ in EMPLOYEES]

    rows = frappe.get_all("Finger Log",
                          filters={"employee": ("in", employees), "docstatus": 0},
                          fields=["name", "employee", "employee_name", "work_date",
                                  "caf_not_full_day"],
                          order_by="employee, work_date")
    print(f"  {len(rows)} draft Finger Log(s) for {len(employees)} employee(s); "
          f"{sum(1 for r in rows if r.caf_not_full_day)} held")

    cleared, still_held, errors = [], [], []
    for r in rows:
        sp = f"rp_{r.name}".replace("-", "_")[:60]
        frappe.db.savepoint(sp)
        try:
            doc = frappe.get_doc("Finger Log", r.name)
            doc.flags.ignore_permissions = True
            if apply:
                doc.save(ignore_permissions=True)
                after = cint(doc.caf_not_full_day)
            else:
                # Dry run: run the same derivation, write nothing.
                doc.resolve_shift_and_day_type()
                doc.det_work_hours()
                after = cint(doc.caf_not_full_day)
                frappe.db.rollback(save_point=sp)
            if cint(r.caf_not_full_day) and not after:
                cleared.append(r)
            elif after:
                still_held.append(r)
        except Exception as e:
            frappe.db.rollback(save_point=sp)
            errors.append((r.name, str(e).splitlines()[0][:110]))

    by_emp = {}
    for r in cleared:
        by_emp.setdefault(r.employee_name, [0, 0])[0] += 1
    for r in still_held:
        by_emp.setdefault(r.employee_name, [0, 0])[1] += 1

    print(f"\n  {'employee':34s} {'clears':>7s} {'still held':>11s}")
    for who, (c, h) in sorted(by_emp.items()):
        print(f"  {who[:34]:34s} {c:7d} {h:11d}")
    print(f"\n  {len(cleared)} day(s) stop being held; {len(still_held)} remain")

    if still_held:
        print("\n  Still held — a genuine miss-punch, not the rule:")
        for r in still_held[:15]:
            print(f"    {r.work_date} {r.employee_name[:30]:30s} {r.name}")
        if len(still_held) > 15:
            print(f"    … and {len(still_held) - 15} more")
    for name, err in errors:
        print(f"  🔴 {name}: {err}")

    if not apply:
        print("\n(report only — pass apply=1 to re-save the drafts)")
        return {"would_clear": len(cleared), "would_remain": len(still_held),
                "errors": errors}

    frappe.db.commit()
    print(f"\nDONE — re-saved {len(rows)} draft(s). They are still DRAFTS: a day "
          f"that stopped being held is one HR can now decide, not one already decided.")
    return {"cleared": len(cleared), "remaining": len(still_held), "errors": errors}


# ---------------------------------------------------------------------- verify

def verify():
    """Assert the end state in both directions — the shifts and the people."""
    frappe.set_user("Administrator")
    bad = []

    for spec in NEW_SHIFTS:
        row = frappe.db.get_value(
            "Shift Type", spec["name"],
            ["start_time", "end_time", "caf_lunch_minutes", "caf_allow_ot",
             "caf_required_punches", "holiday_list", "caf_alt_sat",
             "caf_work_sat", "caf_shift_family"], as_dict=True)
        if not row:
            bad.append(f"{spec['name']} does not exist")
            continue
        src = frappe.db.get_value(
            "Shift Type", spec["clone_of"],
            ["start_time", "end_time", "caf_lunch_minutes", "holiday_list",
             "caf_work_sat"], as_dict=True)

        # The clone must be parameter-identical where it matters, or the "moving
        # somebody between them cannot change their pay basis" claim is false.
        for f in ("start_time", "end_time", "caf_lunch_minutes", "holiday_list",
                  "caf_work_sat"):
            if str(row[f]) != str(src[f]):
                bad.append(f"{spec['name']}.{f} = {row[f]!r}, source has {src[f]!r}")
        if row.caf_required_punches != spec["rule"]:
            bad.append(f"{spec['name']}.caf_required_punches = "
                       f"{row.caf_required_punches!r}, want {spec['rule']!r}")
        if row.caf_alt_sat:
            bad.append(f"{spec['name']} carries caf_alt_sat = 1 — it would be "
                       f"picked up by the mirror-group roster check")
        if spec["rule"] == PUNCH_EITHER and row.caf_allow_ot:
            bad.append(f"🔴 {spec['name']} allows OT on a single-punch rule")
        print(f"  {spec['name']:24s} rule={row.caf_required_punches:22s} "
              f"ot={row.caf_allow_ot} alt_sat={row.caf_alt_sat} "
              f"family={row.caf_shift_family}")

    print()
    for emp, who, _why, want_shift, _c in EMPLOYEES:
        cur = frappe.db.get_value("Employee", emp,
                                  ["default_shift", "holiday_list"], as_dict=True)
        rule = frappe.db.get_value("Shift Type", cur.default_shift,
                                   "caf_required_punches") if cur.default_shift else None
        want_rule = next(s["rule"] for s in NEW_SHIFTS if s["name"] == want_shift)
        ok = cur.default_shift == want_shift and rule == want_rule
        if not ok:
            bad.append(f"{emp} {who} is on {cur.default_shift!r} (rule {rule!r}), "
                       f"want {want_shift!r} (rule {want_rule!r})")
        shift_list = frappe.db.get_value("Shift Type", cur.default_shift, "holiday_list")
        if cur.holiday_list != shift_list:
            bad.append(f"FDR6: {emp} {who} holiday_list {cur.holiday_list!r} != "
                       f"shift's {shift_list!r}")
        print(f"  {'ok ' if ok else '🔴 '} {emp} {who[:30]:30s} "
              f"{cur.default_shift:24s} {rule}")

    # Nobody was left behind on a shift that now holds a mixed population.
    for spec in NEW_SHIFTS:
        n = frappe.db.count("Employee", {"status": "Active",
                                         "default_shift": spec["name"]})
        want = len(spec["people"])
        if n != want:
            bad.append(f"{spec['name']} holds {n} active employee(s), expected {want}")

    print("\n" + ("🔴 " + "; ".join(bad) if bad else
                  "✅ four shifts created parameter-identical to their sources, "
                  "eight employees moved, no single-punch shift allows OT"))
    return {"problems": bad}
