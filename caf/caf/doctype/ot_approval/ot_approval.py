
# -*- coding: utf-8 -*-
# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
# import frappe
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from datetime import datetime

from caf.caf.shift_resolution import get_shift_for_date, get_shift_params

class OTApproval(Document):
    def autoname(self):
        # note that self.work_date is a string. Example: '2021-01-01'
        date_str = self.work_date
        key = "OT-" + date_str
        self.name = 'OT-' + date_str + '-' + getseries(key, 3)
        # debug
        # print("\n", self.__dict__)
        # print("\n", self.work_date)
        # print(key)
        print("name =", self.name)
    

    def sync_child_work_dates(self):
        """🔴 Copy the header date onto every row, SERVER-SIDE. MG, 2026-09-01.

        **The intended invariant is that a row's `work_date` equals the header's**
        — `ot_approval.js` says so in as many words (*"Batch Sync: Force child
        table dates to match parent"*) and MG confirmed it is the design.

        It was enforced **only in JavaScript**, which means it held for the desk
        form and nowhere else. Measured 2026-09-01:

          · every OT Approval created by a PERSON (`production1@`) has row date ==
            header date — the invariant does hold in practice;
          · all **77** rows where they differ, and all **4** approvals spanning
            more than one date, were created by `Administrator` in a single import
            on 2026-08-08. Legacy data, not a workflow.

        ⚠️ **The consequence of the JS-only version is worse than an untidy date.**
        `check_ot_approval()` matches rows on `work_date = <the log's date>`, so an
        approval created by API, Data Import or `bench execute` gets **blank** row
        dates, matches nothing, and the employee's overtime is refused as *"no
        approval"* — while an approval sits there, submitted, looking correct.
        This is the trap the dev protocol has warned about since 2026-08-04.

        Kept alongside the JS rather than replacing it: the form still updates the
        rows as the user types, which is visible feedback. This is the guarantee.
        """
        if not self.work_date:
            frappe.throw(_("Fill in the <b>Work Date</b> before saving — every "
                           "row is approved against it."),
                         title=_("Work Date is required"))

        from frappe.utils import getdate, nowdate
        if getdate(self.work_date) > getdate(nowdate()):
            frappe.throw(
                _("<b>{0}</b> is in the future. Overtime is approved for a day "
                  "that has been worked, or is being worked today — not for one "
                  "that has not happened.").format(self.work_date),
                title=_("Work Date is in the future"))

        for row in self.emp_list:
            if str(row.work_date or "") != str(self.work_date):
                row.work_date = self.work_date

    def guard_special_approve(self):
        """🔴 `special_approve` is the FINAL ARBITER, so it is the one type that
        needs a role. MG, 2026-09-02.

        A **normal** approval is deliberately open to the `Employee` role, and
        that is a business rule, not an oversight (FBR70): department reps file
        OT for their area, the reps rotate often, and CAF chose a wide create +
        submit over a role that would have to be reassigned every rotation. The
        controls are that `Employee` holds **no cancel, no delete and no amend**,
        and that `owner` names whoever filed it.

        ⚠️ **`special_approve` is a different instrument and those controls do not
        reach it.** It does not merely add an approval — `validate()` runs a raw
        `UPDATE tabOT Approval Table SET docstatus = 2` over every *other*
        submitted row for the same (employee, work date), and `check_ot_approval`
        then takes its figure verbatim with `has_overwrite = 1`. So it silently
        overrides an existing approval **without cancelling the document that
        holds it** — and cancel is exactly the permission `Employee` does not
        have. Left open, the one lock on the type is bypassed by the other type.

        Restricted to **HR Manager + Leave Approver** (MG's choice). `Leave
        Approver` is the closest thing CAF has to a supervisor role — 19 holders,
        already the authority for leave (OD-82) — so this needs no new role.
        """
        if self.type != "special_approve":
            return
        # ⚠️ `only_for` returns early for Administrator AND for flags.in_test
        # (quirks #33). That is wanted here — the importer and the fixtures run
        # as Administrator — but it means a suite must use `frappe.set_user`.
        frappe.only_for(("HR Manager", "Leave Approver", "System Manager"))

    def validate(self):
        # Server-side, and OUTSIDE the `docstatus == 0` guard below: an amendment
        # or a resubmit must not be able to leave a row pointing at a different
        # day from the document approving it.
        self.sync_child_work_dates()

        # Before anything else: a special approval that the caller may not file
        # should be refused before it starts cancelling other people's rows.
        self.guard_special_approve()

        if self.docstatus == 0:
            # print("\n", self.__dict__)

            # CHECK ONE -  if there is any duplicated emp_id within the same OT Approval Table
            self.has_duplicated_emp_id()

            # CHECK TWO - if the same emp_id and work_date already exists in OT Approval Table
            # CHECK THREE - if ot_duration is enter correctly and in multiple of 0.5
            if self.type == "normal":
                self.has_previous_submission()
                self.check_ot_duration()

            # if special, cancel child with same work_date and emp_id, for all previous submission (both normal and special)
            if self.type == "special_approve":
                # if other submitted OT Approval (parent) has the same (work_date and emp_id) child row, then cancel this child row that belong to other OT Approval Table entries
                for row in self.emp_list:
                    print(self.name, row.work_date, row.emp_id)
                    frappe.db.sql("""UPDATE `tabOT Approval Table` SET docstatus = 2 WHERE parent != %s AND docstatus = 1 AND work_date = %s AND emp_id = %s""", (self.name, row.work_date, row.emp_id))
                # D-13 hygiene 1 (2026-08-15): the db.commit() here was removed.
                # Committing inside validate persisted the sibling-row
                # cancellation even when THIS document later failed to save or
                # submit - a partial commit. Without it the update rolls back
                # with the transaction, and an aborted special_approve leaves
                # the previous approvals untouched.



    def before_update_after_submit(self):
        # D-13 hygiene 2 (2026-08-15) - a submitted approval's child rows must
        # not change. `emp_list` carries allow_on_submit = 1 (the schema lets
        # the edit through), so this is the lock - the OD-62 shape. The
        # correction route is cancel + file a new approval.
        before = self.get_doc_before_save()
        if not before:
            return
        before_rows = {(r.name, r.emp_id, r.work_date, r.start_work, r.ot_end, r.ot_duration)
                       for r in before.emp_list}
        after_rows = {(r.name, r.emp_id, r.work_date, r.start_work, r.ot_end, r.ot_duration)
                      for r in self.emp_list}
        if before_rows != after_rows:
            frappe.throw(_("OT Approval {0} is submitted. Its employee rows cannot be "
                           "changed - cancel it and file a new approval.").format(self.name),
                         title=_("Submitted approval"))

    def on_cancel(self):
        # D-13 (2026-08-15) - the lifecycle was FROZEN: a submitted Finger Log
        # holding this name in ot_approval_id made stock refuse the cancel
        # (LinkExistsError). The Finger Log pattern: ignore_links, then cascade
        # - zero the linked logs' OT figures, flag them for HR, and refresh the
        # appraisals whose FBR39 window is still open.
        self.flags.ignore_links = True
        # if OT Approval is cancelled, then cancel all OT Approval Table entries with the same name
        frappe.db.sql("""UPDATE `tabOT Approval Table` SET docstatus = 2 WHERE parent = %s""", self.name)
        for row in self.emp_list:
            self._cascade_cancel(row.emp_id, row.work_date)
        frappe.db.commit()

    def _cascade_cancel(self, emp_id, work_date):
        logs = frappe.get_all("Finger Log",
                              filters={"employee": emp_id, "work_date": work_date,
                                       "docstatus": 1, "ot_approval_id": self.name},
                              fields=["name"])
        for lg in logs:
            doc = frappe.get_doc("Finger Log", lg.name)
            doc.flags.ignore_permissions = True
            # OD-62: the machine writing the derived fields - the one marker
            # FingerLog.before_update_after_submit lets past.
            doc.flags.caf_system_write = True
            doc.final_ot = 0
            doc.ot_approval_id = ""
            doc.caf_hr_review = 1
            doc.caf_hr_review_note = _("OT Approval {0} was cancelled - re-file the approval and amend this log").format(self.name)
            doc.save(ignore_permissions=True)
            doc.add_comment("Comment", _("OT Approval {0} cancelled: final_ot zeroed and flagged for HR (D-13).").format(self.name))

        # D-13 - refresh the appraisals this day touches, but ONLY those whose
        # FBR39 window is still open. A settled appraisal stays final (MG).
        from caf.caf.appraisal_refresh import refresh_for
        refresh_for(emp_id, work_date, work_date,
                    reason=_("OT Approval {0} was cancelled").format(self.name),
                    trigger=("OT Approval", self.name),
                    within_window=True)



    def has_previous_submission(self):
        # self.emp_list is a list of entries (object) within OT Approval
        for row in self.emp_list:
            # Query the OTApprovalTable for any entries with the same emp_id
            existing_entry = frappe.db.exists('OT Approval Table', 
                                                {'emp_id': row.emp_id,
                                                'work_date': row.work_date,
                                                "docstatus": 1}
                                            )
            if existing_entry:
                # if existing_entry is not None, then return True
                frappe.throw(_("There is duplicated {0} in other OT Approval form").format(row.emp_id))
                return True
        return False

    # there should be no duplicate of the same emp_id among rows in OT Approval table
    def has_duplicated_emp_id(self):
        list_emp_id = set()
        for row in self.emp_list:
            if row.emp_id in list_emp_id:
                frappe.throw(_("Duplicate {0} in OT Approval Table").format(row.emp_id))
                return True
            list_emp_id.add(row.emp_id)
        return False

    # to check correctness of ot_duration, which is mannually entered by user
    # ot_duration should be = ot_end (hh:mm:ss) - start_work (hh:mm:ss)
    # ot_duration should be = 0 or multiple of 0.5
    def check_ot_duration(self):
        for row in self.emp_list:
            # convert ot_end and start_work to seconds
            OTEnd = self.convert_to_seconds(row.ot_end)
            StartWork = self.convert_to_seconds(row.start_work)
            # cross-midnight: if OT end is before start, assume next day
            if OTEnd < StartWork:
                OTEnd += 86400
            # calculate OTDuration in seconds
            OTDuration = OTEnd - StartWork
            # convert OTDuration to hours. Example: 3600 seconds = 1 hour
            # get_work_hours returns the number of work hours per day, based on work_date and shift_type
            OTDuration = (OTDuration / 3600) - self.get_work_hours(row.emp_id)
            # convert OTDuration to multiple of 0.5
            OTDuration = self.convertTo_nearest(OTDuration)

            # debug
            # print("\n", "OTApproval.check_ot_duration")
            # print(OTEnd - StartWork, OTEnd, StartWork)
            print("Compare Cal vs Manual entry", OTDuration, row.ot_duration)
            frappe.msgprint(f"Employee {row.emp_id} worked from {row.start_work} to {row.ot_end}.")
            frappe.msgprint(f"Total work duration (hours): {OTDuration + self.get_work_hours(row.emp_id)}")
            frappe.msgprint(f"Regular work hours: {self.get_work_hours(row.emp_id)}")
            frappe.msgprint(f"Calculated OT Duration: {OTDuration}, Manually entered OT Duration: {row.ot_duration}")


            # if OTDuration is not equal to ot_duration, then it means that ot_duration is not manually entered correctly
            if OTDuration != row.ot_duration:
                frappe.throw(_("The OT Duration for Employee {0} is incorrect. The correct OT Duration should be {1}.")
                             .format(row.emp_id, OTDuration))
        return True


    # det work_hours per day based on
    # 1. if work_date is within holiday_list, then work_hours = 1
    # 2. if work_date is not within holiday_list, then work_hours depends on Employee's shift_type
    def get_work_hours(self, VarEmpID):
        # Debugging statements
        print("\n", "OTApproval.get_work_hours")
        print(self.work_date, VarEmpID)

        # ⚠️ FIXED in Chunk 2b. This used to be a dict keyed on the OLD numeric
        # shift names ("1".."8") with the hours written in by hand, plus a
        # special case for shift "4" = "no OT". Chunk 0 renamed every Shift Type
        # to its Ingress name, so the lookup missed on EVERY employee and no OT
        # Approval could be created at all — which, via FBR11, made every Finger
        # Log carrying OT unsubmittable.
        #
        # The hours now come from the shift itself (FDR7 — never encode intent
        # as a magic number), and "no OT" is `caf_allow_ot`, the same flag
        # det_ot_in_hour() reads. end - start reproduces the old table exactly
        # where it mattered: 08:00-16:30 = 8.5, 08:00-17:00 = 9.

        # Convert work_date to a datetime object if it's not already
        work_date = self.work_date
        if isinstance(work_date, str):
            try:
                work_date = datetime.strptime(work_date, "%Y-%m-%d")
            except ValueError:
                frappe.throw(_("Invalid date format for work_date. Expected 'YYYY-MM-DD'."))

        # Check if the work_date is a Sunday (weekday 6 in Python's weekday system)
        if work_date.weekday() == 6:  # 6 represents Sunday
            return 1  # Treat as a holiday and return 1

        # The shift that applies on the OT date — a Shift Assignment covering it
        # wins over the employee's default (OD-45), the same resolution the
        # Finger Log uses. Approving OT against the wrong shift would gate it by
        # the wrong rules.
        shift = get_shift_for_date(VarEmpID, self.work_date)
        if not shift:
            frappe.throw(_("Employee {0} has no shift on {1}").format(VarEmpID, self.work_date))

        params = get_shift_params(shift)

        # FBR36 / FDR7 — eligibility is a flag on the shift, not a magic number
        if not params.get("caf_allow_ot"):
            frappe.throw(_("Employee {0} cannot have OT: shift {1} does not allow it").format(
                VarEmpID, shift))

        if params.get("start_time") is None or params.get("end_time") is None:
            frappe.throw(_("Shift {0} has no start or end time").format(shift))

        return (params.end_time - params.start_time).total_seconds() / 3600


    def convert_to_seconds(self, time_str):
        parts = time_str.split(':')
        if len(parts) != 3:
            frappe.throw(_("Start Work or OT End is not in HH:MM:SS format"))
        h, m, s = parts
        s = int(float(s))
        return int(h) * 3600 + int(m) * 60 + s

    def convertTo_nearest(self, floatNum):
        # this function converts floatNum to multiple of 0.5
         # example 2: 0.49 = 0
        # example 3: 0.5 = 0.5
        # example 4: 0.612 = 1
        # example 5: 2.01 = 2
        # example 6: 2.50 = 2.5
        # example 7: 2.999 = 2.5
        # example 8: 3.0108 = 3
        # example 9: 3.50 = 3.5
        # example 10: 3.79 = 3.5
        # example 11: 0.25 = 0
        # example 12: 0.50 = 0.5
        # example 13: 0.51 = 1
        decimal_part = floatNum % 1
        if decimal_part < 0.5:
            return int(floatNum)
        elif 0.5 <= decimal_part < 1:
            return int(floatNum) + 0.5