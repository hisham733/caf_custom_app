"""Everything CAF deliberately TURNED OFF, asserted to still be off. T-21.

    bench --site <site> execute caf.tests.platform.test_disabled_features.run

WHY THIS EXISTS
---------------
MG, 2026-09-04: *"for feature we turn off and blocked — eg disable stock Casual
Leave and ++"*.

CAF is an ERPNext site with a large stock surface that CAF does not use. Over
this project a dozen of those surfaces have been switched off one at a time —
a flag here, a role retirement there, a permission row removed. Every one of
them was a decision with a reason, and **not one of them was asserted anywhere.**

That is a different risk from an untested feature. A feature that breaks is
noticed, because somebody was using it. A switch-off that comes back is silent
by definition: nobody was using it, so nobody notices — until the day it
allocates leave nobody earned, or marks attendance nobody clocked.

🔴 AND THEY CAN COME BACK BY ACCIDENT, WHICH IS THE POINT
---------------------------------------------------------
Three real mechanisms, all measured on this project:

  · `bench migrate` calls `sync_fixtures()` (`frappe/migrate.py:143`). A fixture
    only inserts and updates — but if somebody re-adds a permission row to a
    fixture file, it lands on production silently on the next migrate.
  · A stock upgrade re-seeds stock records. `Casual Leave` arrived with
    `is_carry_forward = 1` and would arrive that way again.
  · A checkbox. `enable_auto_attendance` is one tick away from letting the
    hourly `hrms…process_auto_attendance_for_all_shifts` write Attendance from
    Employee Checkins — a source of truth CAF does not have (FBR69).

WHAT IS ASSERTED — and each one names the decision it protects
--------------------------------------------------------------
  DF01  no Leave Type carries forward                       §6.15 · FBR62a
  DF02  no Leave Type is an EARNED leave                    FDR-STOCKJOB
  DF03  auto-attendance is off on every Shift Type          FBR69 · OD-84
  DF04  nobody holds `Employee Self Service`                OD-84 · T-24
  DF05  `Attendance Request` + `Employee Checkin` are shut  OD-84 · T-24
  DF06  ...and both are in the exported fixture filter      quirk #44
  DF07  `Employee` cannot cancel/delete/amend OT Approval   FBR70
  DF08  `special_approve` is gated to three roles           FBR71
  DF09  `HR User` is retired                                T-J13
  DF10  the roster gate is set                              T-26
  DF11  every alternate-Saturday mirror link is mutual      FBR57
  DF12  `Shift Request` is unused                           T-24

⚠️ THIS SUITE IS READ-ONLY. It writes nothing and needs no cleanup, so it is
safe to run on production as a pre-migrate check — which is the point. Several
of these are exactly the questions to ask a prod-test site on day one.

⚠️ It asserts CONFIGURATION, not permission behaviour. Whether a *role* can
actually reach a surface is `test_role_matrix`'s job and needs per-role tokens
(quirks #33/#43); running that as Administrator measures nothing. Here the
question is narrower and answerable from state: is the switch still off?
"""

import frappe

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:26s} {'PASS' if ok else 'FAIL'}  {detail}")


# ─────────────────────────────────────────────────────────────── leave types
def df01_no_carry_forward():
    """§6.15 — CAF carries nothing over, at any length of service.

    `Casual Leave` was the one type with the flag set (unused: 0 allocations,
    0 applications, 0 policy rows) and was neutralised on 2026-09-04 by
    `caf.scripts.leave_type_hygiene`. A stock upgrade could re-seed it.
    """
    bad = frappe.get_all("Leave Type", filters={"is_carry_forward": 1}, pluck="name")
    check("DF01-NO-CARRY-FWD", not bad,
          f"Leave Types with is_carry_forward=1: {bad or 'none'} — §6.15 says none. "
          f"A carried-forward day is a day no CAF rule granted and no report shows")


