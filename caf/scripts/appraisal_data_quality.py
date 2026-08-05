"""
CAF Appraisal - data quality checks
====================================
Purpose : Finds the data problems that make this product fail SILENTLY. Every
          check here exists because the failure it catches produces no error -
          just a wrong number, an empty screen, or a measurement that quietly
          stops being taken.
Doctype : reads Employee, Appraisal, Finger Log, HR Settings, Appraisal Template
Plan ref: CAF_appraisal_implementation_plan.md 5 Phase 7, section 9;
          D45/D51/D52/D53/D55/D69/D80/D86/D87, BR11/BR12, T19

Run:
    bench --site <site> execute caf.scripts.appraisal_data_quality.run
    bench --site <site> execute caf.scripts.appraisal_data_quality.run \
        --kwargs "{'as_dict': True}"

Exit behaviour: this reports, it never changes anything. Severity is either
ERROR (the product is actively broken for someone) or WARN (works today, will
bite later).

Changelog
---------
1.0  2026-08-05  Initial - Chunk 4
"""

import frappe

ERROR = "ERROR"
WARN = "WARN"
OK = "OK"


class Report:
    def __init__(self):
        self.findings = []

    def add(self, severity, check, message, rows=None):
        self.findings.append(
            {"severity": severity, "check": check, "message": message, "rows": rows or []}
        )

    def ok(self, check, message):
        self.add(OK, check, message)

    def as_text(self):
        lines = []
        for level in (ERROR, WARN, OK):
            group = [f for f in self.findings if f["severity"] == level]
            if not group:
                continue
            lines.append("")
            lines.append("%s (%d)" % (level, len(group)))
            lines.append("-" * 60)
            for f in group:
                lines.append("  [%s] %s" % (f["check"], f["message"]))
                for row in f["rows"][:25]:
                    lines.append("      %s" % row)
                if len(f["rows"]) > 25:
                    lines.append("      ... and %d more" % (len(f["rows"]) - 25))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# the tree the whole permission model rests on
# ---------------------------------------------------------------------------


def check_org_roots(r):
    """D53 - CAF has exactly two. More means an unintended extra root whose
    whole branch nobody can see; fewer means someone cleared a checkbox and
    that employee's record can no longer be saved."""
    roots = frappe.get_all(
        "Employee",
        filters={"status": "Active", "reports_to": ["in", ["", None]]},
        fields=["name", "employee_name", "caf_reports_to_nobody"],
    )

    if len(roots) == 2:
        r.ok("org-roots", "exactly 2 org roots, as D53 expects")
    else:
        r.add(
            ERROR,
            "org-roots",
            "expected exactly 2 employees with no reports_to (D53), found %d" % len(roots),
            ["%s %s" % (x.name, x.employee_name) for x in roots],
        )

    # D51 - an empty reports_to is only legal when the box is ticked. Rows that
    # violate this predate the rule or were written by direct SQL; they cannot
    # be saved through the UI any more, which is confusing if nobody knows why.
    unticked = [x for x in roots if not x.caf_reports_to_nobody]
    if unticked:
        r.add(
            ERROR,
            "org-roots-unticked",
            "%d employee(s) have no reports_to and no org-root tick - they will "
            "fail validation on the next save (D51)" % len(unticked),
            ["%s %s" % (x.name, x.employee_name) for x in unticked],
        )
    else:
        r.ok("org-roots-unticked", "every root carries the org-root tick")


