"""Every HR surface × every role, in BOTH directions. T-21.

    bench --site <site> execute caf.tests.platform.test_role_matrix.run

WHY THIS EXISTS
---------------
MG's last full permission pass was done by hand and took **three days**. Between
that pass and now the framework grew an HR-Manager-only report over OT figures, a
Finger Log → Attendance panel, four punch-rule shifts and a manifest search —
none of it role-tested. A permission hole is the one class of bug that stays
invisible until the wrong person finds it, and T-18 (the prod-test parallel run)
is the first time real people meet these surfaces.

**It earned its keep on the first run**: RM16 found that any ordinary employee
can create *and submit* an OT Approval naming themselves. Measured end to end,
not inferred from a permission row.

WHAT "BOTH DIRECTIONS" MEANS, AND WHY IT IS THE WHOLE POINT
----------------------------------------------------------
A suite that only checks *"HR Manager can"* passes against a system where
**everyone** can. So every row asserts two things:

    ALLOW   the privileged role gets through the gate
    DENY    every other role is refused with frappe.PermissionError

🔴 Running as `Administrator` proves nothing (quirks #33/#43), and
`frappe.only_for` **returns early for Administrator** — an Administrator-run
suite reports a clean matrix against a completely open system. Every probe here
runs under `frappe.set_user`.

🔴 A Script Report must go through `frappe.desk.query_report.run`, not
`execute()` (quirks #58). `execute()` skips the `ref_doctype` report-permission
gate, so a suite can pass while the desk lets a supervisor read OT.

🔴 **`frappe.get_doc()` RUNS NO PERMISSION CHECK.** The first draft of this suite
used it to probe `Ingress Sync Settings` and duly reported that every employee
could read the Ingress database password. They cannot — `has_permission`,
`frappe.client.get`, `get_value` and `doc.check_permission()` all refuse. A probe
that uses the wrong door measures the door, not the lock. Every probe here uses
the surface the desk actually uses.

SAFETY
------
A suite must not change the site (tests/CLAUDE.md). Read-only surfaces are called
for real in both directions. **Mutating** surfaces get the DENY direction for
real — `only_for` throws before any work — plus an ALLOW probe whose arguments
fail *after* the gate (a batch name that does not exist), so "not a
PermissionError" is the assertion. RM16 is the one exception: it must create a
real document to prove the hole, so it builds one and removes it in `finally`.

The one thing this suite cannot see is a hole reachable only by URL. That is what
`tests/appraisal/` (PowerShell, per-role API tokens) is for.
"""

import json

import frappe
from frappe.utils import add_days, getdate

RESULTS = []

METHOD = "method"          # a whitelisted function; call it
REPORT = "report"          # a Script Report; go through query_report.run
DOCTYPE = "doctype"        # a doctype-level permission
READDOC = "readdoc"        # can this user READ this document, the way the desk asks


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:32s} {'PASS' if ok else 'FAIL'}  {detail}")


# ── who plays each role ────────────────────────────────────────────────────
def _pick_user(must_have, must_not_have=()):
    """Resolve a role to a real enabled user on THIS site.

    Deliberately not hardcoded to the test logins: this suite has to run on the
    prod-test server (T-18), where the names differ — and the point of running it
    there is precisely that the roles are not the ones we assumed.
    """
    rows = frappe.db.sql(
        """SELECT DISTINCT hr.parent FROM `tabHas Role` hr
           JOIN `tabUser` u ON u.name = hr.parent
           WHERE hr.role = %s AND u.enabled = 1
             AND u.name NOT IN ('Administrator','Guest')
           ORDER BY hr.parent""",
        (must_have,),
    )
    for (user,) in rows:
        if set(frappe.get_roles(user)).isdisjoint(must_not_have):
            return user
    return None


