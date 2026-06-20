from pydoc import doc
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from datetime import datetime

from frappe.utils import getdate

@frappe.whitelist()
def make_employee_checkin_from_finger_log( doc,target_doc=None, ignore_permissions=False):
      """
      Map data from a Finger Log document to create two Employee Checkin records (IN and OUT).
      """
      finger_log_name = doc
      finger_log_doc = frappe.get_doc("Finger Log", finger_log_name)

      # Function to create an Employee Checkin record
      def create_checkin_record(log_type, checkin_time):
            checkin_doc = frappe.new_doc("Employee Checkin")
            checkin_doc.employee = finger_log_doc.employee
            checkin_doc.time = datetime.combine(getdate(finger_log_doc.work_date), (datetime.min + checkin_time).time())
            checkin_doc.log_type = log_type
            checkin_doc.device_id = finger_log_doc.ftag_id
            checkin_doc.flags.ignore_permissions = ignore_permissions
            checkin_doc.insert(ignore_permissions=ignore_permissions)
            print(f"{log_type} Checkin created: {checkin_doc.name}")
            return checkin_doc

      try:
            # Create IN record
            if hasattr(finger_log_doc, "out"):
                  in_checkin = create_checkin_record("IN", finger_log_doc.time_in)

            # Create OUT record
            if hasattr(finger_log_doc, "out"):
                  out_checkin = create_checkin_record("OUT", finger_log_doc.out)

            frappe.msgprint("Employee Checkins (IN & OUT) created successfully.", alert=True)
            return {"IN": in_checkin.name, "OUT": out_checkin.name if finger_log_doc.out else None}

      except Exception as e:
            print("Error in make_employee_checkin_from_finger_log:", e)
            frappe.throw(f"An error occurred while creating Employee Checkins: {e}")
