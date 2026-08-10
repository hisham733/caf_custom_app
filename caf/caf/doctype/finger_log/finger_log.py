# -*- coding: utf-8 -*-
# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
# from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from datetime import datetime

from frappe.utils import getdate
# Employee Checkin generation is DORMANT — decision F16, analysis §12.8.
# Finger Log writes Attendance directly and nothing reads Employee Checkin.
# See the header of emp_checklist.py for why it is kept and how to re-enable.
# from caf.caf.doctype.finger_log.emp_checklist import make_employee_checkin_from_finger_log

class FingerLog(Document):
    def on_submit(self):
        # make_employee_checkin_from_finger_log(self.name)   # dormant — F16
        pass
    def autoname(self):
        # set FingerLog Name to work_date + getseries
        # note that self.work_date can be a datetime object (2021-01-01 00:00:00) or a string (2021-01-01)
        if isinstance(self.work_date, datetime):  # Corrected line
            date_str = self.work_date.strftime('%Y-%m-%d')
        else:
            date_str = self.work_date
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

            # convert FLog overtime to ot_in_hour (multiple of 0.5) if conditions are met
            self.det_ot_in_hour()

        if self.docstatus == 1:
            # if FingerLog has overtime, call check_ot_approval function
            if self.ot_in_hour > 0:
                self.check_ot_approval()


    def det_ot_in_hour(self):
        # debug
        # print("\n", "self.noOT_dept()", self.noOT_dept())
        # print("self.noOT_shift()", self.noOT_shift())

        # condition where althought FLog has overtime, but ot_in_hour will be set to 0
        # condition 1 - if employee's department is in the list of departments
        # condition 2 - if employee's shift is in the list of "no overtime" shifts
        if self.noOT_dept() or self.noOT_shift():
            self.ot_in_hour = 0
        # if conditions not met, then convert FLog overtime to ot_in_hour
        else:
            self.ot_in_hour = self.convert_ot_to_hour()

    def noOT_shift(self):
        # define list of "no OT shifts"
        skip_ot_approval_shift = ["4"]
        # check employee's shift
        emp_shift = frappe.get_value("Employee", self.employee, "default_shift")
        # if emp_shift is undefined, then raise an exception
        if not emp_shift:
            frappe.throw(_("Employee {0} Shift is undefined").format(self.employee))
        
        # debug
        # print(emp_shift)

        # if employee's shift is in the list of "no OT shifts"
        if emp_shift in skip_ot_approval_shift:
            return True
        return False

    def noOT_dept(self):
        # define list of departments that has "no OT"
        skip_ot_approval_dept = ["Management - CAF", "Delivery - CAF"]
        # check employee's department
        emp_dept = frappe.get_value("Employee", self.employee, "department")
        # if emp_dept is undefined, then raise an exception
        if not emp_dept:
            frappe.throw(_("Employee {0} Department is undefined").format(self.employee))

        # debug
        # print(emp_dept)
        
        # if employee's department is in the list of departments
        if emp_dept in skip_ot_approval_dept:
            return True
        return False

    def convert_ot_to_hour(self):
        # this function converts FLog overtime (hour.min) to multiple of 0.5
         # example 2: 1.28 = 1
        # example 3: 1.31 = 1.5
        # example 4: 1.59 = 1.5
        # example 5: 2.01 = 2
        # example 6: 2.30 = 2.5
        # example 7: 2.59 = 2.5
        decimal_part = round(self.overtime % 1, 3)  # round to 3 decimal places
        if decimal_part < 0.3:
            print("1", decimal_part)
            return int(self.overtime)
        elif decimal_part < 0.6:
            print("2", decimal_part)
            return int(self.overtime) + 0.5
        else:
            print("3", decimal_part)
            return int(self.overtime) + 1
    

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