def _roster():
    return {
        "HR Manager": _pick_user("HR Manager"),
        # The dangerous middle: trusted with a desk, not entitled to OT figures
        # for anyone but their own reports.
        "Supervisor": _pick_user("Leave Approver",
                                 must_not_have={"HR Manager", "HR User", "System Manager"}),
        "Employee": _pick_user("Employee",
                               must_not_have={"HR Manager", "HR User",
                                              "System Manager", "Leave Approver"}),
    }


def _probe(kind, target, user, args=None):
    """Run one surface as one user. 'ALLOWED' | 'DENIED' | 'ERR:<Type>'."""
    args = args or {}
    frappe.set_user(user)
    try:
        if kind == METHOD:
            frappe.get_attr(target)(**args)
        elif kind == REPORT:
            from frappe.desk.query_report import run as report_run
            report_run(target, filters=args or None, ignore_prepared_report=True)
        elif kind == DOCTYPE:
            dt, ptype = target
            return "ALLOWED" if frappe.has_permission(dt, ptype) else "DENIED"
        elif kind == READDOC:
            # 🔴 NOT frappe.get_doc — see the module docstring. This is the path
            # the desk takes, and the only one that consults permissions.
            frappe.client.get(target)
        return "ALLOWED"
    except frappe.PermissionError:
        return "DENIED"
    except Exception as e:
        # Reached the work and failed there — the gate OPENED. That is the
        # distinction the ALLOW direction needs on a mutating surface.
        return f"ERR:{type(e).__name__}"
    finally:
        frappe.set_user("Administrator")


def _allowed(verdict):
    return verdict != "DENIED"


# ── the matrix ─────────────────────────────────────────────────────────────
# (id, kind, target, args, who may, what is at stake)
SURFACES = [
    ("RM01-REPORT-FOLLOWUP", REPORT, "Attendance Follow-Up", {}, {"HR Manager"},
     "the outstanding-attendance worklist — it carries OT hours per person, so a "
     "supervisor reading it sees pay-relevant figures for people who are not theirs"),

    ("RM02-INGRESS-PREVIEW", METHOD, "caf.caf.ingress.reminder.preview", {},
     {"HR Manager"},
     "who has not been imported yet — an attendance gap list for the whole company"),

    ("RM03-EMPLOYEE-OPTIONS", METHOD,
     "caf.caf.doctype.ingress_import_batch.ingress_import_batch.employee_options",
     {"txt": "zz-no-such-person"}, {"HR Manager"},
     "the importer's employee picker, which discloses every active person's "
     "Ingress device id"),

    ("RM04-DASH-HEALTH", METHOD,
     "caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.get_data_health",
     {}, {"HR Manager"},
     "the appraisal dashboard's data-health panel — org-chart gaps across everyone"),

    ("RM05-DASH-HRFLAGS", METHOD,
     "caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.get_hr_review_flags",
     {}, {"HR Manager"},
     "Finger Logs flagged for a human — names, dates and why each is stuck"),

    ("RM10-BATCH-REVERT", METHOD,
     "caf.caf.doctype.ingress_import_batch.ingress_import_batch.revert",
     {"batch_name": "ZZ-NO-SUCH-BATCH"}, {"HR Manager"},
     "unwinds a whole import batch — cancels Attendance and deletes Finger Logs"),

    ("RM11-CHECKIN-MINT", METHOD,
     "caf.caf.doctype.finger_log.emp_checklist.make_employee_checkin_from_finger_log",
     {"doc": "ZZ-NO-SUCH-LOG"}, {"HR Manager"},
     "mints Employee Checkin rows with ignore_permissions — the hole its own "
     "docstring records being closed"),

    ("RM12-SYNC-SETTINGS", READDOC, "Ingress Sync Settings", {}, {"HR Manager"},
     "🔴 holds the Ingress machine's database password, and T-2 records that this "
     "credential still has ALL PRIVILEGES ON *.*. Probed the way the desk probes "
     "it — frappe.get_doc would answer ALLOWED for everyone and mean nothing"),

    ("RM14-FL-SUBMIT", DOCTYPE, ("Finger Log", "submit"), {}, {"HR Manager"},
     "submitting a Finger Log writes the Attendance verdict, and with it the OT"),

    ("RM15-ATT-CREATE", DOCTYPE, ("Attendance", "create"), {}, {"HR Manager"},
     "a hand-typed Attendance contradicts its Finger Log with no error — this is "
     "the 'Mark Attendance' question, and the answer is that only HR can reach it"),

    ("RM17-ROSTER-SUBMIT", DOCTYPE, ("Monthly Roster Confirmation", "submit"), {},
     {"HR Manager"},
     "confirming a month unlocks Finger Log submission for it — the roster gate"),

    ("RM18-SHIFT-WRITE", DOCTYPE, ("Shift Type", "write"), {},
     {"HR Manager"},
     "editing a Shift Type moves the contracted day, and with it everybody's short "
     "hours and OT basis. HR owns this; nobody else may touch it (FBR52/53)"),
]

