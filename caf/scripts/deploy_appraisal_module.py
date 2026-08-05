"""
CAF Appraisal - production deployment
======================================
Purpose : Applies everything this product needs that does NOT live in git.
          `bench migrate` carries code, Custom Fields, Property Setters and
          Custom DocPerm rows. It does not carry the Workflow record, the KRA
          master rows, the Appraisal Template, the HR Settings values, or any
          Employee data. Build it all on a laptop and none of that reaches
          production by itself.
Doctype : KRA, Appraisal Template, HR Settings, Global Defaults, Workflow,
          Workflow State, Workflow Action Master (creates); Employee (reports only)
Plan ref: CAF_appraisal_implementation_plan.md section 9, D58/D72/D83/D86/D87/D92

Run:
    # look first, change nothing
    bench --site <site> execute caf.scripts.deploy_appraisal_module.dry_run

    # then for real
    bench --site <site> execute caf.scripts.deploy_appraisal_module.run

(`dry_run` is a separate entry point rather than a kwarg because passing
`--kwargs "{'dry_run': True}"` is awkward from PowerShell, which is what this
project's shell is - it parses the colon as an operator.)

Reports in three buckets:
    APPLIED     - created or changed by this run
    ALREADY OK  - present and correct, left alone
    NEEDS HUMAN - only HR can do it, listed per employee so they get a worklist

Design commitments (section 9.2)
--------------------------------
* Idempotent - safe to re-run; skips what exists rather than duplicating.
* Self-testing - verifies each item after applying it and fails loudly on a
  mismatch, because the framework will not.
* Refuses to run when the permission model is not what the plan assumes
  (T23 - Custom DocPerm is site-local, so dev findings do not transfer).
* Asserts the Workflow exists with the expected states and transitions. This is
  not bookkeeping: a missing Workflow raises NO error - Frappe simply applies
  none, so appraisals submit straight through with no HR review and nobody is
  told (D72, verified live 2026-08-05).

Changelog
---------
1.0  2026-08-05  Initial - Chunk 4
"""

import frappe

APPLIED = "APPLIED"
ALREADY_OK = "ALREADY OK"
NEEDS_HUMAN = "NEEDS HUMAN"
BLOCKED = "BLOCKED"

# --- what the plan says must exist -----------------------------------------

KRAS = [
    ("Attendance", "Unpaid-leave days in the month, auto-filled from Finger Log."),
    ("Punctuality", "Days clocked in after the shift start time, auto-filled from Finger Log."),
    ("OT Hours", "Total approved overtime for the month, auto-filled from Finger Log."),
    ("Meeting the Deadline", "Whether assigned work was completed on time."),
    ("No Mistakes", "Quality of work - errors, rework and their consequences."),
    ("Teamwork", "Cooperation with colleagues and contribution to the team."),
]

TEMPLATE = "CAF Monthly Appraisal"
TEMPLATE_GOALS = [
    ("Attendance", 17),
    ("Punctuality", 17),
    ("OT Hours", 17),
    ("Meeting the Deadline", 17),
    ("No Mistakes", 16),
    ("Teamwork", 16),
]

HR_SETTINGS = {
    "caf_enable_score_calculation": 0,   # D2/BR5 - CAF does not score today
    "caf_min_late_minutes": 0,           # D8/DR7 - any lateness counts
    "caf_attendance_leave_codes": "UPL, 0.5UPL",  # D69/BR8
    "caf_cycle_frequency": "Monthly",    # BR1
    "caf_feedback_window_months": 12,    # D61
    "caf_show_feedback_author": 1,       # D62
}

WORKFLOW_NAME = "CAF Appraisal Workflow"
WORKFLOW_STATES = [("Draft", ""), ("Pending HR Review", "Warning"), ("Completed", "Success")]
WORKFLOW_ACTIONS = ["Submit for Review", "Approve", "Reject"]
STATES = [
    ("Draft", "0", "Employee"),
    ("Pending HR Review", "0", "HR Manager"),
    ("Completed", "1", "HR Manager"),
]
TRANSITIONS = [
    ("Draft", "Submit for Review", "Pending HR Review", "Employee", 1),
    ("Pending HR Review", "Approve", "Completed", "HR Manager", 0),
    ("Pending HR Review", "Reject", "Draft", "HR Manager", 0),
]

