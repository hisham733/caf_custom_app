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
    """Custom DocPerm on this site vs the DocPerm shipped in the .json.

    Production receives the `.json`. This site has whatever a person clicked in
    Role Permissions Manager. When they disagree, every permission result above
    is true *here* and unproven *there* — which is the whole risk T-18 exists to
    retire.
    """
    slug = doctype.lower().replace(" ", "_")
    path = frappe.get_app_path("caf", "caf", "doctype", slug, f"{slug}.json")
    shipped = {r["role"]: r for r in json.load(open(path))["permissions"]}
    live = {r.role: r for r in frappe.get_all(
        "Custom DocPerm", filters={"parent": doctype},
        fields=["role", "`read`", "`write`", "`create`", "`delete`", "submit", "cancel", "amend"])}

    if not live:
        check("RM13-DOCPERM-DRIFT", True,
              f"{doctype} has no Custom DocPerm rows — the site runs on the "
              f"shipped .json, so production and this site cannot disagree")
        return

    keys = ("read", "write", "create", "delete", "submit", "cancel", "amend")
    drift = []
    for role in sorted(set(shipped) | set(live)):
        if role not in shipped:
            drift.append(f"{role}: live only")
            continue
        if role not in live:
            drift.append(f"{role}: .json only")
            continue
        for k in keys:
            a, b = int(shipped[role].get(k, 0)), int(live[role].get(k, 0) or 0)
            if a != b:
                drift.append(f"{role}.{k} .json={a} live={b}")

    check("RM13-DOCPERM-DRIFT", not drift,
          f"{doctype}: {len(drift) or 'no'} difference(s) between the shipped "
          f".json and this site's Custom DocPerm — {drift or 'identical'}. "
          f"🔴 Production gets the .json. Where these disagree, everything this "
          f"suite proved is true HERE and unproven THERE (T-18)")


def _check_ot_self_approval(emp_user):
    """🔴 Can an ordinary employee approve their own overtime?

    Measured, not inferred. `OT Approval` has no workflow and no `has_permission`
    hook, and its shipped .json grants the `Employee` role create + write +
    submit. So the permission layer has nothing to say — and an OT hour that
    reaches a submitted approval is a PAID hour.

    Builds one document and removes it in `finally`, because a permission row is
    not proof: the first two attempts were stopped by business rules (a duplicate
    day, a wrong duration) and would have been reported as a PASS by any suite
    that only looked at the exception type.
    """
    frappe.set_user("Administrator")
    emp = frappe.db.get_value("Employee", {"user_id": emp_user}, "name")
    if not emp:
        check("RM16-OT-SELF-APPROVAL", True,
              f"skipped: {emp_user} has no Employee record to name")
        return

    shift = frappe.db.get_value("Employee", emp, "default_shift")
    if not shift or not frappe.db.get_value("Shift Type", shift, "caf_allow_ot"):
        # Find any non-privileged employee whose shift does allow OT — otherwise
        # this test passes because the FIXTURE could not have OT, which proves
        # nothing about the permission model.
        for r in frappe.db.sql(
            """SELECT e.name, e.user_id FROM `tabEmployee` e
               JOIN `tabShift Type` st ON st.name = e.default_shift
               WHERE e.status='Active' AND IFNULL(e.user_id,'')<>''
                 AND st.caf_allow_ot = 1""", as_dict=True):
            roles = set(frappe.get_roles(r.user_id))
            if roles.isdisjoint({"HR Manager", "HR User", "System Manager"}):
                emp, emp_user = r.name, r.user_id
                break
        else:
            check("RM16-OT-SELF-APPROVAL", True,
                  "skipped: no ordinary employee on an OT-allowing shift on this site")
            return

    taken = {str(d[0]) for d in frappe.db.sql(
        "SELECT DISTINCT work_date FROM `tabOT Approval Table` WHERE emp_id=%s", (emp,))}
    day = getdate("2026-06-01")
    for _ in range(60):
        if str(day) not in taken and day.weekday() != 6:
            break
        day = add_days(day, 1)

    made, verdict = None, None
    frappe.set_user(emp_user)
    try:
        d = frappe.new_doc("OT Approval")
        d.work_date = str(day)
        d.reason = "role matrix probe"
        d.ot_department = frappe.db.get_value("Employee", emp, "department")
        row = d.append("emp_list", {})
        row.emp_id, row.start_work, row.ot_end, row.ot_duration = emp, "08:00:00", "19:00:00", 2.5
        d.insert()
        made = d.name
        d.submit()
        verdict = f"SUBMITTED docstatus={d.docstatus}"
    except frappe.PermissionError:
        verdict = "refused by permissions"
    except Exception as e:
        verdict = f"reached validate() and stopped there: {type(e).__name__}"
    finally:
        frappe.set_user("Administrator")
        if made and frappe.db.exists("OT Approval", made):
            doc = frappe.get_doc("OT Approval", made)
            if doc.docstatus == 1:
                doc.flags.ignore_permissions = True
                doc.cancel()
            frappe.delete_doc("OT Approval", made, force=True, ignore_permissions=True)
        frappe.db.commit()

    check("RM16-OT-SELF-APPROVAL", verdict == "refused by permissions",
          f"{emp_user} (roles: "
          f"{sorted(r for r in frappe.get_roles(emp_user) if r not in ('All', 'Guest'))}) "
          f"raising an OT Approval that names themselves for 2.5h on {day}: "
          f"{verdict}. 🔴 OT Approval has no workflow and no has_permission hook, "
          f"and its .json grants the Employee role create+write+submit — so an "
          f"employee can approve their own paid overtime. Fix by role (drop submit "
          f"from Employee) or by controller guard (the rows must be the caller's "
          f"reports); a JS-only check will not hold (quirks #29)")


def _summary():
    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
