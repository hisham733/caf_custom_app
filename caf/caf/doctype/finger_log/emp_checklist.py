"""Employee Checkin generation — DORMANT. Decision F16, analysis §12.8.

Under the current framework Employee Checkin is NOT needed and is NOT generated:
Finger Log writes `Attendance` directly, and nothing reads Employee Checkin.
The call in `finger_log.py:on_submit` is commented out, not deleted, and the
existing rows are left untouched.

WHY IT IS KEPT rather than removed — four things would need it:
  * Payroll `payment_days` computed from real attendance
  * stock late-entry / early-exit flags (`mark_attendance_and_link_log`)
  * the HRMS mobile app check-in/out (the PWA writes Employee Checkin directly)
  * an audit of raw punch timestamps in ERPNext (Finger Log holds the summary)

TO RE-ENABLE: uncomment the import and the call in `finger_log.py:on_submit`.
⚠️ BUT FIRST: re-enabling makes this a SECOND producer of `Attendance`, so the
"one computer, one answer" rule (analysis §12.1) has to be re-decided before it
is switched back on.
"""

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

      🔴 Role guard added 2026-08-17. Dormant is not the same as harmless: this is
      still `@frappe.whitelist()`, so before this line ANY logged-in employee could
      call it over REST and mint Employee Checkin rows against ANY Finger Log —
      the same shape of hole found in `ingress.sync.manual_import` the same day
      (whitelisted + writes + `ignore_permissions` + no role check).

      Impact was low only because nothing currently reads Employee Checkin. That
      is a fact about today's wiring, not a permission, and the module docstring
      above says re-enabling makes this a SECOND producer of `Attendance` — at
      which point an unguarded endpoint would be writing attendance facts.
      """
      frappe.only_for(("HR Manager", "System Manager"))

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
