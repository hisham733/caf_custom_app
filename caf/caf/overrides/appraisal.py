"""
CAF Appraisal - Appraisal controller override, auto-fill and permission layer
=============================================================================
Purpose : Replaces stock hrms Appraisal via override_doctype_class. Holds the
          CAF grid auto-fill (UPL dates, lateness, approved OT), the
          supervisor permission hooks, the score toggle, and the yearly
          cycle-creation action.
Doctype : Appraisal (stock, extended)  |  Hook: override_doctype_class
Reads   : Finger Log (single source of truth, D12/D22), Shift Type,
          Holiday List, HR Settings (CAF toggles, permlevel 1)
Plan ref: CAF_appraisal_implementation_plan.md 4.2, 4.5, 4.9, 4.13,
          D3/D12/D18/D20/D24/D28/D31/D39/D45/D52/D55/D56/D63/D68/D69;
          build_brief_chunk2.md 4.1-4.4

Everything Appraisal-related lives in this one module (D20) - the helpers have
no stock original to override, so they are plain module functions rather than a
separate appraisal_helpers.py.

Changelog
---------
1.0  2026-08-05  Initial - Chunk 2: helpers, CustomAppraisal, create_monthly_cycles,
                 has_permission / get_permission_query_conditions
"""

import calendar
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, get_last_day, getdate, now, nowdate
from frappe.utils.nestedset import get_descendants_of

from hrms.hr.doctype.appraisal.appraisal import Appraisal

# The three KRA rows the system fills in. Titles match the seeded KRA records
# and the paper form; the remaining three rows are the supervisor's judgement.
KRA_ATTENDANCE = "Attendance"
KRA_PUNCTUALITY = "Punctuality"
KRA_OT_HOURS = "OT Hours"
AUTO_FILLED_KRAS = (KRA_ATTENDANCE, KRA_PUNCTUALITY, KRA_OT_HOURS)

# Codes that mean "half a day". The date cell marks these with a 1/2 sign so the
# supervisor can see the difference on the form without any numeric weighting
# behind it (D67/D68).
HALF_DAY_CODES = {"0.5UPL"}

# Written as an escape rather than a literal: this file travels through shells
# and heredocs that mangle non-ASCII (protocol_session_2026-08-05 section 3).
HALF = "½"

# DR7 - the lateness threshold is configuration, not a magic number buried in a
# comparison. HR Settings.caf_min_late_minutes overrides this default.
DEFAULT_MIN_LATE_MINUTES = 0


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------


def caf_setting(fieldname, default=None):
    """Server-side reads bypass permissions, so permlevel 1 (D43) does not
    affect CAF's own code."""
    value = frappe.db.get_single_value("HR Settings", fieldname)
    return default if value in (None, "") else value


def scoring_enabled():
    """D2/BR5 - CAF does not score appraisals today. Stock scoring code stays
    in place (DR2) but is skipped while this is off."""
    return bool(cint(caf_setting("caf_enable_score_calculation", 0)))


def attendance_leave_codes():
    """D69/BR8 - which Finger Log leave codes count as an attendance issue.
    Data, not logic: HR edits the field, no code change."""
    raw = caf_setting("caf_attendance_leave_codes", "") or ""
    return [code.strip() for code in raw.split(",") if code.strip()]


def min_late_minutes():
    return cint(caf_setting("caf_min_late_minutes", DEFAULT_MIN_LATE_MINUTES))


# ---------------------------------------------------------------------------
# D68 - date cell formatting
# ---------------------------------------------------------------------------


