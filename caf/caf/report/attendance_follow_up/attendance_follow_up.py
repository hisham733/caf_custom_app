"""Every day still waiting on a human — in one place, always current.

MG's proposal, 2026-09-02: *"currently only visible at the respective Ingress
Import Batch manifest… propose a report for HR Manager that collates all these
blocks."*

🔴 WHY THE MANIFEST CANNOT ANSWER THIS
--------------------------------------
An `Ingress Import Batch` manifest is a **historical record of one run**. Its rows
never change — submit the log a week later and the row still says `Held`. So the
manifest answers *"what happened during that import"* and can never answer
*"what is still outstanding"*, which is the question HR actually has. Verified for
MG on 2026-09-02.

Before this there were **three** partial views and no whole one:

    each batch's manifest      that run's held rows, frozen, found only by opening it
    Finger Log list            filter caf_not_full_day = 1 — no reason, no document
    HR Appraisal Dashboard     caf_hr_review = 1 — collated, but a DIFFERENT set

WHAT THIS COLLECTS, AND WHY BOTH KINDS
--------------------------------------
Two populations, both of which need a person and neither of which the other view
shows:

    HELD     docstatus = 0 — never became a verdict. Incomplete punches, OT with
             no approval, a leave clash. The day is not decided.
    FLAGGED  caf_hr_review = 1 — already SUBMITTED, then a re-resolve found its OT
             no longer matches its approval. The day is decided and now disputed.

They are one question to HR — *"what do I still have to deal with?"* — so they are
one report. The dashboard panel keeps the flagged half as a summary; this is the
worklist.

⚠️ **The reason is derived LIVE, not read from a stored field.** `_missing` is
recomputed from the punches and the shift's `caf_required_punches`, so a day that
stopped being blocked (because HR fixed a punch, or the shift's rule changed —
FBR55) simply leaves the report. A stored reason would go stale exactly when it
mattered.

HR Manager only: Finger Log is restricted to HR Manager and System Manager (D40),
and these rows carry OT figures.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, formatdate, getdate, nowdate

from caf.caf import work_hours
from caf.caf.shift_resolution import get_shift_params


def execute(filters=None):
    frappe.only_for(["HR Manager", "System Manager"])
    filters = frappe._dict(filters or {})
    return _columns(), _rows(filters)


def _columns():
    return [
        # 🔴 The first column, because it splits the list into two different jobs.
        # Without it the report says "566 outstanding" when only ~400 need a
        # decision and the rest need a click — and a worklist that overstates
        # itself is one people stop opening.
        {"label": _("Status"), "fieldname": "status",
         "fieldtype": "Data", "width": 95},
        {"label": _("Work Date"), "fieldname": "work_date",
         "fieldtype": "Date", "width": 95},
        {"label": _("Employee"), "fieldname": "employee_name",
         "fieldtype": "Data", "width": 190},
        {"label": _("Waiting"), "fieldname": "age",
         "fieldtype": "Data", "width": 80},
        # 🔴 ONE column, not two — MG, 2026-09-15: *"two col, why need 2 cols?"*
        # Every reason is concatenated into one sentence, in the order Submit
        # will raise them, and the documents inside it are clickable.
        {"label": _("Why it cannot submit"), "fieldname": "why",
         "fieldtype": "Data", "width": 520},
        # 🔴 The column the manifest cannot give: the document that has to change
        # before this day can move. A Dynamic Link so one column can point at an
        # OT Approval or a Leave Application, whichever is blocking.
        {"label": _("Blocked by"), "fieldname": "blocker",
         "fieldtype": "Dynamic Link", "options": "blocker_type", "width": 175},
        {"label": _("Type"), "fieldname": "blocker_type",
         "fieldtype": "Data", "width": 1, "hidden": 1},
        {"label": _("Finger Log"), "fieldname": "finger_log",
         "fieldtype": "Link", "options": "Finger Log", "width": 150},
        {"label": _("Shift"), "fieldname": "shift_type",
         "fieldtype": "Link", "options": "Shift Type", "width": 150},
        {"label": _("OT (h)"), "fieldname": "ot_in_hour",
         "fieldtype": "Float", "width": 70, "precision": 2},
    ]


def _link(doctype, name):
    """A clickable document inside the sentence — MG, 2026-09-15: *"some text,
    if possible, hyperlinked to the doc.name deemed related to the block."*

    ⚠️ A query report renders a `Data` cell as HTML, so this works here. It does
    NOT work in the submit refusal's plain-text manifest line — see `_reason()`
    on Finger Log, which is why that one keeps the links in COLUMNS instead.
    """
    if not name:
        return ""
    slug = doctype.lower().replace(" ", "-")
    return '<a href="/app/%s/%s">%s</a>' % (slug, name, name)


def _leave_on(employee, day):
    rows = frappe.get_all(
        "Leave Application",
        filters={"employee": employee, "docstatus": 1,
                 "from_date": ("<=", day), "to_date": (">=", day)},
        fields=["name", "leave_type"], limit=1)
    return rows[0] if rows else None


BLOCKED = "🔴 Blocked"
FLAGGED = "🟠 Flagged"
READY = "✅ Ready"


def _roster_gap(log):
    """Is the month this day belongs to still unconfirmed? The fourth guard.

    🔴 This was MISSING from the report entirely until 2026-09-15, and it is the
    third commonest reason a draft cannot submit — measured at **352 of 1,526
    drafts (23.1%)**. HR opened the worklist, saw no reason against a row, fixed
    nothing, pressed Submit and was refused.
    """
    gate_from = frappe.db.get_single_value("HR Settings", "caf_roster_gate_from")
    if not gate_from or getdate(log.work_date) < getdate(gate_from):
        return None                         # the gate does not reach this day
    month = getdate(log.work_date).replace(day=1)
    name = frappe.db.get_value("Monthly Roster Confirmation",
                               {"month_start": month, "docstatus": 1}, "name")
    if name:
        return None
    return (_("{0} roster not confirmed yet").format(
        formatdate(month, "MMMM yyyy")), "Monthly Roster Confirmation", None)


def _reasons(log):
    """EVERY reason this day cannot submit, in the order the guards really fire.

    🔴 REWRITTEN 2026-09-15 — MG asked for a *"why is this blocked"* view, and
    measuring the old one found two faults worth more than the feature:

      1. **It reported only the FIRST reason**, and **366 of 1,526 drafts (24.0%)
         carry more than one.** HR cleared one, pressed Submit, met the next, and
         had no way to know how many were left. Each was a separate visit.
      2. 🔴 **Its order was not the submit order.** It checked punches ➜ leave ➜
         OT; the document checks **OT ➜ punches ➜ leave ➜ roster**, because
         `check_ot_approval` runs in `validate()` and the rest in
         `before_submit()` (`test_guard_order` pins this). So on a day with both
         a missing punch and unapproved OT, the report said *"missing punch"* and
         the submit said *"overtime has no approval"* — two descriptions of one
         row, which is how somebody concludes the system is inconsistent.

    Returns (status, reasons, blocker_type, blocker). `reasons` is ordered; the
    first is what the submit will say, and the rest are what it will say next.

    🔴 The three statuses are three different jobs, and conflating them was the
    first version's mistake:

      Blocked  something must CHANGE before this day can become a verdict
      Flagged  already submitted, and a re-resolve since found its OT disputed
      Ready    nothing is blocking it — it only needs submitting

    `Ready` is not noise: 157 days became submittable the moment the punch-rule
    shifts went in (FBR55), and every one of them is still a draft because
    nothing submits a draft automatically. Measured again 2026-09-15: **123 of
    1,526 drafts have nothing against them at all.**
    """
    params = get_shift_params(log.shift_type)
    reasons, blocker_type, blocker = [], None, None

    # ── 1 ── overtime, judged first because it lives in validate() ────────────
    if log.ot_in_hour:
        row = frappe.get_all(
            "OT Approval Table",
            filters={"emp_id": log.employee, "work_date": log.work_date,
                     "docstatus": 1},
            fields=["parent", "ot_duration"], order_by="creation desc", limit=1)
        if not row:
            reasons.append(_("{0} h of overtime, and no approval")
                           .format(log.ot_in_hour))
        else:
            approved, parent = row[0].ot_duration, row[0].parent
            if log.ot_in_hour > approved:
                # ⚠️ `approved = 0` is real and common: 493 of 45,667 submitted
                # child rows carry ot_duration = 0, nearly all of them
                # `special_approve` filed with start_work == ot_end (FBR92 —
                # that type never runs check_ot_duration, so nothing computes
                # the figure). Saying "only 0.0 h is approved" is truthful but
                # reads like a fault, so the zero case gets its own sentence.
                if not approved:
                    reasons.append(
                        _("{0} h of overtime, but {1} approves none").format(
                            log.ot_in_hour, _link("OT Approval", parent)))
                else:
                    reasons.append(
                        _("{0} h of overtime, but {1} approves only {2} h")
                        .format(log.ot_in_hour, _link("OT Approval", parent),
                                approved))
                blocker_type, blocker = "OT Approval", parent
            elif frappe.db.get_value("OT Approval", parent, "docstatus") != 1:
                reasons.append(_("{0} has not been submitted")
                               .format(_link("OT Approval", parent)))
                blocker_type, blocker = "OT Approval", parent

    # ── 2 ── the punches ──────────────────────────────────────────────────────
    missing = work_hours.missing_punches(log, params)
    if missing:
        # ⭐ The same words the submit refusal uses — see work_hours.PUNCH_LABEL.
        reasons.append(
            _("{0} is missing").format(work_hours.name_punches(missing))
            if len(missing) == 1 else
            _("{0} are missing").format(work_hours.name_punches(missing)))

    # ── 3 ── an approved leave already owns the day ───────────────────────────
    leave = _leave_on(log.employee, log.work_date)
    if leave:
        reasons.append(_("{0} is approved for this day ({1})").format(
            _link("Leave Application", leave.name), leave.leave_type))
        if not blocker:
            blocker_type, blocker = "Leave Application", leave.name

    # ── 4 ── the roster gate, which the report never used to check ────────────
    gap = _roster_gap(log)
    if gap:
        reasons.append(gap[0])
        if not blocker:
            blocker_type = gap[1]

    if reasons:
        return BLOCKED, reasons, blocker_type, blocker

    if log.caf_hr_review:
        return (FLAGGED, [log.caf_hr_review_note or _("flagged for review")],
                "OT Approval", log.ot_approval_id or None)

    return READY, [_("nothing is blocking this — it only needs submitting")], None, None


def _why(log):
    """Back-compatible wrapper: the first reason only."""
    status, reasons, blocker_type, blocker = _reasons(log)
    return status, reasons[0], blocker_type, blocker


def _rows(filters):
    conditions = {"docstatus": ("<", 2)}
    if filters.get("employee"):
        conditions["employee"] = filters.employee

    logs = frappe.get_all(
        "Finger Log",
        filters=conditions,
        or_filters=[["caf_not_full_day", "=", 1], ["caf_hr_review", "=", 1],
                    ["docstatus", "=", 0]],
        fields=["name", "employee", "employee_name", "work_date", "shift_type",
                "day_type", "ot_in_hour", "caf_hr_review", "caf_hr_review_note",
                "caf_not_full_day", "docstatus",
                "time_in", "`break`", "resume", "`out`"],
        order_by="work_date asc",
        limit_page_length=0)

    today = getdate(nowdate())
    out = []
    for log in logs:
        status, reasons, blocker_type, blocker = _reasons(log)
        if filters.get("status") and status != filters.status:
            continue
        days = date_diff(today, getdate(log.work_date))
        out.append({
            "status": status,
            "work_date": log.work_date,
            "employee_name": log.employee_name,
            "age": _("{0} days").format(days) if days else _("today"),
            # ⚠️ Blank when nothing is blocking — MG: *"if there is no block,
            # better just to have a blank field."* An empty cell in a worklist
            # reads as "nothing to do here" faster than any sentence can.
            "why": "" if status == READY else ", then ".join(reasons),
            "blocker": blocker,
            "blocker_type": blocker_type,
            "finger_log": log.name,
            "shift_type": log.shift_type,
            "ot_in_hour": log.ot_in_hour,
        })
    return out
