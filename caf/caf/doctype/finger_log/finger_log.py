# -*- coding: utf-8 -*-
# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
# from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from datetime import datetime

from frappe.utils import getdate, cint, cstr, flt
from caf.caf.shift_resolution import get_shift_params, resolve_day_type
from caf.caf import work_hours
from caf.caf.attendance_verdict import create_attendance, cancel_attendance, assert_no_clash
# Employee Checkin generation is DORMANT — decision F16, analysis §12.8.
# Finger Log writes Attendance directly and nothing reads Employee Checkin.
# See the header of emp_checklist.py for why it is kept and how to re-enable.
# from caf.caf.doctype.finger_log.emp_checklist import make_employee_checkin_from_finger_log

# OD-62 — every field that is DERIVED and carries allow_on_submit = 1, i.e. every
# field a machine writes after submission and a person never should. Measured, not
# listed by hand: these are exactly the allow_on_submit fields on Finger Log, minus
# `caf_hr_review` and `caf_hr_review_note`, which exist for HR to act on.
DERIVED_AFTER_SUBMIT = (
    "shift_type", "day_type", "ot_approval_id", "has_overwrite",
    "final_ot", "caf_work_hours", "ot_in_hour", "short", "caf_not_full_day",
)


def _same(a, b):
    """Compare a stored value with an in-memory one without tripping over types.

    A Float arrives from the DB as Decimal and from Python as float; a Check as
    int; a Data as str or None. Comparing raw would report a change on every save.
    """
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        return flt(a) == flt(b)
    return cstr(a) == cstr(b)


def overtime_to_minutes(overtime):
    # FBR2 — Finger Log.overtime is hour.minute, NOT decimal hours. 1.28 is
    # 1 h 28 min, not 1.28 h. Measured: 0 of 13,243 rows carry a decimal >= 0.6.
    if not overtime:
        return 0
    overtime = float(overtime)
    hours = int(overtime)
    minutes = int(round((overtime - hours) * 100))
    return hours * 60 + minutes


def _link(route, label):
    """A desk hyperlink for a message that will be rendered as HTML.

    MG asked for the person, the day and the approval to be clickable. Frappe
    renders `frappe.throw` / `msgprint` content as HTML, so an anchor works and
    saves the reader a search — which is the whole point of naming them.

    ⚠️ Only for HTML surfaces. Anywhere the text lands in a Data/Small Text field
    shown in a grid — the import manifest's `reason`, for one — the markup is
    escaped and the reader sees the tag. Those surfaces get plain wording and rely
    on their own Link columns instead.
    """
    return f'<a href="{route}">{frappe.utils.escape_html(str(label))}</a>'


TITLE_SEP = " · "


def compose_title(work_date, ftag_id, employee_name):
    """The Finger Log's human-readable identity: `2026-08-03 · 442 · Chen Xiao Natalie`.

    MG asked for the Ingress device id to be visible so a log can be cross-checked
    against the machine at a glance, and the name alongside it for human
    verification. This is the *display*; `name` stays the identifier.

    🔴 Read from `ftag_id`, NOT from `Employee.attendance_device_id`.
    They agree on all 3,167 rows today, but the employee field is **mutable** — a
    re-enrolment on a new reader changes it, and every historical title would then
    claim a device that was not the one Ingress recorded. `ftag_id` is
    `set_only_once` and captured at import, so it is what the machine held ON THE
    DAY. That is the whole reason a title beats putting the device id in `name`
    (FBR67): a display re-reads, an identifier is frozen — so the value that goes
    in the display must still be the historically correct one.

    ⚠️ `name` already LOOKS like this format and is not. `autoname` builds
    `<work_date>-<3-digit daily series>`, so `2026-07-01-232` is the 232nd log of
    that day, not device 232 — and device ids are 3-digit numbers in the same
    range. The title is what removes that ambiguity.
    """
    parts = [
        getdate(work_date).strftime("%Y-%m-%d") if work_date else "????-??-??",
        cstr(ftag_id) or "no device",
        cstr(employee_name) or "?",
    ]
    return TITLE_SEP.join(parts)