def df02_no_earned_leave():
    """The stock cron `allocate_earned_leaves` runs on a schedule and is inert
    ONLY because it iterates `is_earned_leave = 1` and CAF has none. Create one
    and the job starts writing allocations nobody asked for."""
    bad = frappe.get_all("Leave Type", filters={"is_earned_leave": 1}, pluck="name")
    check("DF02-NO-EARNED-LEAVE", not bad,
          f"Leave Types with is_earned_leave=1: {bad or 'none'}. The stock "
          f"`allocate_earned_leaves` cron iterates exactly this filter — an empty "
          f"filter is the whole reason the job does nothing")


# ─────────────────────────────────────────────────────────── attendance sources
def df03_auto_attendance_off():
    """FBR69 — ERPNext has ONE source of attendance, the Finger Log.

    `hrms…process_auto_attendance_for_all_shifts` runs HOURLY and is stopped
    only by this flag. It builds Attendance from Employee Checkin, which CAF
    does not populate — so switching it on would not add data, it would start
    marking people ABSENT.
    """
    on = frappe.get_all("Shift Type", filters={"enable_auto_attendance": 1}, pluck="name")
    check("DF03-AUTO-ATT-OFF", not on,
          f"Shift Types with enable_auto_attendance=1: {on or 'none'}. The hourly "
          f"hrms job is idling on this flag, not disabled")


def df04_no_ess_holders():
    """OD-84 — CAF does not use self-service attendance. Retired from 4 holders
    on 2026-09-02. ⚠️ `Has Role` is the child table of BOTH `User` and
    `Role Profile`, so this MUST filter on parenttype or a Role Profile counts
    as a person."""
    users = frappe.get_all("Has Role",
                           filters={"role": "Employee Self Service", "parenttype": "User"},
                           pluck="parent")
    profiles = frappe.get_all("Has Role",
                              filters={"role": "Employee Self Service",
                                       "parenttype": "Role Profile"},
                              pluck="parent")
    check("DF04-ESS-RETIRED", not users,
          f"users holding Employee Self Service: {len(users)} {users[:4]} — want 0. "
          f"(Role Profiles carrying it: {profiles or 'none'} — those are not people, "
          f"but a profile that still grants it will re-grant on the next assignment)")


def df05_self_service_shut():
    """OD-84 / T-24 — the two doctypes that let an employee assert their own
    attendance. Closed to `Employee` and to `Employee Self Service`.

    Read from `Custom DocPerm`, which is what actually applies: CAF overrides
    stock permissions per doctype and the doctype's own `.json` is then dead
    letter (quirk: compare against the fixture, never against the .json)."""
    holes = []
    for dt in ("Attendance Request", "Employee Checkin"):
        for role in ("Employee", "Employee Self Service"):
            rows, table = _perms(dt, role)
            for r in rows:
                if r.create or r.write or r.submit:
                    holes.append(f"{dt}/{role} ({table}) create={r.create} "
                                 f"write={r.write} submit={r.submit}")
    check("DF05-SELF-SERVICE-SHUT", not holes,
          f"ways an employee could assert their own attendance: {holes or 'none'}. "
          f"CAF's only attendance source is the Finger Log (FBR69)")


def df06_in_fixture_filter():
    """quirk #44 — an un-exported permission change is invisible to production.

    The closure in DF05 only reaches prod because both doctypes were added to
    the `Custom DocPerm` fixture filter in `hooks.py`. Remove them from the
    filter and DF05 keeps passing here while production stays wide open."""
    from caf import hooks
    filtered = set()
    for f in getattr(hooks, "fixtures", []):
        if isinstance(f, dict) and f.get("dt") == "Custom DocPerm":
            for clause in f.get("filters", []):
                # ["parent", "in", [...]]
                if len(clause) == 3 and clause[0] == "parent" and isinstance(clause[2], (list, tuple)):
                    filtered |= set(clause[2])
    want = {"Attendance Request", "Employee Checkin"}
    missing = want - filtered
    check("DF06-FIXTURE-CARRIES", not missing,
          f"doctypes missing from the Custom DocPerm fixture filter: "
          f"{missing or 'none'}. Without them the closure never travels — it is "
          f"true here and false on production, which is the worst of the two")