# --- the permission state the plan assumes (section 4.12) ------------------

REQUIRED_PERMS = [
    # (doctype, role, permlevel, ptype)
    ("KRA", "HR Manager", 0, "create"),
    ("KRA", "Employee", 0, "read"),
    ("HR Settings", "HR Manager", 1, "read"),
    ("HR Settings", "HR Manager", 1, "write"),
    ("Employee Performance Feedback", "HR Manager", 1, "read"),
]
FORBIDDEN_PERMS = [
    # role `All` must NOT be able to write Finger Log (D40) - all three
    # auto-filled cells read from it
    ("Finger Log", "All", 0, "write"),
    ("Finger Log", "All", 0, "create"),
    ("Finger Log", "All", 0, "submit"),
]


class Deployment:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.buckets = {APPLIED: [], ALREADY_OK: [], NEEDS_HUMAN: [], BLOCKED: []}

    def record(self, bucket, message, rows=None):
        self.buckets[bucket].append({"message": message, "rows": rows or []})

    def report(self):
        out = ["", "CAF Appraisal deployment%s" % (" (DRY RUN - nothing changed)" if self.dry_run else "")]
        out.append("=" * 68)
        for bucket in (BLOCKED, APPLIED, ALREADY_OK, NEEDS_HUMAN):
            items = self.buckets[bucket]
            if not items:
                continue
            out.append("")
            out.append("%s (%d)" % (bucket, len(items)))
            out.append("-" * 68)
            for item in items:
                out.append("  %s" % item["message"])
                for row in item["rows"][:40]:
                    out.append("      %s" % row)
                if len(item["rows"]) > 40:
                    out.append("      ... and %d more" % (len(item["rows"]) - 40))
        return "\n".join(out)


# ---------------------------------------------------------------------------
# gate: refuse to deploy onto an unexpected permission model (T23)
# ---------------------------------------------------------------------------


def _has_perm(doctype, role, permlevel, ptype):
    """Effective permission: Custom DocPerm rows REPLACE the shipped DocPerm
    rows entirely when any exist for that doctype."""
    table = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "DocPerm"
    return bool(
        frappe.db.get_value(
            table, {"parent": doctype, "role": role, "permlevel": permlevel, ptype: 1}
        )
    )


def check_permissions(d):
    missing = [
        "%s / %s / permlevel %s / %s" % (dt, role, pl, ptype)
        for dt, role, pl, ptype in REQUIRED_PERMS
        if not _has_perm(dt, role, pl, ptype)
    ]
    present = [
        "%s / %s / permlevel %s / %s" % (dt, role, pl, ptype)
        for dt, role, pl, ptype in FORBIDDEN_PERMS
        if _has_perm(dt, role, pl, ptype)
    ]

    if missing:
        d.record(
            BLOCKED,
            "Required permissions are missing. Run `bench migrate` first so the "
            "Custom DocPerm fixtures land, then re-run this script (section 4.12 / D33).",
            missing,
        )
    if present:
        d.record(
            BLOCKED,
            "Finger Log is still writable by the role `All`. Every auto-filled cell reads "
            "from Finger Log, so any user could edit the data driving their own appraisal "
            "(D40).",
            present,
        )

    if not missing and not present:
        d.record(ALREADY_OK, "permission model matches the plan (section 4.12)")
        return True
    return False


# ---------------------------------------------------------------------------
# the data items
# ---------------------------------------------------------------------------