def check_supervisor_logins(r):
    """BR11/D87 - has_permission resolves the acting user through
    Employee.user_id. A supervisor without one fails CLOSED: they see nothing
    and get no error.

    D87 makes this worse than it looks - the Employee ROLE is auto-stripped from
    any User with no mapped Employee on every User save
    (erpnext employee.py:237, wired via doc_events User.validate). So a broken
    link does not merely hide data, it can silently remove the role that D55
    depends on.
    """
    report_counts = {}
    for row in frappe.get_all("Employee", filters={"status": "Active"}, fields=["reports_to"]):
        if row.reports_to:
            report_counts[row.reports_to] = report_counts.get(row.reports_to, 0) + 1

    missing = frappe.get_all(
        "Employee",
        filters={"status": "Active", "user_id": ["in", ["", None]]},
        fields=["name", "employee_name"],
    )
    blocked = [(e, report_counts.get(e.name, 0)) for e in missing if report_counts.get(e.name)]

    if blocked:
        r.add(
            ERROR,
            "supervisor-no-login",
            "%d supervisor(s) have no Employee.user_id - nobody in their team can be "
            "appraised by them, and it fails silently (BR11/D87)" % len(blocked),
            ["%s %s (%d direct reports)" % (e.name, e.employee_name, n) for e, n in blocked],
        )
    else:
        r.ok("supervisor-no-login", "every supervisor has a linked User")

    non_supervisors = [e for e in missing if not report_counts.get(e.name)]
    if non_supervisors:
        r.add(
            WARN,
            "employee-no-login",
            "%d employee(s) have no User link. They supervise nobody so the permission "
            "layer is unaffected, but they cannot receive feedback or see their own "
            "appraisal" % len(non_supervisors),
            ["%s %s" % (e.name, e.employee_name) for e in non_supervisors],
        )


def check_user_role_mapping(r):
    """D87 - the reverse direction. A User holding the Employee role with no
    Employee record pointing back at them will LOSE that role on their next
    save."""
    users = frappe.get_all(
        "Has Role", filters={"role": "Employee", "parenttype": "User"}, pluck="parent"
    )
    if not users:
        return

    mapped = set(
        frappe.get_all(
            "Employee", filters={"user_id": ["in", users], "status": "Active"}, pluck="user_id"
        )
    )
    orphaned = [u for u in set(users) if u not in mapped]

    if orphaned:
        r.add(
            WARN,
            "role-will-be-stripped",
            "%d user(s) hold the Employee role with no active Employee mapped to them. "
            "erpnext validate_employee_role() removes that role on their next User save "
            "(D87), and stock Appraisal permissions grant create/write to it" % len(orphaned),
            sorted(orphaned),
        )
    else:
        r.ok("role-will-be-stripped", "every Employee-role user has an Employee record")


# ---------------------------------------------------------------------------
# the data the three auto-filled cells read
# ---------------------------------------------------------------------------


def check_shifts(r):
    """BR9 - punctuality resolves the shift through Employee.default_shift.
    Without one the cell is skipped, silently."""
    rows = frappe.db.sql(
        """
        SELECT name, employee_name FROM `tabEmployee`
        WHERE status = 'Active'
          AND IFNULL(caf_reports_to_nobody, 0) = 0
          AND (default_shift IS NULL OR default_shift = '')
        """,
        as_dict=True,
    )
    if rows:
        r.add(
            WARN,
            "no-default-shift",
            "%d appraisable employee(s) have no default_shift - their punctuality cell "
            "will always be blank (BR9)" % len(rows),
            ["%s %s" % (x.name, x.employee_name) for x in rows],
        )
    else:
        r.ok("no-default-shift", "every appraisable employee has a shift")


def check_holiday_lists(r):
    """D14/BR8 - the Remarks working-days figure reads Employee.holiday_list."""
    rows = frappe.db.sql(
        """
        SELECT name, employee_name FROM `tabEmployee`
        WHERE status = 'Active'
          AND IFNULL(caf_reports_to_nobody, 0) = 0
          AND (holiday_list IS NULL OR holiday_list = '')
        """,
        as_dict=True,
    )
    if rows:
        r.add(
            WARN,
            "no-holiday-list",
            "%d appraisable employee(s) have no holiday_list - their working-days figure "
            "falls back to calendar days (D14)" % len(rows),
            ["%s %s" % (x.name, x.employee_name) for x in rows],
        )
    else:
        r.ok("no-holiday-list", "every appraisable employee has a holiday list")


def check_leave_codes(r):
    """D69/T26 - a leave code that appears in Finger Log but is not configured
    is simply not counted. A new code arriving in a CSV import would go
    unnoticed forever."""
    configured = {
        c.strip()
        for c in (frappe.db.get_single_value("HR Settings", "caf_attendance_leave_codes") or "").split(",")
        if c.strip()
    }
    in_data = {
        row.leave_taken
        for row in frappe.db.sql(
            "SELECT DISTINCT leave_taken FROM `tabFinger Log` "
            "WHERE leave_taken IS NOT NULL AND leave_taken != ''",
            as_dict=True,
        )
    }

    uncovered = sorted(in_data - configured)
    if uncovered:
        r.add(
            WARN,
            "uncovered-leave-codes",
            "leave codes present in Finger Log but NOT counted as attendance issues: %s. "
            "Configured: %s (D69)" % (", ".join(uncovered), ", ".join(sorted(configured)) or "(none)"),
        )
    else:
        r.ok("uncovered-leave-codes", "every Finger Log leave code is accounted for")

    stale = sorted(configured - in_data)
    if stale:
        r.add(
            WARN,
            "stale-leave-codes",
            "configured codes that appear nowhere in Finger Log: %s" % ", ".join(stale),
        )