def format_day_cell(entries):
    """Render day numbers per D68: consecutive days collapsed to a range,
    half-days suffixed, blank when there is nothing.

    `entries` is an iterable of (day_number, is_half_day).
    Samples: "3, 11, 24" - "8-10, 22" - "3, 27<half>" - "" .

    Month and year are deliberately omitted: they come from the cycle, and the
    paper form's Date column is narrow. This keeps the worst realistic case
    (late most of the month) to roughly 40 characters.
    """
    by_day = {}
    for day, is_half in entries:
        # a full day wins over a half day if both somehow appear
        by_day[day] = by_day.get(day, True) and is_half

    parts = []
    run_start = run_end = None

    def flush():
        if run_start is None:
            return
        if run_start == run_end:
            parts.append(str(run_start))
        elif run_end == run_start + 1:
            parts.append("%d, %d" % (run_start, run_end))
        else:
            parts.append("%d-%d" % (run_start, run_end))

    for day in sorted(by_day):
        if by_day[day]:
            # half-days never join a range - the marker has to stay attached
            flush()
            run_start = run_end = None
            parts.append("%d%s" % (day, HALF))
            continue

        if run_start is not None and day == run_end + 1:
            run_end = day
        else:
            flush()
            run_start = run_end = day

    flush()
    return ", ".join(parts)


def format_ot_cell(hours):
    """D68 - OT renders as a total, e.g. "12.5 h". Blank when there is none."""
    hours = flt(hours)
    if not hours:
        return ""
    text = ("%.2f" % hours).rstrip("0").rstrip(".")
    return "%s h" % text


# ---------------------------------------------------------------------------
# auto-fill helpers (D12 - Finger Log is the only source)
# ---------------------------------------------------------------------------


def get_upl_dates(employee, start_date, end_date):
    """BR8 - days whose Finger Log leave_taken matches a configured code."""
    codes = attendance_leave_codes()
    if not codes:
        return ""

    rows = frappe.get_all(
        "Finger Log",
        filters={
            "employee": employee,
            "docstatus": 1,
            "work_date": ["between", [start_date, end_date]],
            "leave_taken": ["in", codes],
        },
        fields=["work_date", "leave_taken"],
        order_by="work_date asc",
    )
    return format_day_cell(
        (getdate(r.work_date).day, r.leave_taken in HALF_DAY_CODES) for r in rows
    )


def get_late_dates(employee, start_date, end_date):
    """BR9 - days clocked in after the shift start, beyond the grace threshold.

    Known limitation (state it in the user guide): the shift is resolved through
    Employee.default_shift, which is a CURRENT value. Shift Assignment has no
    rows on this system, so there is no historical shift source - a June
    appraisal computed in August uses today's shift. auto_fill_computed_on is
    what makes that auditable.
    """
    shift = frappe.db.get_value("Employee", employee, "default_shift")
    if not shift:
        frappe.log_error(
            title="CAF appraisal: no default shift",
            message="Employee %s has no default_shift; punctuality cell skipped." % employee,
        )
        return ""

    start_time = frappe.db.get_value("Shift Type", shift, "start_time")
    if start_time is None:
        frappe.log_error(
            title="CAF appraisal: shift has no start time",
            message="Shift Type %s (employee %s) has no start_time." % (shift, employee),
        )
        return ""

    threshold = _as_timedelta(start_time) + timedelta(minutes=min_late_minutes())

    rows = frappe.get_all(
        "Finger Log",
        filters={
            "employee": employee,
            "docstatus": 1,
            "work_date": ["between", [start_date, end_date]],
        },
        fields=["work_date", "time_in", "leave_taken"],
        order_by="work_date asc",
    )

    late = []
    for row in rows:
        if row.time_in is None:
            continue
        clock_in = _as_timedelta(row.time_in)
        # 00:00 means the employee never clocked in - an absence, not lateness
        if not clock_in.total_seconds():
            continue
        if clock_in > threshold:
            late.append((getdate(row.work_date).day, False))

    return format_day_cell(late)


def get_ot_hours(employee, start_date, end_date):
    """BR10/D45 - approved OT only. `final_ot`, never `ot_in_hour`.

    A NULL final_ot is summed as 0 AND logged: finger_log's controller always
    assigns a value, so NULL means the row bypassed it (direct SQL, or an import
    that skipped on_submit) and is worth surfacing rather than silently summing.
    """
    rows = frappe.get_all(
        "Finger Log",
        filters={
            "employee": employee,
            "docstatus": 1,
            "work_date": ["between", [start_date, end_date]],
        },
        fields=["name", "final_ot"],
    )

    total = 0.0
    nulls = []
    for row in rows:
        if row.final_ot is None:
            nulls.append(row.name)
            continue
        total += flt(row.final_ot)

    if nulls:
        frappe.log_error(
            title="CAF appraisal: NULL final_ot",
            message=(
                "Employee %s, %s to %s: %d Finger Log rows have a NULL final_ot and were "
                "summed as 0. The controller always assigns a value, so these rows bypassed "
                "it.\n%s" % (employee, start_date, end_date, len(nulls), ", ".join(nulls[:50]))
            ),
        )

    return total