def apply_ot_rules(overtime, params):
    # The three per-shift settings, in the order they apply. Kept a module-level
    # function of plain values so it can be tested without a document.
    #
    #   caf_allow_ot        FBR36 / FDR7 — "no OT on this shift" is a flag, never
    #                       a magic threshold. Replaces Ingress' minot = 200
    #   caf_ot_gate_minutes FBR26 — OT below the gate does not count at all.
    #                       Shift ending 17:00 with a 30 min gate: 17:29 -> 0
    #   caf_ot_round_minutes FBR27 — what survives the gate rounds DOWN (FBR1)
    #
    # With gate 30 + rounding 30 this reproduces the old convert_ot_to_hour()
    # exactly, which is the point: no shift changes behaviour on day one.
    if not params or not params.get("caf_allow_ot"):
        return 0.0

    minutes = overtime_to_minutes(overtime)

    if minutes < cint(params.get("caf_ot_gate_minutes")):
        return 0.0

    step = cint(params.get("caf_ot_round_minutes"))
    if step > 0:
        minutes -= minutes % step

    return minutes / 60.0


class FingerLog(Document):
    def before_submit(self):
        # OD-58 — an incomplete punch record may not become a verdict. Measured
        # 2026-08-10: before this guard existed, EVERY incomplete shape saved and
        # submitted freely, because validate() never looked at the punches.
        if self.caf_not_full_day:
            frappe.throw(_(
                "Not a full day: {0} is missing {1}. Correct the punches, or file "
                "half-day leave — a Finger Log may not decide that half a day was worked."
            ).format(self.work_date, ", ".join(getattr(self, "_missing", None) or ["a punch"])))

        # Refuse a day that is already decided, BEFORE the docstatus is written.
        assert_no_clash(self)

    def on_submit(self):
        # make_employee_checkin_from_finger_log(self.name)   # dormant — F16
        create_attendance(self)

    def before_update_after_submit(self):
        """OD-62 — the lock OD-48 claimed but never had.

        OD-48's register row said `read_only = 1` meant *"code may write them and
        a person may not"*. **Measured 2026-08-11: `read_only` does not stop a
        write at all** — it is form decoration, the same shape as workflow
        `allow_edit`. Neither does `hidden`, and `set_only_once` is not even
        checked on child rows. The only field property Frappe truly enforces is
        `permlevel`, and that cannot be made conditional on `docstatus`.

        So these fields were rewritable on a SUBMITTED Finger Log by anyone
        holding `write` AND `submit` — 3 accounts here, and `final_ot` drives
        overtime pay. This is the guard that makes the claim true.

        ⚠️ `caf_hr_review` / `caf_hr_review_note` are deliberately NOT guarded:
        they exist for a human to act on, so HR keeps a route to clear a flag
        they have dealt with.

        The sanctioned route for genuinely wrong DATA is unchanged and is what
        OD-48 already specified: **cancel + amend** (Path 2).
        """
        if self.flags.caf_system_write:
            return
        before = self.get_doc_before_save()
        if not before:
            return
        changed = [f for f in DERIVED_AFTER_SUBMIT
                   if not _same(before.get(f), self.get(f))]
        if not changed:
            return
        frappe.throw(
            _(
                "{0} is derived from the punches and the shift, and this log is already "
                "submitted. {1} cannot be typed. If the DATA is wrong, cancel and amend "
                "the log (OD-48 Path 2); if the SHIFT was wrong, file a Shift Assignment "
                "and the day re-resolves itself."
            ).format(frappe.bold(", ".join(changed)),
                     _("They") if len(changed) > 1 else _("It")),
            title=_("Derived field"),
        )

    def on_cancel(self):
        # Now that Attendance links back here, stock REFUSES the cancel while a
        # submitted document points at this one (frappe/model/delete_doc.py:334
        # — the Work Order / Stock Entry behaviour). on_cancel alone is too late:
        # the link guard runs first. ignore_links + cancel the CHILD first is the
        # pattern ERPNext itself uses. Spec §6.3.
        self.flags.ignore_links = True
        cancel_attendance(self)
    def autoname(self):
        # set FingerLog Name to work_date + getseries
        # work_date arrives as a str, a datetime, or a plain date. The original
        # test was `isinstance(self.work_date, datetime)`, which is False for a
        # date — so `date + '-'` raised TypeError on every row the importer
        # created. getdate() normalises all three.
        date_str = getdate(self.work_date).strftime('%Y-%m-%d')
        key = date_str
        self.name = key + '-' + getseries(key, 3)

    def validate(self):
        # D-6 (2026-08-15) - `employee` is now a Link, but `employee_name`
        # carries a fetch_from companion, which makes Frappe silently SKIP the
        # does-it-exist check for the Link (the EPF `reviewer` quirk). Validate
        # explicitly: the importer must fail loudly on a bad name, never store
        # junk.
        if self.employee and not frappe.db.exists("Employee", self.employee):
            frappe.throw(_("Employee {0} does not exist").format(self.employee))

        # OUTSIDE the docstatus guard below on purpose. The title is the doctype's
        # `title_field`, so it must exist on a draft as well as a submitted log —
        # and its three inputs are all set_only_once, so recomputing costs nothing
        # and can never disagree with itself.
        self.caf_title = compose_title(self.work_date, self.ftag_id, self.employee_name)
        # (debug prints removed 2026-08-10 — the importer creates thousands of
        # rows per run and three lines each buried the actual result)
        # if FingerLog record is NOT submitted, then execute the following
        if self.docstatus != 1:
            # print("\n", self.__dict__)
            
            # if already submitted a Finger Log for the same date, then raise an exception
            if self.check_previous_submission():
                frappe.throw(_("Employee {0} already submitted a Finger Log for this date").format(self.employee))

            # what kind of day was this, and on which shift. MUST run before
            # det_ot_in_hour() — the OT rules are read off the resolved shift.
            self.resolve_shift_and_day_type()

            # hours served, and whether the record is even complete. Also shift-
            # derived, so it has the same ordering requirement.
            self.det_work_hours()

            # apply the resolved shift's OT rules to the clocked overtime
            self.det_ot_in_hour()

        if self.docstatus == 1:
            # if FingerLog has overtime, call check_ot_approval function
            if self.ot_in_hour > 0:
                self.check_ot_approval()


    def resolve_shift_and_day_type(self):
        # OD-45 option A: the shift comes from a Shift Assignment covering the
        # date, else Employee.default_shift. Ingress plays no part.
        # OD-52: a Saturday swap files a Shift Assignment per employee, so the
        # day type MUST come from the shift that applies on the date — reading
        # the employee's own default would miss the swap entirely.
        day_type, shift = resolve_day_type(self.employee, self.work_date)

        # E1 — refuse loudly rather than guessing a shift. An employee with
        # neither an assignment nor a default has no rules to be judged by.
        if not shift:
            frappe.throw(_("Employee {0} has no shift on {1}: no Shift Assignment covers the date and no default shift is set").format(
                self.employee, self.work_date))

        self.shift_type = shift
        self.day_type = day_type

    def det_work_hours(self):
        # OD-59 — derived here, NOT imported from Ingress. `work` is the part of
        # the scheduled shift actually served; anything outside the window is
        # overtime. See work_hours.py for why elapsed time is the wrong formula.
        params = get_shift_params(self.shift_type)
        self._missing = work_hours.missing_punches(self, params)

        # OD-58 — "Not Full Day". The name is deliberate: it records only what
        # was observed. Claiming he worked half a day is a DECISION, and FDR4
        # keeps decisions with the Leave Application.
        self.caf_not_full_day = 1 if self._missing else 0

        work, short = work_hours.compute(
            self.time_in, self.get("break"), self.resume, self.out, params)

        if work is None and work_hours.is_all_zero(self):
            # He did not come. On a Workday he missed the whole scheduled shift,
            # so `short` is the full net — that is what makes the day countable.
            # On a Restday or Holiday nothing was scheduled, so nothing is short.
            self.caf_work_hours = 0
            self.short = round(work_hours.net_minutes(params) / 60.0, 4) \
                if self.day_type == "Workday" else 0
        elif work is None and work_hours.is_single_punch_shift(params):
            # 🔴 "In OR Out only" — MG, 2026-08-22. One tap on a scheduled day
            # credits the FULL contracted day.
            #
            # `compute()` cannot help here: it needs both ends and returns None,
            # and the branch below would then store 0 hours and 0 short — a WRONG
            # number replacing a missing one, which flows straight into the
            # appraisal. So the rule is stated explicitly instead.
            #
            # This is an ASSUMPTION, not a measurement, and that is precisely why
            # `overrides/shift_type.py` forbids overtime on such a shift: crediting
            # a whole day from one tap is defensible for salaried staff whose hours
            # are not really measured; paying overtime on top of it would not be.
            self.caf_work_hours = round(work_hours.net_minutes(params) / 60.0, 4) \
                if self.day_type == "Workday" else 0
            self.short = 0
        else:
            # Not computable and not all-zero = an incomplete record. Leave both
            # at 0 rather than inventing a number; caf_not_full_day carries the
            # meaning and HR resolves it (OD-58).
            self.caf_work_hours = work or 0
            self.short = short if short is not None else 0

    def det_ot_in_hour(self):
        # The OT rules are per-SHIFT (FBR36 / FDR7), never per-department. The
        # retired FBR5 department list and the hardcoded noOT_shift() = ["4"]
        # were deleted in Chunk 2b — framework §3.
        self.ot_in_hour = apply_ot_rules(self.overtime, get_shift_params(self.shift_type))


    # check_previous_submission is a function that check if the employee has already submitted a Finger Log for the same date
    def check_previous_submission(self):
        # Search for Finger Log records
        flogList = frappe.get_all('Finger Log',
                                  filters={
                                      "employee": self.employee,
                                      "work_date": self.work_date,
                                      "docstatus": 1
                                  },
                                  # get name of Finger Log record
                                  fields=['name'],
                                  # order by creation date in descending order
                                  order_by='creation desc'
                                  )
        if not flogList:
            # if no Finger Log records found, then return False
            return False

        # if Finger Log records > 0, then return True
        return True



    def _who(self):
        """The person as HR knows them, never the docname — and clickable.

        FBR61 — the ID-vs-name family. Every message below used to say
        `HR-EMP-00052`, which is the one identifier the supervisor reading it
        does not have.

        MG, 2026-09-01: *"emp.name is good, but name with hyperlink even
        better."* ⚠️ These render as links only where the message is shown as
        HTML — `frappe.throw`/`msgprint` dialogs. In the import manifest the
        reason is a plain-text grid cell, so the markup would be escaped: there,
        the links are the COLUMNS (`employee_name`, `finger_log`), which is why
        the manifest wording is kept short. See `_reason()`.
        """
        return _link(f"/app/employee/{self.employee}",
                     self.employee_name or self.employee)

    def _day(self):
        """The work date, linked to this log — MG asked for it.

        The date IS this document's own `work_date`, so the link goes to the
        Finger Log. On a refusal at submit the reader is already looking at it;
        the link matters when the same wording is reused elsewhere.
        """
        if self.name and not self.is_new():
            return _link(f"/app/finger-log/{self.name}", self.work_date)
        return f"<b>{self.work_date}</b>"

    def check_ot_approval(self):
        """Does a submitted OT Approval cover this day's overtime? FBR11.

        🔴 MESSAGES REWRITTEN 2026-09-01, MG's manual-test finding: *"the OT
        message does not name the blocking OT Approval."* They said things like
        `"No OT Approval records found, HR-EMP-00052"` — an employee id, no date,
        no hours, no document, and nothing about what to do. The supervisor who
        hits this at 6pm has to go and work all of that out.

        Every refusal now names **the person, the date, the hours, the document
        and the next step**, because this is the one guard that stands between a
        clocked hour and an unapproved payment.
        """
        rows = frappe.get_all(
            "OT Approval Table",
            filters={"emp_id": self.employee, "work_date": self.work_date,
                     "docstatus": 1},
            fields=["name", "parent", "ot_end", "ot_duration"],
            order_by="creation desc")

        if not rows:
            frappe.throw(
                _("{0} has <b>{1} h</b> of overtime on {2}, and no submitted "
                  "<b>OT Approval</b> covers that day."
                  "<br><br>Ask the department representative to file one for "
                  "{3} and submit it, then submit this log again."
                  "<br><br>The clocked hours are safe — this log stays a draft "
                  "until the approval exists, and nothing is lost."
                  ).format(self._who(), self.ot_in_hour, self._day(),
                           self.work_date),
                title=_("Overtime has no approval"))

        ot_child = rows[0]
        parent = frappe.db.get_value(
            "OT Approval", ot_child["parent"],
            ["name", "type", "docstatus", "work_date"], as_dict=True)

        if not parent:
            frappe.throw(
                _("The OT Approval <b>{0}</b> that covers {1} on {2} no longer "
                  "exists, although its row is still there. This is a data "
                  "problem, not a decision — tell whoever maintains the system."
                  ).format(ot_child["parent"], self._who(), self.work_date),
                title=_("OT Approval is missing"))

        # 🔴 The parent's own `work_date` is deliberately NOT compared. Measured
        # 2026-09-01: **77 submitted child rows carry a work_date that differs
        # from their parent's header**, and genuine multi-date approvals exist
        # (one document covering two dates). The header date is the day the
        # approval was RAISED; the row's date is the day being approved, and the
        # row is already matched on it above.
        #
        # This line previously read:
        #
        #     if parent["work_date"] != self.work_date and parent["docstatus"] != 1:
        #
        # — an `and` where only the second half is a real condition, so it could
        # never fire. ⚠️ And "fixing" it to `or` would have been far worse than
        # leaving it: it would have refused all 77 of those legitimate rows.
        if parent.docstatus != 1:
            frappe.throw(
                _("OT Approval {0} is <b>{1}</b>, so it cannot authorise the "
                  "overtime {2} worked on {3}."
                  "<br><br>Submit that approval, or file a new one for the day."
                  ).format(_link(f"/app/ot-approval/{parent.name}", parent.name),
                           {0: _("still a draft"), 2: _("cancelled")}.get(
                               parent.docstatus, _("not submitted")),
                           self._who(), self._day()),
                title=_("OT Approval is not submitted"))

        if parent.type == "normal" and self.ot_in_hour <= ot_child["ot_duration"]:
            self.ot_approval_id = parent.name
            self.final_ot = self.ot_in_hour

        elif parent.type == "normal":
            frappe.throw(
                _("{0} clocked <b>{1} h</b> of overtime on {2}, but OT Approval "
                  "{3} approved <b>{4} h</b>."
                  "<br><br>Either the approval needs to cover the hours actually "
                  "worked — amend {3}, or file a <b>special approval</b> for the "
                  "day — or the punches are wrong and should be corrected in "
                  "Ingress."
                  "<br><br>Until then this log stays a draft and nothing is paid."
                  ).format(self._who(), self.ot_in_hour, self._day(),
                           _link(f"/app/ot-approval/{parent.name}", parent.name),
                           ot_child["ot_duration"]),
                title=_("More overtime than was approved"))

        elif parent.type == "special_approve":
            self.ot_approval_id = parent.name
            self.final_ot = ot_child["ot_duration"]
            self.has_overwrite = 1