def deploy_kras(d):
    created, existing = [], []
    for title, description in KRAS:
        if frappe.db.exists("KRA", title):
            existing.append(title)
            continue
        created.append(title)
        if not d.dry_run:
            frappe.get_doc({"doctype": "KRA", "title": title, "description": description}).insert(
                ignore_permissions=True
            )

    if created:
        d.record(APPLIED, "created %d KRA master row(s)" % len(created), created)
    if existing:
        d.record(ALREADY_OK, "%d KRA row(s) already present" % len(existing), existing)

    if not d.dry_run:
        for title, _desc in KRAS:
            if not frappe.db.exists("KRA", title):
                frappe.throw("KRA %r was not created" % title)


def deploy_template(d):
    total = sum(w for _, w in TEMPLATE_GOALS)
    if total != 100:
        frappe.throw("Template weightage totals %s, must be 100" % total)

    if frappe.db.exists("Appraisal Template", TEMPLATE):
        d.record(ALREADY_OK, "Appraisal Template %r present" % TEMPLATE)
    else:
        d.record(APPLIED, "created Appraisal Template %r (%d KRAs, total %d)"
                 % (TEMPLATE, len(TEMPLATE_GOALS), total))
        if not d.dry_run:
            frappe.get_doc(
                {
                    "doctype": "Appraisal Template",
                    "template_title": TEMPLATE,
                    "description": "Monthly appraisal template matching the CAF paper form.",
                    "goals": [
                        {"key_result_area": k, "per_weightage": w} for k, w in TEMPLATE_GOALS
                    ],
                }
            ).insert(ignore_permissions=True)
            if not frappe.db.exists("Appraisal Template", TEMPLATE):
                frappe.throw("Appraisal Template %r was not created" % TEMPLATE)


def deploy_hr_settings(d):
    def norm(value):
        # NOT `value or ""` - that maps 0 to "" and would report every correct
        # zero (caf_enable_score_calculation, caf_min_late_minutes) as a change
        return "" if value is None else str(value)

    changed, same = [], []
    for field, wanted in HR_SETTINGS.items():
        current = frappe.db.get_single_value("HR Settings", field)
        if norm(current) == norm(wanted):
            same.append("%s = %r" % (field, current))
        else:
            changed.append("%s: %r -> %r" % (field, current, wanted))

    if changed:
        d.record(APPLIED, "set %d HR Settings value(s)" % len(changed), changed)
        if not d.dry_run:
            doc = frappe.get_single("HR Settings")
            for field, wanted in HR_SETTINGS.items():
                doc.set(field, wanted)
            doc.flags.ignore_permissions = True
            doc.save(ignore_permissions=True)
            for field, wanted in HR_SETTINGS.items():
                got = frappe.db.get_single_value("HR Settings", field)
                if norm(got) != norm(wanted):
                    frappe.throw("HR Settings.%s is %r, expected %r" % (field, got, wanted))
    if same:
        d.record(ALREADY_OK, "%d HR Settings value(s) already correct" % len(same), same)


def deploy_global_default_company(d):
    """D92 - make `company` an actual default, not just a Global Defaults field.

    Global Defaults.default_company was already "CAF" on dev, but the
    tabDefaultValue row it is supposed to write was missing, so
    frappe.defaults.get_default("company") returned None. Two visible symptoms:
    the Appraisal form opened with Company blank and made the supervisor pick a
    value from a list of one, and the hrms organisational chart - whose company
    filter defaults to exactly that key - refused to draw until you chose CAF.

    Re-saving the Single is what populates it: GlobalDefaults.on_update() loops
    its keydict into frappe.db.set_default(). Nothing here sets the value, so
    this is safe on a multi-company site: it only publishes whatever
    default_company already says.
    """
    default_company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not default_company:
        d.record(
            NEEDS_HUMAN,
            "Global Defaults has no default_company - set it before go-live",
            ["Appraisal Company and the org chart will both keep asking without it"],
        )
        return

    # frappe.defaults has no get_default() - that name only exists on the JS
    # side. The Python equivalent is frappe.db.get_default (or
    # frappe.defaults.get_global_default, which is the same __default row).
    if frappe.db.get_default("company") == default_company:
        d.record(ALREADY_OK, "default company published as %r" % default_company)
        return

    d.record(APPLIED, "published default company %r" % default_company)
    if d.dry_run:
        return

    # on_update() does the work; saving unchanged is enough to trigger it.
    frappe.get_doc("Global Defaults").save(ignore_permissions=True)
    got = frappe.db.get_default("company")
    if got != default_company:
        frappe.throw("default company is %r, expected %r" % (got, default_company))