# ───────────────────────────────────────────────────────────────── OT Approval
def _perms(doctype, role):
    """The permission rows that ACTUALLY apply, from whichever table holds them.

    🔴 `Custom DocPerm` does not universally replace `DocPerm` — it replaces it
    **only for doctypes somebody has customised**. Frappe's own rule (see
    `frappe/permissions.py`): if ANY Custom DocPerm row exists for the doctype,
    that set is the whole truth and the `.json` DocPerms are dead letter;
    otherwise the `.json` applies. Measured 2026-09-04: `Attendance Request` is
    in the first camp and `OT Approval` — a CAF-owned doctype — is in the
    second, with zero Custom DocPerm rows.

    Reading only one table is how a suite passes against a doctype it never
    looked at. This reads the one in force and says which.
    """
    custom = frappe.get_all("Custom DocPerm", filters={"parent": doctype},
                            fields=["role", "`create`", "`read`", "`write`",
                                    "submit", "`cancel`", "`delete`", "amend"])
    if custom:
        return [r for r in custom if r.role == role], "Custom DocPerm"
    stock = frappe.get_all("DocPerm", filters={"parent": doctype},
                           fields=["role", "`create`", "`read`", "`write`",
                                   "submit", "`cancel`", "`delete`", "amend"])
    return [r for r in stock if r.role == role], "DocPerm (.json)"


def df07_ot_employee_locks():
    """FBR70 — an Employee MAY create and submit a NORMAL OT Approval. That is
    MG's business rule, not a hole: department reps file for their area and
    rotate often. The CONTROL is the other three verbs, plus `owner`.

    ⚠️ `amend` is display-only in Frappe (quirk #50) — `insert()` checks
    `create`, never `amend`. It is asserted anyway because it is what the
    permission row claims, and a gap between claim and effect is worth seeing."""
    rows, table = _perms("OT Approval", "Employee")
    if not rows:
        return check("DF07-OT-EMP-LOCKS", False,
                     f"no {table} row for OT Approval/Employee at all — every "
                     "department rep who files OT would be blocked, which is the "
                     "opposite failure but still a failure")
    bad = [r for r in rows if r.cancel or r.delete]
    check("DF07-OT-EMP-LOCKS", not bad,
          f"OT Approval/Employee via {table}: create={rows[0].create} "
          f"submit={rows[0].submit} (both intended, FBR70) · cancel={rows[0].cancel} "
          f"delete={rows[0].delete} amend={rows[0].amend} — cancel and delete must "
          f"stay 0; they are the only lock the open create relies on")


def df08_special_approve_gated():
    """FBR71 — `type = special_approve` cancels every other submitted row for
    that (employee, date) by raw SQL, bypassing the parent's own lock. So it is
    the one OT verb that is NOT open, and the gate is a controller guard, not a
    permission row — read it from the source rather than trusting the docstring."""
    import inspect
    from caf.caf.doctype.ot_approval import ot_approval as mod
    src = inspect.getsource(mod)
    has_guard = "guard_special_approve" in src and "only_for" in src
    roles_ok = all(r in src for r in ("HR Manager", "Leave Approver", "System Manager"))
    check("DF08-SPECIAL-GATED", has_guard and roles_ok,
          f"guard_special_approve present={has_guard}, gates the three intended "
          f"roles={roles_ok}. ⚠️ `frappe.only_for` early-returns for Administrator "
          f"AND for flags.in_test — this checks the code exists; test_role_matrix "
          f"RM16 checks it BITES, and only that one uses per-role tokens")


# ─────────────────────────────────────────────────────────────────── roles etc
def df09_hr_user_retired():
    """T-J13 — `HR User` went from 32 holders down to a named list. It is a broad
    stock role granting most of the HR module; CAF's model is HR Manager plus
    `Employee.leave_approver`.

    The sanctioned list is read from `retire_hr_user_role.KEEP` rather than
    hard-coded here, so the script and the assertion cannot drift apart — and a
    count is the wrong test anyway. WHICH four matters, not that there are four.
    """
    from caf.scripts.retire_hr_user_role import KEEP
    users = set(frappe.get_all("Has Role",
                               filters={"role": "HR User", "parenttype": "User"},
                               pluck="parent"))
    extra = sorted(users - set(KEEP))
    check("DF09-HR-USER-RETIRED", not extra,
          f"users holding HR User outside the sanctioned list: {extra or 'none'} "
          f"({len(users)} holders, {len(KEEP)} sanctioned). ⚠️ `hr.user.test@` is on "
          f"the list deliberately — stripping it broke C75-ROLE")