# Surfaces that are deliberately open to everyone AND SCOPED per user. Asserting
# a denial here would be wrong — the supervisor page is built on them. What must
# be true is that a non-HR caller gets their own subtree and never `all`.
SCOPED = [
    ("RM06-DASH-PROGRESS", "get_monthly_progress",
     "per-cycle appraisal progress. Open on purpose — the supervisor page reads "
     "it — so the guarantee is the SCOPE, not the gate"),
    ("RM07-DASH-QUEUE", "get_action_queue",
     "what needs attention right now; a supervisor must see their own reports"),
    ("RM08-DASH-AFTERSUBMIT", "get_refreshed_after_submit",
     "appraisals whose SCORES moved after submission (OD-64) — the most sensitive "
     "rows on the page, and the ones a wrong scope would leak"),
]


def _scope_of(user, fn):
    frappe.set_user(user)
    try:
        from caf.caf.page.hr_appraisal_dashboard import hr_appraisal_dashboard as hd
        return frappe.get_attr(
            f"caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.{fn}")().get("scope")
    except frappe.PermissionError:
        return "DENIED"
    finally:
        frappe.set_user("Administrator")


def run():
    frappe.set_user("Administrator")
    try:
        who = _roster()
        print("Role → user on this site:")
        for role, user in who.items():
            print(f"   {role:<14} {user or '🔴 NONE FOUND'}")
        print()

        missing = [r for r, u in who.items() if not u]
        if missing:
            check("RM00-ROSTER", False,
                  f"no enabled user found for {missing} — the matrix cannot run, "
                  f"and every result below would be a false PASS")
            return _summary()
        check("RM00-ROSTER", True,
              f"resolved a real user for each of {list(who)} BY ROLE, not by "
              f"hardcoded login — so this runs unchanged on the prod-test server "
              f"(T-18), where the names differ")

        for tid, kind, target, args, may, stake in SURFACES:
            verdicts = {role: _probe(kind, target, user, dict(args))
                        for role, user in who.items()}
            allow_ok = all(_allowed(verdicts[r]) for r in may)
            deny_ok = all(not _allowed(verdicts[r]) for r in who if r not in may)
            shown = "  ".join(f"{r}={verdicts[r]}" for r in who)
            direction = [f"{'/'.join(sorted(may))} through" if allow_ok
                         else f"🔴 {'/'.join(sorted(may))} BLOCKED",
                         "others refused" if deny_ok else "🔴 OTHERS GET IN"]
            check(tid, allow_ok and deny_ok, f"[{', '.join(direction)}]  {shown}  —  {stake}")

        # ── the scoped panels ─────────────────────────────────────────────
        for tid, fn, stake in SCOPED:
            scopes = {r: _scope_of(u, fn) for r, u in who.items()}
            ok = (scopes["HR Manager"] == "all"
                  and scopes["Supervisor"] == "subtree"
                  and scopes["Employee"] == "subtree")
            check(tid, ok,
                  f"scope: " + "  ".join(f"{r}={scopes[r]}" for r in who)
                  + f"  —  {stake}")

        # ── RM13: what production will get vs what this site does ─────────
        _check_docperm_drift("Finger Log")

        # ── RM16: 🔴 the measured hole ────────────────────────────────────
        _check_ot_self_approval(who["Employee"])

    finally:
        frappe.set_user("Administrator")

    return _summary()