def deploy_workflow(d):
    """D72 - the one item whose absence produces no error at all."""
    for name, style in WORKFLOW_STATES:
        if not frappe.db.exists("Workflow State", name):
            d.record(APPLIED, "created Workflow State %r" % name)
            if not d.dry_run:
                frappe.get_doc(
                    {"doctype": "Workflow State", "workflow_state_name": name, "style": style}
                ).insert(ignore_permissions=True)

    for name in WORKFLOW_ACTIONS:
        if not frappe.db.exists("Workflow Action Master", name):
            d.record(APPLIED, "created Workflow Action Master %r" % name)
            if not d.dry_run:
                frappe.get_doc(
                    {"doctype": "Workflow Action Master", "workflow_action_name": name}
                ).insert(ignore_permissions=True)

    exists = frappe.db.exists("Workflow", WORKFLOW_NAME)
    if exists:
        d.record(ALREADY_OK, "Workflow %r present" % WORKFLOW_NAME)
    else:
        d.record(APPLIED, "created Workflow %r" % WORKFLOW_NAME)

    if d.dry_run:
        return

    doc = frappe.get_doc("Workflow", WORKFLOW_NAME) if exists else frappe.new_doc("Workflow")
    doc.workflow_name = WORKFLOW_NAME
    doc.document_type = "Appraisal"
    doc.workflow_state_field = "workflow_state"
    doc.is_active = 1
    doc.send_email_alert = 0

    doc.set("states", [])
    for state, doc_status, allow_edit in STATES:
        doc.append("states", {"state": state, "doc_status": doc_status, "allow_edit": allow_edit})

    doc.set("transitions", [])
    for state, action, next_state, allowed, self_approval in TRANSITIONS:
        doc.append(
            "transitions",
            {
                "state": state,
                "action": action,
                "next_state": next_state,
                "allowed": allowed,
                "allow_self_approval": self_approval,
            },
        )
    doc.save(ignore_permissions=True)

    # D74 - never leave the initial state blank. CAF's last commit on develop
    # before this project was the fix for exactly that.
    cf = frappe.db.get_value("Custom Field", {"dt": "Appraisal", "fieldname": "workflow_state"})
    if cf and frappe.db.get_value("Custom Field", cf, "default") != "Draft":
        frappe.db.set_value("Custom Field", cf, "default", "Draft")
        d.record(APPLIED, "pinned Appraisal.workflow_state default to 'Draft' (D74)")

    assert_workflow(d)


def assert_workflow(d):
    doc = frappe.get_doc("Workflow", WORKFLOW_NAME)
    problems = []
    if not doc.is_active:
        problems.append("not active")
    if {(s.state, s.doc_status, s.allow_edit) for s in doc.states} != set(STATES):
        problems.append("states do not match")
    got = {(t.state, t.action, t.next_state, t.allowed, int(t.allow_self_approval)) for t in doc.transitions}
    if got != set(TRANSITIONS):
        problems.append("transitions do not match")
    if problems:
        frappe.throw("Workflow %s: %s" % (WORKFLOW_NAME, "; ".join(problems)))
    d.record(ALREADY_OK, "Workflow verified: 3 states, 3 transitions, self-approval off")


# ---------------------------------------------------------------------------
# what only HR can do
# ---------------------------------------------------------------------------


