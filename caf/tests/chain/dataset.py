"""The base data every guard-ladder playbook walks. T-45.

    bench --site <site> execute caf.tests.chain.dataset.report   # dry run, WRITES NOTHING
    bench --site <site> execute caf.tests.chain.dataset.seed
    bench --site <site> execute caf.tests.chain.dataset.verify
    bench --site <site> execute caf.tests.chain.dataset.reset

🔴 WHY THE DATA IS CODE WHEN THE WALK IS A BROWSER
---------------------------------------------------
MG, 2026-09-12, proposing the playbook: *"before playwright, plan out, create
base data set (with --> no OT approval, OT approval not submitted, more than
approved…) for each rung then run playwright."* Exactly right — and building
those states **through the user interface** would be the slowest possible route
to them and would not be re-runnable after a crash. So: this module seeds, the
browser walks what it seeded.

⭐ **"Keep this testing data set and append more carefully designed data into this
set when the test_suite has more new tests in future"** — MG's instruction, and it
is the contract: **SEEDED ROWS ARE NEVER EDITED, ONLY ADDED TO.** A playbook
confirmed in September must still mean the same thing in January, and it cannot
if the ground under it moved. New climbs claim new dates and append to `PLAN`.

THE TWO SHAPES, AND WHY BOTH ARE NEEDED
---------------------------------------
    LADDER_DAY   ONE date carrying EVERY fault at once. The climb clears them one
                 at a time and records WHICH MESSAGE ARRIVES AT EACH STEP.
                 🔴 This is the one that answers the actual question — HR sees
                 exactly one refusal, and only a day with several faults can say
                 which one she sees.

    ISO_DAYS     one date per fault, each in isolation. These are for asserting
                 that a message carries its FACTS (the person, the date, the
                 hours, the blocking document) — the `test_ot_messages` shape.

THE RULES THIS OBEYS (../CLAUDE.md — they are not optional)
------------------------------------------------------------
- **June, not July.** ⚠️ `2026-06-17` is Awal Muharram and is excluded: stock
  refuses a leave application whose every day is a holiday, and that refusal
  arrives long before any CAF logic.
- 🔴 **Never 2026-08-10..16 or 2026-09-07..10** — the 616 and 352 draft windows.
  10–16 August is still T-44's only evidence.
- 🔴 **The cast is chosen by `attendance_device_id`, never `HR-EMP-xxxxx`**
  (T-32 — the same id is a different person on production).
- ⚠️ **A fixture employee must PRE-DATE its own fixture.** Stock refuses an
  Attendance dated before the joining date, and `test_chunk7_dashboard` lost a
  June fixture to exactly that (its first pick joined 2026-08-03).
- ⚠️ **Other suites take `LIMIT 1` of "active employee on an OT-allowing shift"**,
  so this one deliberately takes from the far end of that pool.
- **Self-cleaning, artifacts removed FIRST as well as last**, so a run after a
  crash still works.

🔴 THE ROSTER GATE IS A RUNG, NOT AN OBSTACLE
----------------------------------------------
Every other suite wraps itself in `roster_gate.suspended()`. This one must NOT:
the gate firing, being cleared by confirming the month, and then letting the log
through **is rung 7**. The live gate starts 2026-09-01 and this window is June, so
the playbook arms it with `roster_gate.armed_from(MONTH_START)` for the length of
the climb and restores it by MEANING afterwards. ⚠️ `seed()` deliberately does
**not** create the Monthly Roster Confirmation — its ABSENCE is the rung.
"""

import traceback

import frappe
from frappe.utils import strip_html


# ── the window ──────────────────────────────────────────────────────────────
MONTH = "2026-06"
MONTH_START = "2026-06-01"
MONTH_END = "2026-06-30"
HOLIDAY = "2026-06-17"          # Awal Muharram — never use it