def get_working_days(employee, start_date, end_date):
    """D14/BR8 - the Remarks figure on the Attendance row: days in the period
    that are not in the employee's Holiday List."""
    start_date, end_date = getdate(start_date), getdate(end_date)
    total_days = (end_date - start_date).days + 1

    holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
    if not holiday_list:
        frappe.log_error(
            title="CAF appraisal: no holiday list",
            message="Employee %s has no holiday_list; working days = calendar days." % employee,
        )
        return total_days

    holidays = frappe.get_all(
        "Holiday",
        filters={
            "parent": holiday_list,
            "holiday_date": ["between", [start_date, end_date]],
        },
        pluck="holiday_date",
    )
    return total_days - len(set(holidays))


def _as_timedelta(value):
    """Frappe hands Time fields back as timedelta, time or string depending on
    the path taken. Normalise so comparisons are safe."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, str):
        parts = value.split(":")
        while len(parts) < 3:
            parts.append("0")
        h, m, s = (int(float(p)) for p in parts[:3])
        return timedelta(hours=h, minutes=m, seconds=s)
    return timedelta(hours=value.hour, minutes=value.minute, seconds=value.second)


# ---------------------------------------------------------------------------
# supervisor identity (D55 - a fact derived from the tree, not a role)
# ---------------------------------------------------------------------------


def _workflow_states():
    """The CAF Appraisal Workflow's state rows, or [] when no workflow is
    attached. A missing Workflow fails SILENTLY in Frappe (D72) - it simply
    applies none - so this must not assume one exists."""
    from frappe.model.workflow import get_workflow_name

    name = get_workflow_name("Appraisal")
    if not name:
        return []
    return frappe.get_cached_doc("Workflow", name).states or []


def get_employee_for_user(user=None):
    user = user or frappe.session.user
    return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def is_hr_manager(user=None):
    return "HR Manager" in frappe.get_roles(user or frappe.session.user)


@frappe.whitelist()
def get_direct_reports(employee=None):
    """Employees reporting directly to `employee`. Backs the JS gate (D57) and
    the Q1 employee-field filter."""
    employee = employee or get_employee_for_user()
    if not employee:
        return []
    return frappe.get_all(
        "Employee", filters={"reports_to": employee, "status": "Active"}, pluck="name"
    )


@frappe.whitelist()
def can_create_appraisal():
    """D57 - drives the New-button gate. UX ONLY, never a security barrier:
    any logged-in user can POST to the API directly. The real gates are
    has_permission and the validate() re-check (D56)."""
    if is_hr_manager():
        return {"allowed": True, "reason": "hr_manager"}

    employee = get_employee_for_user()
    if not employee:
        return {"allowed": False, "reason": "no_employee_record"}
    if not get_direct_reports(employee):
        return {"allowed": False, "reason": "no_direct_reports"}
    return {"allowed": True, "reason": "supervisor"}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def employee_query_direct_reports(doctype, txt, searchfield, start, page_len, filters):
    """Q1 - the employee picker offers only the supervisor's direct reports.

    A Link-field query, so it must return rows of (value, description). HR
    Manager never reaches this - the JS gives them an unfiltered query instead.
    """
    supervisor = get_employee_for_user()
    if not supervisor:
        return []

    return frappe.db.sql(
        """
        SELECT name, employee_name
        FROM `tabEmployee`
        WHERE reports_to = %(supervisor)s
          AND status = 'Active'
          AND (name LIKE %(txt)s OR employee_name LIKE %(txt)s)
        ORDER BY employee_name
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "supervisor": supervisor,
            "txt": "%%%s%%" % (txt or ""),
            "start": start,
            "page_len": page_len,
        },
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def cycle_query_not_yet_appraised(doctype, txt, searchfield, start, page_len, filters):
    """Q2 - hide cycles this employee already has an appraisal for.

    Cancelled appraisals (docstatus 2) do not block a new one, matching stock
    validate_duplicate().
    """
    employee = (filters or {}).get("employee")

    return frappe.db.sql(
        """
        SELECT name, CONCAT(start_date, ' to ', end_date)
        FROM `tabAppraisal Cycle`
        WHERE name LIKE %(txt)s
          AND (%(employee)s = '' OR name NOT IN (
                SELECT appraisal_cycle FROM `tabAppraisal`
                WHERE employee = %(employee)s AND docstatus != 2
                  AND appraisal_cycle IS NOT NULL
          ))
        ORDER BY name DESC
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "employee": employee or "",
            "txt": "%%%s%%" % (txt or ""),
            "start": start,
            "page_len": page_len,
        },
    )


def get_visible_employees(user=None):
    """D18/D24 - read visibility is the whole subtree beneath the user's own
    employee record. Reuses frappe.utils.nestedset rather than recreating the
    lft/rgt walk."""
    employee = get_employee_for_user(user)
    if not employee:
        return []
    return get_descendants_of("Employee", employee, ignore_permissions=True) or []


def may_appraise(employee, user=None):
    """BR3 - the write rule. HR Manager may appraise anyone; everyone else only
    their own direct reports."""
    if is_hr_manager(user):
        return True

    supervisor = get_employee_for_user(user)
    if not supervisor or not employee:
        return False
    return frappe.db.get_value("Employee", employee, "reports_to") == supervisor


# ---------------------------------------------------------------------------
# hooks.py entry points - module-level functions, not controller methods
# ---------------------------------------------------------------------------


def has_permission(doc, ptype=None, user=None, **kwargs):
    """Write/read layer, per document (D18/D56). Registered under the
    `has_permission` hook, which frappe.permissions:450 calls from
    check_permission() - i.e. BEFORE validate and before the DB write."""
    user = user or frappe.session.user
    if user == "Administrator" or is_hr_manager(user):
        return True

    employee = getattr(doc, "employee", None)
    if not employee:
        return True  # nothing to judge yet; validate() will still gate it

    if ptype in ("read", "print", "email", "share", "select"):
        # read is the subtree (D18): C sees A and B; A sees B only; A never sees C
        return employee in (get_visible_employees(user) or [])

    return may_appraise(employee, user)


def get_permission_query_conditions(user=None):
    """Read layer / list filtering (D18). Returns a SQL fragment."""
    user = user or frappe.session.user
    if user == "Administrator" or is_hr_manager(user):
        return ""

    visible = get_visible_employees(user)
    if not visible:
        # A leaf employee supervises nobody. Returning an empty IN () would be a
        # SQL syntax error, so emit a condition that is simply always false
        # (test T-D6).
        return "1=0"

    quoted = ", ".join(frappe.db.escape(name) for name in visible)
    return "`tabAppraisal`.`employee` in ({0})".format(quoted)


# ---------------------------------------------------------------------------
# the controller
# ---------------------------------------------------------------------------


class CustomAppraisal(Appraisal):
    def validate(self):
        # --- stock sequence, with the scoring block gated by the CAF toggle ---
        self.set_kra_evaluation_method()

        from hrms.hr.doctype.appraisal_cycle.appraisal_cycle import validate_active_appraisal_cycle
        from hrms.hr.utils import validate_active_employee

        validate_active_employee(self.employee)
        validate_active_appraisal_cycle(self.appraisal_cycle)
        self.validate_duplicate()

        # --- CAF ---
        self.validate_state_edit_permission()
        self.validate_supervisor()
        self.set_reported_by()
        self.build_grid_from_template()
        self.refresh_auto_fill(force=False)

        if scoring_enabled():
            # D2/DR2: both weightage throw-sites, or the toggle leaks -
            # validate_total_weightage() here, and calculate_total_score()
            # reached via set_goal_score().
            self.validate_total_weightage("appraisal_kra", "KRAs")
            self.validate_total_weightage("self_ratings", "Self Ratings")
            self.set_goal_score()
            self.calculate_self_appraisal_score()
            self.calculate_avg_feedback_score()
            if self.appraisal_cycle:
                # stock calculate_final_score() calls get_cached_doc on the cycle
                # unconditionally (appraisal.py:189) and blows up without one
                self.calculate_final_score()

    def on_update(self):
        """The workflow calls the ordinary document methods - there is no
        special path (4.13.1 step 5), so CAF logic hangs off the state change."""
        if self.has_value_changed("workflow_state"):
            if self.workflow_state == "Pending HR Review":
                self.validate_month_ended()
                self.refresh_auto_fill(force=True)

    def on_submit(self):
        # BR6/D31 - gates SUBMIT, not create. Drafts for month M may exist at any
        # time; this is what stops one being finalised before M has ended.
        self.validate_month_ended()

    # -- CAF rules ---------------------------------------------------------

    def validate_supervisor(self):
        """The second of the two gates (D56).

        has_permission fires from check_permission() before validate, but
        ignore_permissions=True skips it while STILL running validate - so this
        is what protects against CAF's own scripts and background jobs. It is
        not redundant with the hook.
        """
        if self.flags.caf_skip_supervisor_check:
            return
        if not self.employee:
            return
        if may_appraise(self.employee):
            return

        frappe.throw(
            _("You may only appraise employees who report directly to you. {0} does not.").format(
                frappe.bold(self.employee_name or self.employee)
            ),
            frappe.PermissionError,
        )

    def validate_state_edit_permission(self):
        """Enforce the workflow's `allow_edit` ON THE SERVER.

        ⚠️ Frappe does not do this. Despite validate_workflow()'s docstring
        ("Check if user is allowed to edit in current state",
        frappe/model/workflow.py:169), that function only validates the
        TRANSITION - it never reads allow_edit. The field is consumed purely in
        JavaScript: frappe/public/js/frappe/model/workflow.js:48,64
        (get_document_state_roles / is_read_only) feed form.js:412, which sets
        the desk form read-only and shows a banner. Grep confirms no Python
        reference outside the doctype definition and the workflow builder.

        So without this method the "Pending HR Review" lock exists only in the
        browser: a PUT to /api/resource/Appraisal/<name> edits a document that
        is supposedly locked for HR review. Verified live (test T-A5).

        This is the same principle as D56/D57 - JS is never a security barrier.
        """
        if self.is_new() or frappe.session.user == "Administrator":
            return
        if self.flags.caf_skip_supervisor_check:
            return
        # BR3 - HR Manager may act on any appraisal at any point
        if is_hr_manager():
            return

        before = self.get_doc_before_save()
        if not before:
            return

        current_state = before.get("workflow_state")
        if not current_state:
            return

        # A state CHANGE is a transition, not an edit. get_transitions() and
        # has_approval_access() already police those (4.13.1 steps 1-2).
        if self.workflow_state != current_state:
            return

        allow_edit = None
        for row in _workflow_states():
            if row.state == current_state:
                allow_edit = row.allow_edit
                break

        if not allow_edit or allow_edit in frappe.get_roles():
            return

        frappe.throw(
            _(
                "This appraisal is in the <b>{0}</b> state and can only be edited by "
                "<b>{1}</b>. It has been submitted for HR review - ask HR to reject it back "
                "to Draft if it needs changing."
            ).format(current_state, allow_edit),
            frappe.PermissionError,
            title=_("Locked for review"),
        )

    def set_reported_by(self):
        if not self.reported_by:
            self.reported_by = get_employee_for_user()

    def validate_month_ended(self):
        """BR6 - the cycle's month must be over before the appraisal is final."""
        if not self.appraisal_cycle:
            return
        end_date = frappe.db.get_value("Appraisal Cycle", self.appraisal_cycle, "end_date")
        if not end_date:
            return
        if getdate(nowdate()) <= getdate(end_date):
            frappe.throw(
                _(
                    "Appraisal cycle {0} ends on {1}. It cannot be submitted for review until "
                    "the period is over - the attendance and overtime data would be incomplete."
                ).format(self.appraisal_cycle, end_date)
            )

    def build_grid_from_template(self):
        """Populate the KRA grid server-side.

        Stock set_kras_and_rating_criteria() is a @frappe.whitelist() method
        called from the desk form - it is NOT part of validate(). So an Appraisal
        created through the API with a template set gets ZERO Appraisal KRA rows,
        and validate_total_weightage() passes happily on an empty table: it fails
        silently, leaving a saved appraisal with no grid. Verified on this site
        during the chunk 1 build.
        """
        if self.get("appraisal_kra") or self.get("goals"):
            return
        if not self.appraisal_template:
            return
        self.set_kras_and_rating_criteria()

    @frappe.whitelist()
    def set_kras_and_rating_criteria(self):
        """Guard the stock wipe (plan 4.1).

        NOTE the decorator: stock carries @frappe.whitelist() and the desk form
        calls this by name. An override that omits it silently un-whitelists the
        method, so "apply template" from the form fails with "Function ... is not
        whitelisted" - which looks like the guard working but is not.

        Stock opens with self.set("appraisal_kra", []) and rebuilds from the
        template - destroying whatever the supervisor typed into the CAF text
        columns. Refuse loudly rather than merging silently: a quiet
        data-preserving merge hides the mistake.
        """
        if self.has_caf_text():
            frappe.throw(
                _(
                    "This appraisal already has text in the CAF columns. Re-applying the "
                    "template would erase it. Clear the Description / Root Cause / Corrective "
                    "Action / Remarks cells first if you really want to rebuild the grid."
                ),
                title=_("Template not re-applied"),
            )
        return super().set_kras_and_rating_criteria()

    def has_caf_text(self):
        fields = ("caf_description", "caf_root_cause", "caf_corrective_action", "caf_remarks")
        for row in self.get("appraisal_kra") or []:
            if any((row.get(f) or "").strip() for f in fields):
                return True
        return False

    # -- auto-fill ---------------------------------------------------------

    def get_cycle_period(self):
        if not self.appraisal_cycle:
            return None, None
        cycle = frappe.db.get_value(
            "Appraisal Cycle", self.appraisal_cycle, ["start_date", "end_date"], as_dict=True
        )
        if not cycle:
            return None, None
        return cycle.start_date, cycle.end_date

    def refresh_auto_fill(self, force=False):
        """D3 - authoritative recomputation. Every save recomputes, so the
        stored document always matches the data at save time, stamped in
        auto_fill_computed_on.

        `force=False` only fills cells that are still empty, so a supervisor's
        manual edit is not overwritten on an unrelated save.
        """
        if not self.employee or not self.get("appraisal_kra"):
            return

        start_date, end_date = self.get_cycle_period()
        if not start_date or not end_date:
            return

        # BR6/T-F3 - refuse to compute a month that has not finished. Reporting a
        # partial month as if it were final is worse than reporting nothing.
        if getdate(nowdate()) <= getdate(end_date):
            return

        values = {
            KRA_ATTENDANCE: get_upl_dates(self.employee, start_date, end_date),
            KRA_PUNCTUALITY: get_late_dates(self.employee, start_date, end_date),
            KRA_OT_HOURS: format_ot_cell(get_ot_hours(self.employee, start_date, end_date)),
        }
        working_days = get_working_days(self.employee, start_date, end_date)

        touched = False
        for row in self.appraisal_kra:
            if row.kra not in AUTO_FILLED_KRAS:
                continue
            if force or not (row.caf_date_cell or "").strip():
                row.caf_date_cell = values[row.kra]
                touched = True
            if row.kra == KRA_ATTENDANCE and (force or not (row.caf_remarks or "").strip()):
                row.caf_remarks = _("{0} working days").format(working_days)
                touched = True

        if touched:
            self.auto_fill_computed_on = now()

    @frappe.whitelist()
    def refresh_auto_fill_action(self):
        """The form's "Refresh Data" button (Q4). Recomputes unconditionally."""
        self.refresh_auto_fill(force=True)
        self.save()
        return {
            "computed_on": self.auto_fill_computed_on,
            "rows": {r.kra: r.caf_date_cell for r in self.appraisal_kra},
        }

    # -- D52 ---------------------------------------------------------------

    def set_employees(self):
        """Not used by Appraisal itself - kept for symmetry with the cycle
        override below, which is where the org-root filter actually matters."""
        return super().set_employees()


# ---------------------------------------------------------------------------
# yearly cycle creation (D39 / 4.9) - a plain whitelisted module function, so
# no controller override is needed on any settings doctype
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_monthly_cycles(year, company=None):
    """Create the 12 monthly cycles for `year`. Idempotent - months that
    already have a cycle are skipped, so re-running is safe."""
    if not is_hr_manager() and frappe.session.user != "Administrator":
        # DR8 - the list-view button hides itself for non-HR, but the UI is
        # never the barrier
        frappe.throw(_("Only an HR Manager may create appraisal cycles."), frappe.PermissionError)

    year = cint(year)
    if year < 2000 or year > 2100:
        frappe.throw(_("{0} is not a plausible year.").format(year))

    company = company or frappe.defaults.get_user_default("Company") or frappe.db.get_value(
        "Company", {}, "name"
    )

    created, skipped = [], []
    for month in range(1, 13):
        name = "%04d-%02d" % (year, month)
        if frappe.db.exists("Appraisal Cycle", name):
            skipped.append(name)
            continue

        start_date = "%04d-%02d-01" % (year, month)
        end_date = str(get_last_day(start_date))

        cycle = frappe.get_doc(
            {
                "doctype": "Appraisal Cycle",
                "cycle_name": name,
                "start_date": start_date,
                "end_date": end_date,
                "company": company,
                # D63 - excludes feedback and self-appraisal from the final score
                # with no code at all: calculate_final_score() branches on these.
                "calculate_final_score_based_on_formula": 1,
                "final_score_formula": "goal_score",
            }
        )
        cycle.insert()
        created.append(name)

    return {"created": created, "skipped": skipped, "company": company}


DEFAULT_TEMPLATE = "CAF Monthly Appraisal"


def resolve_template(employee):
    """Which Appraisal Template applies to this employee.

    Chunk 2 implements only the fallback. The full resolution order
    (Employee -> Appraisee row -> Designation -> Department default, D10/Phase 4)
    is Chunk 3 work - this exists so the stock cycle-level "Create Appraisals"
    button works at all: it throws "Appraisal Template not found for some
    designations" when nothing resolves, because stock reads
    Designation.appraisal_template, which CAF has never populated.
    """
    designation = frappe.db.get_value("Employee", employee, "designation")
    if designation:
        template = frappe.db.get_value("Designation", designation, "appraisal_template")
        if template:
            return template

    if frappe.db.exists("Appraisal Template", DEFAULT_TEMPLATE):
        return DEFAULT_TEMPLATE
    return None


@frappe.whitelist()
def set_cycle_employees(appraisal_cycle):
    """Fill a cycle's Appraisee table, excluding the org roots (D52).

    Without the filter, stock set_employees() puts both Managing Directors into
    all 12 cycles every year. Nobody can appraise them - they are nobody's direct
    report - so the dashboard completion figure would sit permanently short by
    two and never reach 100%, and it would fail QUIETLY: complete_cycle() counts
    only draft Appraisals, of which there would be none.
    """
    cycle = frappe.get_doc("Appraisal Cycle", appraisal_cycle)
    cycle.set_employees()

    kept = []
    for row in cycle.get("appraisees") or []:
        if frappe.db.get_value("Employee", row.employee, "caf_reports_to_nobody"):
            continue
        kept.append(row)

    excluded = len(cycle.get("appraisees") or []) - len(kept)
    cycle.set("appraisees", [])
    without_template = []
    for row in kept:
        data = row.as_dict()
        if not data.get("appraisal_template"):
            template = resolve_template(data.get("employee"))
            if template:
                data["appraisal_template"] = template
            else:
                without_template.append(data.get("employee"))
        cycle.append("appraisees", data)

    cycle.save()
    return {
        "appraisees": len(kept),
        "org_roots_excluded": excluded,
        "without_template": without_template,
    }