def check_final_ot(r):
    """D45/BR10 - the controller always assigns final_ot, so NULL on a submitted
    log means the row bypassed it (direct SQL, or an import that skipped
    on_submit). Those hours are silently summed as 0."""
    rows = frappe.db.sql(
        "SELECT name, employee, work_date FROM `tabFinger Log` "
        "WHERE docstatus = 1 AND final_ot IS NULL",
        as_dict=True,
    )
    if rows:
        r.add(
            ERROR,
            "null-final-ot",
            "%d SUBMITTED Finger Log row(s) have a NULL final_ot - they bypassed the "
            "controller and their OT is being counted as zero (D45)" % len(rows),
            ["%s %s %s" % (x.name, x.employee, x.work_date) for x in rows],
        )
    else:
        r.ok("null-final-ot", "no submitted Finger Log has a NULL final_ot")


# ---------------------------------------------------------------------------
# the product's own invariants
# ---------------------------------------------------------------------------


def check_impossible_times(r):
    """Finger Log rows whose Time fields exceed 24:00:00 cannot be saved AT ALL.

    ⚠️ THE DATA IS CORRECT. BR13: a CAF working period may legitimately exceed
    24 hours - a shift running past midnight is recorded as elapsed time from
    the start of the work date, not wrapped to a clock face. This check does NOT
    ask anyone to "fix" those values. The limitation is in the framework.

    MariaDB's TIME type legally holds up to 838:59:59, so a value like
    28:40:00 stores without complaint. But Frappe reads it back as a Python
    timedelta - `1 day, 4:40:00.800000` - and writing that string back is
    rejected:

        pymysql.err.OperationalError (1292): Incorrect time value:
        '1 day, 4:40:00.800000' for column tabFinger Log.time_in

    So the row is permanently unsaveable and unsubmittable, by anyone, with an
    HTTP 500 rather than a helpful message. Found 2026-08-05 when a test probe
    happened to pick one.

    Consequence for appraisals: these logs stay at docstatus 0 forever, and all
    three auto-filled cells count only SUBMITTED logs - so the attendance,
    lateness and overtime they represent are silently missing.
    """
    rows = frappe.db.sql(
        """
        SELECT name, employee, work_date, time_in, `out`
        FROM `tabFinger Log`
        WHERE time_in >= '24:00:00' OR `out` >= '24:00:00'
           OR `break` >= '24:00:00' OR resume >= '24:00:00'
        ORDER BY work_date
        """,
        as_dict=True,
    )
    if rows:
        r.add(
            ERROR,
            "impossible-clock-times",
            "%d Finger Log row(s) record a period of 24:00:00 or more. The DATA IS VALID "
            "(BR13 - a shift past midnight is elapsed time, not clock time), but Frappe "
            "cannot write a Time beyond 24h back to MariaDB, so these rows CANNOT be saved "
            "or submitted by anyone - any attempt returns HTTP 500. They therefore never "
            "reach docstatus 1, and the attendance/lateness/overtime they represent is "
            "silently absent from every appraisal. Needs a schema decision, not a data fix "
            "(D88)" % len(rows),
            ["%s %s %s in=%s out=%s" % (x.name, x.employee, x.work_date, x.time_in, x.out)
             for x in rows],
        )
    else:
        r.ok("impossible-clock-times", "no Finger Log row has a time beyond 24:00:00")