# 🔴 EVERY DATE BELOW WAS MEASURED, NOT PICKED FROM A CALENDAR (2026-09-12).
# Two things disqualify a date and neither is visible by looking at it:
#
#   ⚠️ 2026-06-01 and 2026-06-02 resolve as **Holiday**, and 07/14/21/28 as
#      **Restday** — a ladder needs a scheduled day or nothing is expected of it.
#      The first draft of this file used 06-02 and `report()` caught it.
#
#   🔴 This employee ALREADY HAS submitted OT Approvals on 06-04, 06-05, 06-10,
#      06-22, 06-23, 06-24 and 06-25. Seeding an "OT with no approval" rung on
#      one of those would have been **silently satisfied by a real approval** —
#      the rung would pass while testing nothing, which is the failure mode this
#      whole package exists to stop. `report()` re-checks this every run.
LADDER_DAY = "2026-06-03"       # Wednesday. Carries every fault at once.

ISO_DAYS = {
    "ot_none":     "2026-06-08",   # overtime clocked, NO OT Approval at all
    "ot_draft":    "2026-06-09",   # an OT Approval exists but is a DRAFT
    "ot_over":     "2026-06-11",   # clocked MORE than a normal approval allows
    "held":        "2026-06-12",   # a missing punch — OD-58
    "leave_clash": "2026-06-15",   # approved leave already owns the day
    "clean":       "2026-06-16",   # nothing wrong: the control. It must SUBMIT
}

# The cast, by DEVICE ID (T-32 — `HR-EMP-xxxxx` is a per-site counter and is a
# different person on production). Measured 2026-09-12: of 70 active employees on
# an OT-allowing shift, exactly **4** are also clear of Finger Logs, Attendance
# and leave across all of June AND hold a 2026 MC allocation. This is one of them.
CAST = {
    "OLD": {
        "device": "982",
        "why": "joined 2022-11-18 — 43 months at the window, so the FLAT "
               "entitlement band, and comfortably before it (stock refuses an "
               "Attendance dated before the joining date). `8am Schedule` allows "
               "OT, so rungs 1-3 can fire at all. Holds a submitted 2026 MC "
               "allocation, without which the leave rung cannot be seeded. "
               "⭐ And the leave approver is `production1@caffood.com` — one of "
               "the supervisor test logins — so the climb can genuinely change "
               "hands between roles.",
    },
}

LEAVE_TYPE = "MC"

# Overtime, in FBR2's hour.minute notation — 2.30 is 2 h 30 m, NOT 2.3 h.
OT_CLOCKED = 2.30               # -> ot_in_hour 2.5 after gate + rounding
OT_APPROVED_LOW = 1.0           # deliberately less than the clocked figure


def _fail(msg):
    frappe.throw(f"[chain.dataset] {msg}")


# ── the cast ────────────────────────────────────────────────────────────────
def employee(role="OLD", required=True):
    """The Employee for a cast role, found by device id. Never a hard-coded id."""
    device = CAST[role]["device"]
    name = frappe.db.get_value("Employee", {"attendance_device_id": device,
                                            "status": "Active"}, "name")
    if not name and required:
        _fail(f"no ACTIVE employee carries attendance_device_id {device!r}, which "
              f"is how the {role} member of the cast is identified (T-32 — the "
              f"HR-EMP id is a per-site counter and means nothing here). Re-pick "
              f"the cast for this site and record the new device id in CAST.")
    return name


def _shift_of(emp):
    from caf.caf.shift_resolution import resolve_day_type
    return resolve_day_type(emp, LADDER_DAY)


# ── builders ────────────────────────────────────────────────────────────────
NO_PUNCH = "00:00:00"