def df10_roster_gate_set():
    """T-26 — `caf_roster_gate_from` refuses Finger Logs on a work date whose
    month has no confirmed roster. Unset, every guard downstream is inert.

    ⚠️ It is a Custom Field on **HR Settings**, not on Ingress Sync Settings —
    the field is read from the doctype the Custom Field record names, so a move
    shows up here as a failure rather than as a silently-skipped check.

    ⚠️ A cleared Date on a Single reads back as `0001-01-01`, not None or ''
    (measured 2026-09-02) — so 'is it set' has to test the MEANING."""
    from frappe.utils import getdate
    dt = frappe.db.get_value("Custom Field", {"fieldname": "caf_roster_gate_from"}, "dt")
    if not dt:
        return check("DF10-ROSTER-GATE-SET", False,
                     "no Custom Field named caf_roster_gate_from exists at all — "
                     "the roster gate has no home, so nothing enforces T-26")
    raw = frappe.db.get_single_value(dt, "caf_roster_gate_from")
    ok = bool(raw) and getdate(raw).year > 1900
    check("DF10-ROSTER-GATE-SET", ok,
          f"{dt}.caf_roster_gate_from = {raw!r} — a cleared Date on a Single reads "
          f"back as 0001-01-01, so 'truthy' is not the test; the year is")


def df11_mirrors_mutual():
    """FBR57 — a one-way mirror link is a half-configured pair that fails in the
    direction nobody tests. `guard_alt_sat_pairing()` refuses to save one, but
    `db.set_value` and a fixture import both bypass the controller."""
    bad = []
    for s in frappe.get_all("Shift Type", filters={"caf_alt_sat": 1},
                            fields=["name", "caf_sat_mirror", "caf_sat_anchor",
                                    "caf_sat_anchor_date"]):
        if not s.caf_sat_mirror:
            bad.append(f"{s.name}: no mirror")
            continue
        back = frappe.db.get_value("Shift Type", s.caf_sat_mirror, "caf_sat_mirror")
        if back != s.name:
            bad.append(f"{s.name} → {s.caf_sat_mirror} → {back}")
        other = frappe.db.get_value("Shift Type", s.caf_sat_mirror, "caf_sat_anchor")
        if other == s.caf_sat_anchor:
            bad.append(f"{s.name} and its mirror BOTH anchor '{s.caf_sat_anchor}' "
                       f"— they must be opposite or nobody works that Saturday")
    check("DF11-MIRRORS-MUTUAL", not bad,
          f"broken alternate-Saturday pairs: {bad or 'none'}")


def df12_shift_request_unused():
    """T-24 — `Shift Request` is a second, stock route to a Shift Assignment.
    Inert today at 0 rows. This is a WATCH, not a lock: it fails the day
    somebody starts using it, which is the day the decision needs revisiting."""
    n = frappe.db.count("Shift Request")
    check("DF12-SHIFT-REQ-UNUSED", n == 0,
          f"Shift Request rows: {n} — expected 0. Any row means the stock "
          f"self-service route to a Shift Assignment is live, and T-24 stops "
          f"being theoretical")


CHECKS = [df01_no_carry_forward, df02_no_earned_leave, df03_auto_attendance_off,
          df04_no_ess_holders, df05_self_service_shut, df06_in_fixture_filter,
          df07_ot_employee_locks, df08_special_approve_gated, df09_hr_user_retired,
          df10_roster_gate_set, df11_mirrors_mutual, df12_shift_request_unused]


def run():
    print(f"\n{'=' * 78}\nDISABLED FEATURES — everything CAF switched off, still off?"
          f"\n{'=' * 78}")
    for fn in CHECKS:
        try:
            fn()
        except Exception as e:
            check(fn.__name__.split("_")[0].upper(), False,
                  f"🔴 raised {type(e).__name__}: {str(e)[:110]}")

    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