def _check_docperm_drift(doctype):
    """Does the EXPORTED FIXTURE still match this site's live Custom DocPerm?

    🔴 **Compare against `fixtures/custom_docperm.json`, NOT the doctype's own
    `.json`.** The first version of this check compared the two `.json` files and
    reported that Finger Log's permissions would arrive on production wrong. They
    will not: `Custom DocPerm` is a declared fixture in `hooks.py` (filtered to a
    list that includes Finger Log), so `bench migrate` imports these rows and they
    override the doctype's own DocPerm — which is exactly why the two differ, and
    why the difference is the design rather than a defect.

    The drift that CAN actually happen is quirks #44: a permission changed in Role
    Permissions Manager and never re-exported. That row lives only in this site's
    database, and production silently keeps the old one. So this compares
    **fixture vs live**, which is the pair that can genuinely disagree.

    ⚠️ **And when they do disagree, do not assume the narrower side is right.** On
    Finger Log, `create` is what actually gates amendment (`insert()` checks
    `create`, never `amend` — OD-48 · A1), so a "tidy-up" to `create = 0` would
    silently kill cancel-and-amend, the sanctioned route for correcting a
    submitted log. Resolve each row on what the permission DOES.
    """
    live = {r.role: r for r in frappe.get_all(
        "Custom DocPerm", filters={"parent": doctype, "permlevel": 0},
        fields=["role", "permlevel", "`read`", "`write`", "`create`", "`delete`",
                "submit", "cancel", "amend"])}

    path = frappe.get_app_path("caf", "fixtures", "custom_docperm.json")
    try:
        exported = {r["role"]: r for r in json.load(open(path))
                    if r.get("parent") == doctype and not r.get("permlevel")}
    except FileNotFoundError:
        check("RM13-FIXTURE-DRIFT", False,
              f"{path} does not exist — Custom DocPerm is declared as a fixture in "
              f"hooks.py but has never been exported, so NONE of this site's "
              f"permission rows would reach production (quirks #44)")
        return

    if not live and not exported:
        check("RM13-FIXTURE-DRIFT", True,
              f"{doctype} has no Custom DocPerm rows on either side — it runs on "
              f"the shipped .json, which travels with the app")
        return

    keys = ("read", "write", "create", "delete", "submit", "cancel", "amend")
    drift = []
    for role in sorted(set(exported) | set(live)):
        if role not in exported:
            drift.append(f"{role}: LIVE ONLY — never exported")
            continue
        if role not in live:
            drift.append(f"{role}: in the fixture but not on this site")
            continue
        for k in keys:
            a, b = int(exported[role].get(k, 0) or 0), int(live[role].get(k, 0) or 0)
            if a != b:
                drift.append(f"{role}.{k} fixture={a} live={b}")

    check("RM13-FIXTURE-DRIFT", not drift,
          f"{doctype}: this site's {len(live)} Custom DocPerm row(s) match the "
          f"exported fixture — {drift or 'identical'}. That fixture is what "
          f"`bench migrate` installs on production, so a match means everything "
          f"this suite proved here is also true there. ⚠️ A permission edited in "
          f"Role Permissions Manager and not re-exported lives only in this "
          f"database (quirks #44) — run `bench export-fixtures`")