def _log(emp, date, ot=0, missing_punch=False):
    """One DRAFT Finger Log. Never submitted here — climbing is the playbook's job.

    🔴 "NO PUNCH" IS `"00:00:00"`, NEVER `None`. MEASURED THE HARD WAY 2026-09-12.
    ------------------------------------------------------------------------------
    The first version set `resume = None` to express a missing lunch-IN. The row
    came back holding **`16:34:11.300874`** — the wall-clock time of the seed run.
    Frappe casts a `Time` field through `get_time()`, and **`get_time(None)`
    returns NOW**, so a deliberately absent punch silently became a punch at
    whatever o'clock the fixture was built.

    The damage was not only that `caf_not_full_day` stayed **0** and rung 4 could
    never fire — the day's arithmetic was corrupted too (resume 16:34 sitting
    between break 12:00 and out 20:00 gave `caf_work_hours` 3.93). A rung built on
    it would have asserted against nonsense.

    ⚠️ `"00:00:00"` is not a workaround, it is the CORRECT value: `has_punch()`
    treats the all-zero sentinel as absent precisely because *"the importer writes
    '00:00:00', never NULL — testing for NULL is the trap that cost this project a
    withdrawn decision (OD-49)."* The fixture now writes what Ingress writes.

    ⚠️ Which punch is dropped is read from the SHIFT's own rule, not assumed. On
    `In + Out + Lunch pair` the lunch-IN is the honest miss (T-8 — correcting one
    means filling the lunch PAIR); on `In and Out only` dropping lunch would flag
    nothing at all, so the OUT is dropped instead.
    """
    from caf.caf.shift_resolution import get_shift_params, resolve_day_type
    from caf.caf import work_hours

    punches = {"time_in": "08:00:00", "break": "12:00:00",
               "resume": "13:00:00", "out": "20:00:00"}

    if missing_punch:
        _day, shift = resolve_day_type(emp, date)
        required = work_hours.required_punches(get_shift_params(shift))
        drop = "resume" if "resume" in required else \
               ("out" if "out" in required else None)
        if not drop:
            _fail(f"shift {shift!r} on {date} requires {required or 'any one punch'}, "
                  f"so no single omission can make the day incomplete — rung 4 "
                  f"cannot be seeded against it. Pick a cast member on a shift "
                  f"with a stricter punch rule.")
        punches[drop] = NO_PUNCH

    d = frappe.new_doc("Finger Log")
    d.employee = emp
    d.work_date = date
    d.time_in = punches["time_in"]
    d.set("break", punches["break"])
    d.resume = punches["resume"]
    d.out = punches["out"]
    d.overtime = ot                      # FBR2 — hour.minute, not decimal hours
    d.flags.ignore_permissions = True
    d.insert(ignore_permissions=True)
    return d