def collect_human_work(d):
    active = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name", "reports_to", "user_id", "holiday_list",
                "department", "caf_reports_to_nobody"],
        order_by="name",
    )

    no_reports_to = [e for e in active if not e.reports_to and not e.caf_reports_to_nobody]
    if no_reports_to:
        d.record(
            NEEDS_HUMAN,
            "Set Reports To on %d employee(s), or tick 'Reports To Nobody' if they are a "
            "company director. Nothing else in this product works without it - it is what "
            "decides who may appraise whom (BR3/D15)." % len(no_reports_to),
            ["%s  %s" % (e.name, e.employee_name) for e in no_reports_to],
        )

    roots = [e for e in active if e.caf_reports_to_nobody]
    if len(roots) != 2:
        d.record(
            NEEDS_HUMAN,
            "Expected exactly 2 organisation roots (D53), found %d. Tick 'Reports To "
            "Nobody' on each managing director and untick it on anyone else." % len(roots),
            ["%s  %s" % (e.name, e.employee_name) for e in roots],
        )

    report_counts = {}
    for e in active:
        if e.reports_to:
            report_counts[e.reports_to] = report_counts.get(e.reports_to, 0) + 1

    supervisors_no_login = [e for e in active if not e.user_id and report_counts.get(e.name)]
    if supervisors_no_login:
        d.record(
            NEEDS_HUMAN,
            "Create a User and set User ID on %d SUPERVISOR(s). Without it they cannot "
            "appraise anyone and it fails silently - they simply see nothing (BR11/D87). "
            "This includes directors: being an org root exempts you from being appraised, "
            "not from appraising (BR12)." % len(supervisors_no_login),
            ["%s  %s  (%d direct reports)" % (e.name, e.employee_name, report_counts.get(e.name, 0))
             for e in supervisors_no_login],
        )

    no_holiday = [e for e in active if not e.holiday_list and not e.caf_reports_to_nobody]
    if no_holiday:
        d.record(
            NEEDS_HUMAN,
            "Attach a Holiday List to %d employee(s). Without one the working-days figure "
            "on the Attendance row falls back to calendar days (D14/D46)." % len(no_holiday),
            ["%s  %s" % (e.name, e.employee_name) for e in no_holiday],
        )

    no_shift = [e for e in active if not e.caf_reports_to_nobody
                and not frappe.db.get_value("Employee", e.name, "default_shift")]
    if no_shift:
        d.record(
            NEEDS_HUMAN,
            "Set Default Shift on %d employee(s), or their punctuality cell stays blank "
            "forever (BR9)." % len(no_shift),
            ["%s  %s" % (e.name, e.employee_name) for e in no_shift],
        )

    departments = frappe.get_all("Department", filters={"is_group": 0}, pluck="name")
    unmapped = [
        dept for dept in departments
        if not frappe.db.get_value("Department", dept, "caf_appraisal_template")
        and frappe.db.exists("Employee", {"department": dept, "status": "Active"})
    ]
    if unmapped:
        d.record(
            NEEDS_HUMAN,
            "Optionally set a Default Appraisal Template on %d department(s) with staff. "
            "Anything left blank falls back to %r, which is a valid choice (BR4/D82)."
            % (len(unmapped), TEMPLATE),
            unmapped,
        )

    d.record(
        NEEDS_HUMAN,
        "Finally: HR runs 'Create Monthly Cycles for Year' from the Appraisal Cycle list "
        "view (D39), then the section 2.10 role probes are run against production before "
        "go-live (section 9.3 steps 6-7).",
    )


# ---------------------------------------------------------------------------


def dry_run():
    """Report what would change, without changing anything (section 9.3 step 3)."""
    return run(dry_run=True)


def run(dry_run=False):
    d = Deployment(dry_run=dry_run)

    if not check_permissions(d):
        print(d.report())
        print("")
        print("REFUSED - fix the BLOCKED items above and re-run. Nothing was changed.")
        return

    deploy_kras(d)
    deploy_template(d)
    deploy_hr_settings(d)
    deploy_global_default_company(d)
    deploy_workflow(d)
    collect_human_work(d)

    if not dry_run:
        frappe.db.commit()

    print(d.report())
    print("")
    print("=" * 68)
    if dry_run:
        print("DRY RUN - nothing was changed. Re-run without dry_run to apply.")
    else:
        print("Done. Review the NEEDS HUMAN list with HR before announcing go-live.")