def _check_ot_self_approval(emp_user):
    """OT Approval's two types have deliberately different gates. Assert both.

    🔴 **Corrected 2026-09-02. The first version of this check called the open
    `normal` type a hole; MG had already decided it, and was right.**

    FBR70 — a **normal** approval is open to the `Employee` role ON PURPOSE.
    Department reps file OT for their area, the reps rotate often, and CAF chose
    a wide create + submit over a role that would need reassigning every
    rotation. The controls are real and are asserted here: the `Employee` role
    holds **no cancel, no delete and no amend**, `owner` names whoever filed it,
    and most users additionally carry a `User Permission` scoping them to their
    own Employee record.

    FBR71 — **`special_approve` is a different instrument** and those controls do
    not reach it: it runs a raw `UPDATE ... SET docstatus = 2` over every other
    submitted row for the same (employee, date), and the Finger Log then takes
    its figure verbatim. It overrides an approval *without cancelling the
    document holding it* — and cancel is precisely what `Employee` lacks. Gated
    to HR Manager + Leave Approver on 2026-09-02.

    ⚠️ Nothing is written: the ALLOW direction rolls back, and the DENY direction
    never gets that far.
    """
    frappe.set_user("Administrator")

    # A plain employee whose own shift allows OT — otherwise a PASS would mean
    # "the fixture could not have overtime", which proves nothing.
    filer = None
    for r in frappe.db.sql(
        """SELECT e.user_id FROM `tabEmployee` e
           JOIN `tabShift Type` st ON st.name = e.default_shift
           WHERE e.status='Active' AND IFNULL(e.user_id,'')<>'' AND st.caf_allow_ot=1
           ORDER BY e.name""", as_dict=True):
        if set(frappe.get_roles(r.user_id)).isdisjoint(
                {"HR Manager", "HR User", "System Manager", "Leave Approver"}):
            filer = r.user_id
            break
    if not filer:
        check("RM16-OT-TYPE-GATES", True,
              "skipped: no ordinary employee on an OT-allowing shift on this site")
        return

    emp = frappe.db.get_value("Employee", {"user_id": filer}, "name")
    dept = frappe.db.get_value("Employee", emp, "department")
    taken = {str(d[0]) for d in frappe.db.sql(
        "SELECT DISTINCT work_date FROM `tabOT Approval Table` WHERE emp_id=%s", (emp,))}
    day = getdate("2026-06-01")
    for _ in range(60):
        if str(day) not in taken and day.weekday() != 6:
            break
        day = add_days(day, 1)

    def attempt(kind):
        frappe.set_user(filer)
        try:
            d = frappe.new_doc("OT Approval")
            d.work_date, d.type, d.reason, d.ot_department = str(day), kind, "probe", dept
            row = d.append("emp_list", {})
            row.emp_id, row.start_work, row.ot_end, row.ot_duration = (
                emp, "08:00:00", "19:00:00", 2.5)
            d.insert()
            return "ALLOWED"
        except frappe.PermissionError:
            return "DENIED"
        except Exception as e:
            return f"ERR:{type(e).__name__}"
        finally:
            frappe.set_user("Administrator")
            frappe.db.rollback()

    v_norm, v_spec = attempt("normal"), attempt("special_approve")

    perms = frappe.get_all(
        "Custom DocPerm", filters={"parent": "OT Approval", "role": "Employee"},
        fields=["`create`", "`delete`", "submit", "cancel", "amend"]) or frappe.get_all(
        "DocPerm", filters={"parent": "OT Approval", "role": "Employee"},
        fields=["`create`", "`delete`", "submit", "cancel", "amend"])
    e = perms[0] if perms else {}
    undo_locked = bool(e) and not (e.get("cancel") or e.get("delete") or e.get("amend"))

    check("RM16-OT-TYPE-GATES",
          v_norm != "DENIED" and v_spec == "DENIED" and undo_locked,
          f"{filer} (plain Employee) — normal={v_norm}, special_approve={v_spec}; "
          f"Employee cancel={e.get('cancel')} delete={e.get('delete')} "
          f"amend={e.get('amend')}. Normal is open BY BUSINESS RULE (FBR70) and "
          f"must stay open; special is the final arbiter and is gated to HR "
          f"Manager + Leave Approver (FBR71). The asymmetry — filing is open, "
          f"UNDOING is not — is what makes the open create safe, so all three "
          f"are asserted together")


def _summary():
    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