def _approval(emp, date, hours, kind="normal", submit=True):
    """An OT Approval for exactly `hours` on `date`.

    ⚠️ Three traps, all previously paid for in `test_ot_messages`:
      1. the child table is **`emp_list`**, not `ot_table` — appending to a
         fieldname that does not exist dies as
         `AttributeError: 'NoneType' object has no attribute 'options'`;
      2. `ot_duration` is RECOMPUTED and a disagreeing value is refused —
         `(ot_end - start_work)/3600 - <the shift's work hours>` — so
         🔴 `start_work` is the start of the WORKING DAY, not of the overtime;
      3. `hours` must be a multiple of 0.5, because `convertTo_nearest` rounds
         to that and the check then compares against the rounded figure.
    """
    shift = frappe.db.get_value("Employee", emp, "default_shift")
    s = frappe.db.get_value("Shift Type", shift, ["start_time", "end_time"],
                            as_dict=True)

    def mins(v):
        return int(v.total_seconds() // 60) if hasattr(v, "total_seconds") \
            else int(str(v)[:2]) * 60 + int(str(v)[3:5])

    def hhmm(m):
        return f"{m // 60:02d}:{m % 60:02d}:00"

    a = frappe.new_doc("OT Approval")
    a.type = kind
    a.work_date = date
    a.ot_department = frappe.db.get_value("Employee", emp, "department")
    a.append("emp_list", {"emp_id": emp, "work_date": date,
                          "start_work": hhmm(mins(s.start_time)),
                          "ot_end": hhmm(mins(s.end_time) + int(round(hours * 60))),
                          "ot_duration": hours})
    a.flags.ignore_permissions = True
    a.insert(ignore_permissions=True)
    if submit:
        a.submit()
    return a


def _leave(emp, date):
    """One approved day of MC. Needs a Leave Allocation or it cannot be approved."""
    la = frappe.new_doc("Leave Application")
    la.employee = emp
    la.leave_type = LEAVE_TYPE
    la.from_date = la.to_date = date
    la.description = "chain.dataset — the day is already decided by leave (rung 5)"
    la.status = "Approved"
    if la.meta.has_field("leave_approver"):
        la.leave_approver = frappe.db.get_value("Employee", emp, "leave_approver")
    la.flags.ignore_permissions = True
    la.insert()
    la.submit()
    return la


# ── what this module OWNS, and nothing else ─────────────────────────────────
def _owned_dates():
    return [LADDER_DAY] + sorted(ISO_DAYS.values())


def _ot_approvals(emp, dates):
    """OT Approvals for THIS employee on THESE dates.

    🔴 CAUGHT BY `report()` BEFORE `seed()` EVER RAN, and it would have destroyed
    real data. The first version filtered on `work_date` alone — and an OT
    Approval is a HEADER with a child row per employee, so that claimed every
    approval anybody held on those dates. `reset()` would have cancelled and
    deleted 30-odd other people's submitted approvals.

    ⚠️ The scope that is correct is the CHILD row's `emp_id`. And note the
    header's own `work_date` is deliberately what is matched: 77 submitted child
    rows carry a date differing from their header (genuine multi-date approvals),
    so matching the child date instead would sweep in documents this module never
    made.
    """
    if not dates:
        return []
    return frappe.db.sql("""
        SELECT DISTINCT p.name, p.work_date, p.docstatus, p.type
          FROM `tabOT Approval` p
          JOIN `tabOT Approval Table` c ON c.parent = p.name
         WHERE c.emp_id = %(e)s AND p.work_date IN %(d)s
         ORDER BY p.work_date""", {"e": emp, "d": tuple(dates)}, as_dict=True)


def owned():
    """Every row this dataset claims. `reset()` removes exactly this and no more."""
    emp = employee("OLD", required=False)
    if not emp:
        return {}
    dates = _owned_dates()
    return {
        "Finger Log": frappe.get_all(
            "Finger Log", filters={"employee": emp, "work_date": ("in", dates)},
            fields=["name", "work_date", "docstatus"], order_by="work_date"),
        "OT Approval": _ot_approvals(emp, dates),
        "Leave Application": frappe.get_all(
            "Leave Application",
            filters={"employee": emp, "from_date": ("in", dates)},
            fields=["name", "from_date", "docstatus", "status"]),
        "Attendance": frappe.get_all(
            "Attendance",
            filters={"employee": emp, "attendance_date": ("in", dates),
                     "docstatus": ("<", 2)},
            fields=["name", "attendance_date", "status", "leave_type",
                    "caf_finger_log"]),
    }


# ── report · seed · reset · verify ──────────────────────────────────────────
def report():
    """🔴 WRITES NOTHING. What seeding would do, and whether it can."""
    try:
        emp = employee("OLD", required=False)
        print("=" * 74)
        print(f"chain.dataset — REPORT (writes nothing) · window {MONTH}")
        print("=" * 74)

        if not emp:
            print(f"🔴 BLOCKED — no active employee with device "
                  f"{CAST['OLD']['device']}. See CAST.")
            return None

        row = frappe.db.get_value(
            "Employee", emp,
            ["employee_name", "date_of_joining", "default_shift", "department",
             "reports_to", "leave_approver"], as_dict=True)
        print(f"  cast OLD : {emp}  {row.employee_name}")
        print(f"             device {CAST['OLD']['device']} · joined "
              f"{row.date_of_joining} · shift {row.default_shift}")
        print(f"             supervisor {row.reports_to} · leave approver "
              f"{row.leave_approver}")
        print(f"             {CAST['OLD']['why']}")

        blockers = []
        if str(row.date_of_joining) >= MONTH_START:
            blockers.append(
                f"joined {row.date_of_joining}, which is NOT before the window — "
                f"stock refuses an Attendance dated before the joining date")
        allows_ot = frappe.db.get_value("Shift Type", row.default_shift,
                                        "caf_allow_ot")
        if not allows_ot:
            blockers.append(
                f"shift {row.default_shift!r} has caf_allow_ot = 0, so ot_in_hour "
                f"is always 0 and rungs 1-3 cannot fire at all (FBR36/FDR7)")
        if not frappe.db.exists("Leave Allocation",
                                {"employee": emp, "leave_type": LEAVE_TYPE,
                                 "docstatus": 1}):
            blockers.append(
                f"no submitted {LEAVE_TYPE} Leave Allocation — the leave-clash rung "
                f"cannot be seeded, because an application with no allocation is "
                f"refused for balance long before CAF's guard is reached")

        # ── every date, not just the ladder day ────────────────────────────
        from caf.caf.shift_resolution import resolve_day_type
        print(f"\n  {'date':<12}{'day type':<11}{'pre-existing on it':<22}rung")
        labels = {LADDER_DAY: "LADDER DAY (all faults)"}
        labels.update({v: k for k, v in ISO_DAYS.items()})
        for date in _owned_dates():
            day_type, _shift = resolve_day_type(emp, date)
            prior = []
            if _ot_approvals(emp, [date]):
                prior.append("OT Approval")
            if frappe.db.exists("Leave Application",
                                {"employee": emp, "from_date": ("<=", date),
                                 "to_date": (">=", date), "docstatus": 1}):
                prior.append("approved leave")
            if frappe.db.exists("Attendance",
                                {"employee": emp, "attendance_date": date,
                                 "docstatus": ("<", 2)}):
                prior.append("Attendance")
            print(f"  {date:<12}{day_type:<11}{', '.join(prior) or '-':<22}"
                  f"{labels.get(date, '')}")

            if date == HOLIDAY:
                blockers.append(f"{date} is Awal Muharram — excluded by the "
                                f"suite convention")
            if day_type != "Workday":
                blockers.append(
                    f"{date} resolves as {day_type}, not Workday — nothing is "
                    f"expected of an unscheduled day, so the rung on it would "
                    f"assert nothing")
            # 🔴 the one that would pass while testing nothing
            if "OT Approval" in prior and date in (LADDER_DAY, ISO_DAYS["ot_none"]):
                blockers.append(
                    f"{date} already has a submitted OT Approval for {emp} — the "
                    f"'overtime has no approval' rung would be SILENTLY SATISFIED "
                    f"by it and pass while testing nothing. Move the rung to a "
                    f"date with none")

        existing = owned()
        n = sum(len(v) for v in existing.values())
        print(f"\n  rows this dataset already owns (reset() would remove these): {n}")
        for dt, rows in existing.items():
            for r in rows:
                print(f"     {dt:<18} {r.name}  docstatus {r.docstatus}")

        print(f"\n  it WOULD create, for {emp}:")
        print(f"     {LADDER_DAY}  LADDER DAY — every fault at once:")
        print(f"                    missing lunch-IN (held) + {OT_CLOCKED} clocked "
              f"OT with NO approval + approved {LEAVE_TYPE}, with June's roster "
              f"unconfirmed")
        for k, d in sorted(ISO_DAYS.items(), key=lambda kv: kv[1]):
            print(f"     {d}  {k}")
        print(f"\n  ⚠️ it deliberately creates NO Monthly Roster Confirmation for "
              f"{MONTH} — its ABSENCE is rung 7.")

        if blockers:
            print("\n🔴 BLOCKED:")
            for b in blockers:
                print(f"   - {b}")
        else:
            print("\n✅ clear to seed.")
        print("=" * 74)
    except Exception:
        print(traceback.format_exc())
    return None


def reset():
    """Remove exactly what this dataset owns. Safe to run first, and it is."""
    try:
        emp = employee("OLD", required=False)
        if not emp:
            print("nothing to reset — the cast does not resolve on this site")
            return None

        removed = []
        # Order matters: Attendance is linked FROM Finger Log, and leave owns
        # its own Attendance. Cancel downward, delete upward.
        for r in frappe.get_all("Leave Application",
                                filters={"employee": emp,
                                         "from_date": ("in", _owned_dates())},
                                fields=["name", "docstatus"]):
            doc = frappe.get_doc("Leave Application", r.name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.cancel()
            frappe.delete_doc("Leave Application", r.name, force=True,
                              ignore_permissions=True)
            removed.append(f"Leave Application {r.name}")

        for r in frappe.get_all("Attendance",
                                filters={"employee": emp,
                                         "attendance_date": ("in", _owned_dates())},
                                fields=["name", "docstatus"]):
            doc = frappe.get_doc("Attendance", r.name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                # the machine cancel, exactly as cancel_attendance does (D-12)
                doc.flags.caf_skip_leave_guard = True
                doc.cancel()
            frappe.delete_doc("Attendance", r.name, force=True,
                              ignore_permissions=True)
            removed.append(f"Attendance {r.name}")

        targets = [("Finger Log", r.name) for r in frappe.get_all(
            "Finger Log", filters={"employee": emp,
                                   "work_date": ("in", _owned_dates())},
            fields=["name"])]
        # 🔴 scoped to this employee's CHILD rows — see `_ot_approvals`
        targets += [("OT Approval", r.name)
                    for r in _ot_approvals(emp, _owned_dates())]

        for dt, name in targets:
            doc = frappe.get_doc(dt, name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.flags.ignore_links = True
                doc.cancel()
            frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
            removed.append(f"{dt} {name}")

        # rung 7's artefact, if a playbook confirmed the month
        for r in frappe.get_all("Monthly Roster Confirmation",
                                filters={"name": ("like", f"%{MONTH}%")},
                                fields=["name", "docstatus"]):
            doc = frappe.get_doc("Monthly Roster Confirmation", r.name)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.cancel()
            frappe.delete_doc("Monthly Roster Confirmation", r.name, force=True,
                              ignore_permissions=True)
            removed.append(f"Monthly Roster Confirmation {r.name}")

        frappe.db.commit()
        print(f"removed {len(removed)} row(s)")
        for r in removed:
            print(f"   {r}")
    except Exception:
        print(traceback.format_exc())
    return None


def seed():
    """Build the base data. Idempotent: it resets what it owns first."""
    try:
        emp = employee("OLD")
        reset()

        made = []

        # ── the LADDER DAY — every fault at once ───────────────────────────
        # 🔴 The order the faults are CREATED in does not matter; the order the
        # guards FIRE in is the question, and that is the playbook's to answer.
        if frappe.db.exists("Leave Allocation", {"employee": emp,
                                                 "leave_type": LEAVE_TYPE,
                                                 "docstatus": 1}):
            la = _leave(emp, LADDER_DAY)
            made.append(f"Leave Application {la.name} ({LEAVE_TYPE} on {LADDER_DAY})")
        else:
            print(f"⚠️ SKIPPED the leave on the ladder day — {emp} holds no "
                  f"submitted {LEAVE_TYPE} allocation, so an application would be "
                  f"refused for balance, not by CAF's guard. Rung 5 will be a SKIP.")

        log = _log(emp, LADDER_DAY, ot=OT_CLOCKED, missing_punch=True)
        made.append(f"Finger Log {log.name} — held + {OT_CLOCKED} OT unapproved")

        # ── the isolation days ─────────────────────────────────────────────
        l1 = _log(emp, ISO_DAYS["ot_none"], ot=OT_CLOCKED)
        made.append(f"Finger Log {l1.name} — OT, no approval")

        l2 = _log(emp, ISO_DAYS["ot_draft"], ot=OT_CLOCKED)
        a2 = _approval(emp, ISO_DAYS["ot_draft"], 3.0, submit=False)
        made.append(f"Finger Log {l2.name} + DRAFT OT Approval {a2.name}")

        l3 = _log(emp, ISO_DAYS["ot_over"], ot=OT_CLOCKED)
        a3 = _approval(emp, ISO_DAYS["ot_over"], OT_APPROVED_LOW)
        made.append(f"Finger Log {l3.name} + OT Approval {a3.name} for only "
                    f"{OT_APPROVED_LOW} h")

        l4 = _log(emp, ISO_DAYS["held"], missing_punch=True)
        made.append(f"Finger Log {l4.name} — missing lunch-IN, no OT")

        if frappe.db.exists("Leave Allocation", {"employee": emp,
                                                 "leave_type": LEAVE_TYPE,
                                                 "docstatus": 1}):
            la2 = _leave(emp, ISO_DAYS["leave_clash"])
            l5 = _log(emp, ISO_DAYS["leave_clash"])
            made.append(f"Leave Application {la2.name} + Finger Log {l5.name}")

        l6 = _log(emp, ISO_DAYS["clean"])
        made.append(f"Finger Log {l6.name} — the CONTROL: nothing wrong with it")

        frappe.db.commit()
        print("=" * 74)
        print(f"chain.dataset — SEEDED for {emp} in {MONTH}")
        print("=" * 74)
        for m in made:
            print(f"   {m}")
        print(f"\n   ⚠️ NO Monthly Roster Confirmation for {MONTH} — its absence "
              f"is rung 7.")
        print(f"   ⚠️ The gate is not armed here either. The playbook wraps its "
              f"climb in caf.tests.roster_gate.armed_from({MONTH_START!r}).")
        print("=" * 74)
    except Exception:
        print(traceback.format_exc())
    return None


def arm_gate():
    """Arm the roster gate onto THIS window, for the length of a browser climb.

    🔴 `roster_gate.armed_from()` is a context manager, and a browser playbook
    cannot hold a Python context across its steps — the climb happens in another
    process entirely. So the two halves are exposed separately here, and the
    playbook is responsible for calling `disarm_gate` with what this printed.

    ⚠️ IT PRINTS THE PREVIOUS VALUE. Write it into the playbook before going on:
    it is the only record of what must be restored, and a gate left armed at June
    would refuse every Finger Log dated after it.
    """
    from caf.caf.doctype.monthly_roster_confirmation \
        import monthly_roster_confirmation as mrc
    from caf.tests import roster_gate

    before = mrc.gate_from()
    roster_gate._set(MONTH_START)
    print(f"gate ARMED at {MONTH_START}")
    print(f"🔴 PREVIOUS VALUE WAS {before} — restore it with:")
    print(f"   bench ... execute caf.tests.chain.dataset.disarm_gate "
          f'--kwargs "{{\'previous\': \'{before}\'}}"')
    return None


def disarm_gate(previous=None):
    """Put the gate back to the MEANING it had. Assert it, do not assume it."""
    from caf.caf.doctype.monthly_roster_confirmation \
        import monthly_roster_confirmation as mrc
    from caf.tests import roster_gate

    roster_gate._set(previous or "")
    now = mrc.gate_from()
    ok, detail = roster_gate.restored(
        frappe.utils.getdate(previous) if previous else None)
    print(f"gate is now {now}")
    print(("✅ " if ok else "🔴 ") + detail)
    return None


def verify():
    """Is the seeded data in the state a playbook expects? Prints, never fixes."""
    try:
        emp = employee("OLD", required=False)
        if not emp:
            print("🔴 the cast does not resolve on this site — see CAST")
            return None

        expect = {
            LADDER_DAY: "held + unapproved OT + approved leave",
            ISO_DAYS["ot_none"]: "OT, no approval",
            ISO_DAYS["ot_draft"]: "OT, DRAFT approval",
            ISO_DAYS["ot_over"]: f"OT above a {OT_APPROVED_LOW} h approval",
            ISO_DAYS["held"]: "missing lunch-IN",
            ISO_DAYS["leave_clash"]: "approved leave owns the day",
            ISO_DAYS["clean"]: "nothing wrong — must SUBMIT",
        }

        print("=" * 74)
        print(f"chain.dataset — VERIFY · {emp} · {MONTH}")
        print("=" * 74)
        print(f"  {'date':<12}{'docstatus':<11}{'held':<6}{'ot_in_hour':<12}"
              f"{'leave':<8}what it is for")
        ok = True
        for date, why in sorted(expect.items()):
            fl = frappe.db.get_value(
                "Finger Log", {"employee": emp, "work_date": date},
                ["name", "docstatus", "caf_not_full_day", "ot_in_hour"],
                as_dict=True)
            lv = frappe.db.exists("Leave Application",
                                  {"employee": emp, "from_date": date,
                                   "docstatus": 1})
            if not fl:
                ok = False
                print(f"  {date:<12}🔴 MISSING — run seed()")
                continue
            print(f"  {date:<12}{fl.docstatus:<11}{fl.caf_not_full_day:<6}"
                  f"{fl.ot_in_hour or 0:<12}{'yes' if lv else '-':<8}{why}")

        roster = frappe.db.exists("Monthly Roster Confirmation",
                                  {"name": ("like", f"%{MONTH}%"), "docstatus": 1})
        print(f"\n  {MONTH} roster confirmed : {'YES — rung 7 will NOT fire' if roster else 'no  ✅ rung 7 is live'}")
        from caf.caf.doctype.monthly_roster_confirmation \
            import monthly_roster_confirmation as mrc
        print(f"  gate currently starts  : {mrc.gate_from()}  "
              f"(the playbook arms it at {MONTH_START} for the climb)")
        print("=" * 74)
        print("✅ consistent" if ok else "🔴 incomplete — run seed()")
    except Exception:
        print(traceback.format_exc())
    return None
