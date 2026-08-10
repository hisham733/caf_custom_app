# -*- coding: utf-8 -*-
# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
# from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from datetime import datetime

from frappe.utils import getdate, cint
from caf.caf.shift_resolution import get_shift_params, resolve_day_type
from caf.caf import work_hours
from caf.caf.attendance_verdict import create_attendance, cancel_attendance, assert_no_clash
# Employee Checkin generation is DORMANT — decision F16, analysis §12.8.
# Finger Log writes Attendance directly and nothing reads Employee Checkin.
# See the header of emp_checklist.py for why it is kept and how to re-enable.
# from caf.caf.doctype.finger_log.emp_checklist import make_employee_checkin_from_finger_log

def overtime_to_minutes(overtime):
    # FBR2 — Finger Log.overtime is hour.minute, NOT decimal hours. 1.28 is
    # 1 h 28 min, not 1.28 h. Measured: 0 of 13,243 rows carry a decimal >= 0.6.
    if not overtime:
        return 0
    overtime = float(overtime)
    hours = int(overtime)
    minutes = int(round((overtime - hours) * 100))
    return hours * 60 + minutes


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
        # debug
        # print("\n", self.__dict__)
        # print("\n", self.work_date)
        # print(key)
        print(self.name)
        

    def validate(self):
        print("\n", "Finger Log validate")
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
        print("flogList: ",flogList)
        if not flogList:
            # if no Finger Log records found, then return False
            return False

        # if Finger Log records > 0, then return True
        return True



    def check_ot_approval(self):
        # debug
        # print(self.__dict__)  # Print the attributes of self
        # print(self.ot_in_hour)  # Print the value of ot_in_hour

        # Search for OT Approval Table records (child table)
        ot_childList = frappe.get_all('OT Approval Table',
                                        filters={
                                            "emp_id": self.employee,
                                            "work_date": self.work_date,
                                            "docstatus": 1
                                        },
                                        # get name of child record + parent of child record + ot_end
                                        fields=['name', 'parent',
                                                'ot_end', 'ot_duration'],
                                        # order by creation date in descending order
                                        order_by='creation desc'
                                        )

        if not ot_childList:
            # if FLog has no OT Approval records found in the child table, then raise an exception
            frappe.throw(_("No OT Approval records found, {0}").format(self.employee))
        # debug
        print(len(ot_childList))
        print(ot_childList)

        # if OT Approval Table records > 0, then set ot_childList to the first record. First record = most recent record
        ot_child = ot_childList[0]

        # Fetch additional details from OT Approval record (parent table)
        parent_details = frappe.get_all('OT Approval',
                                        filters={
                                            "name": ot_child['parent']
                                        },
                                        # get fields from parent table
                                        fields=["name", "type",
                                                "docstatus", "work_date"],
                                        # order by creation date in descending order
                                        order_by='creation desc'
                                        )

        if not parent_details:
            # if parent_details is empty (no approval), then raise an exception
            frappe.throw(_("No OT Approval found,{0}").format(self.employee))
        
        parent = parent_details[0]

        # if parent work_date is not equal to FLog work_date and docstatus is not submitted, then raise an exception
        if parent["work_date"] != self.work_date and parent["docstatus"] != 1:
            frappe.throw(_("OT Approval for {0} has issue").format(self.employee))

        # verifying logic between OT Approval and Finger Log
        # 1. Submit - has overtime, has approval, and overtime duration <= approved OT. final_ot = FLog overtime
        if parent["type"] == "normal" and self.ot_in_hour <= ot_child['ot_duration']:
            self.ot_approval_id = parent["name"]
            self.final_ot = self.ot_in_hour
        # 2. Reject - has overtime, has approval, but overtime duration > approved OT
        elif parent["type"] == "normal" and self.ot_in_hour > ot_child['ot_duration']:
            frappe.throw(_("{0} OT duration is greater than approved OT").format(self.employee))
        # 3. Submit - has overtime and with special_approve. final_ot = overtime duration stated in OT Approval record (child). Could be = 0 or > 0
        elif parent["type"] == "special_approve":
            self.ot_approval_id = parent["name"]
            self.final_ot = ot_child['ot_duration']
            self.has_overwrite = 1