def check_appraisals_for_org_roots(r):
    """D86 - org roots are not appraised. Until 2026-08-05 this was only a
    filter on the cycle appraisee list, so anything created by hand slipped
    through. Rows found here predate the guard."""
    rows = frappe.db.sql(
        """
        SELECT a.name, a.employee, a.appraisal_cycle, a.workflow_state
        FROM `tabAppraisal` a
        INNER JOIN `tabEmployee` e ON e.name = a.employee
        WHERE IFNULL(e.caf_reports_to_nobody, 0) = 1 AND a.docstatus != 2
        """,
        as_dict=True,
    )
    if rows:
        r.add(
            ERROR,
            "appraisal-for-org-root",
            "%d appraisal(s) exist for an organisation root. Nobody supervises them, so "
            "these can never be completed and will hold the cycle below 100%% (D52/D86)" % len(rows),
            ["%s %s %s %s" % (x.name, x.employee, x.appraisal_cycle, x.workflow_state) for x in rows],
        )
    else:
        r.ok("appraisal-for-org-root", "no appraisals point at an org root")


def check_workflow(r):
    """D72 - a missing Workflow fails SILENTLY. Frappe applies none: appraisals
    submit straight through with no HR review and no error anywhere."""
    from frappe.model.workflow import get_workflow_name

    name = get_workflow_name("Appraisal")
    if not name:
        r.add(
            ERROR,
            "workflow-missing",
            "NO workflow is attached to Appraisal. Appraisals will submit straight "
            "through with no HR review, and nothing will warn anyone (D72)",
        )
        return

    doc = frappe.get_cached_doc("Workflow", name)
    states = {s.state for s in doc.states}
    expected_states = {"Draft", "Pending HR Review", "Completed"}
    transitions = {(t.state, t.action, t.next_state) for t in doc.transitions}
    expected_transitions = {
        ("Draft", "Submit for Review", "Pending HR Review"),
        ("Pending HR Review", "Approve", "Completed"),
        ("Pending HR Review", "Reject", "Draft"),
    }

    problems = []
    if not doc.is_active:
        problems.append("workflow is not active")
    if states != expected_states:
        problems.append("states differ: %s" % sorted(states ^ expected_states))
    if transitions != expected_transitions:
        problems.append("transitions differ: %s" % sorted(transitions ^ expected_transitions))

    self_approval = [t for t in doc.transitions if t.action == "Approve" and t.allow_self_approval]
    if self_approval:
        problems.append("Approve allows self-approval - a supervisor could approve their own")

    if problems:
        r.add(ERROR, "workflow", "%s: %s" % (name, "; ".join(problems)))
    else:
        r.ok("workflow", "%s is active with the expected 3 states and 3 transitions" % name)


def check_templates(r):
    """D83 - a template missing one of the three auto-filled KRAs drops that
    measurement for every employee in the departments using it."""
    from caf.caf.overrides.appraisal import AUTO_FILLED_KRAS

    for template in frappe.get_all("Appraisal Template", pluck="name"):
        doc = frappe.get_doc("Appraisal Template", template)
        present = {g.key_result_area for g in doc.goals}
        missing = [k for k in AUTO_FILLED_KRAS if k not in present]
        if missing:
            r.add(
                WARN,
                "template-missing-kra",
                "template %r has no %s row - appraisals using it will not report that "
                "at all (D83)" % (template, ", ".join(missing)),
            )

    used = frappe.get_all(
        "Department",
        filters={"caf_appraisal_template": ["is", "set"]},
        fields=["name", "caf_appraisal_template"],
    )
    if not used:
        r.add(
            WARN,
            "no-department-templates",
            "no department has a template set - everyone falls back to the default (BR4/D82)",
        )
    else:
        r.ok("department-templates", "%d department(s) have a template assigned" % len(used))


# ---------------------------------------------------------------------------


CHECKS = [
    check_org_roots,
    check_supervisor_logins,
    check_user_role_mapping,
    check_shifts,
    check_holiday_lists,
    check_leave_codes,
    check_final_ot,
    check_impossible_times,
    check_appraisals_for_org_roots,
    check_workflow,
    check_templates,
]


def run(as_dict=False):
    r = Report()
    for check in CHECKS:
        try:
            check(r)
        except Exception as exc:
            r.add(ERROR, check.__name__, "check itself failed: %s" % exc)

    errors = len([f for f in r.findings if f["severity"] == ERROR])
    warns = len([f for f in r.findings if f["severity"] == WARN])

    if as_dict:
        return {"findings": r.findings, "errors": errors, "warnings": warns}

    print("CAF Appraisal - data quality")
    print("=" * 60)
    print(r.as_text())
    print("")
    print("=" * 60)
    print("%d error(s), %d warning(s)" % (errors, warns))
    return None
