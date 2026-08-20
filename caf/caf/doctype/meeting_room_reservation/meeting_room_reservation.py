import re

import frappe
from erpnext.setup.doctype.holiday_list.holiday_list import is_holiday
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, get_datetime, getdate, now_datetime


class MeetingRoomReservation(Document):
	def validate(self):
		if self.docstatus == 0:
			self.status = "Draft"
		self.validate_booking_type()
		self.validate_dates()
		self.validate_party()
		self.validate_purpose()
		self.validate_backdated()
		self.validate_holiday()
		self.validate_availability()
		self.validate_employee_active()
		self.validate_room_active()
		self.validate_no_dual_party()

	def on_submit(self):
		self.status = "Booked"
		frappe.db.set_value("Meeting Room Reservation", self.name, "status", "Booked")

	def on_cancel(self):
		self.status = "Cancelled"
		frappe.db.set_value("Meeting Room Reservation", self.name, "status", "Cancelled")

	def validate_booking_type(self):
		if not self.booking_type:
			frappe.throw(_("Booking Type is mandatory."))

	def _validate_time_format(self, value, label):
		if not re.match(r"^\d{1,2}:\d{2}$", (value or "").strip()):
			frappe.throw(_("{0} must be in HH:MM format.").format(label))

	def _starts_dt(self):
		return get_datetime(f"{self.starts_on} {(self.starts_time or '').strip()}:00")

	def _ends_dt(self):
		return get_datetime(f"{self.ends_on} {(self.ends_time or '').strip()}:00")

	def validate_dates(self):
		if not self.starts_on or not self.starts_time or not self.ends_on or not self.ends_time:
			frappe.throw(_("Starts On, Starts Time, Ends On and Ends Time are mandatory."))
		self._validate_time_format(self.starts_time, self.meta.get_label("starts_time"))
		self._validate_time_format(self.ends_time, self.meta.get_label("ends_time"))
		if self._ends_dt() <= self._starts_dt():
			frappe.throw(_("End time must be later than start time."))

	def validate_party(self):
		if self.booking_type == "Internal" and not self.employee:
			frappe.throw(_("Staff is required when Booking Type is Internal."))
		if self.booking_type == "External" and not self.visitor_name:
			frappe.throw(_("Guest / Company is required when Booking Type is External."))

	def validate_employee_active(self):
		if self.booking_type == "Internal" and self.employee:
			status = frappe.db.get_value("Employee", self.employee, "status")
			if status != "Active":
				frappe.throw(
					_("Cannot book for employee {0} because employee status is {1}.").format(
						self.employee, status
					)
				)

	def validate_room_active(self):
		if self.room and frappe.db.get_value("Room", self.room, "status") == "Inactive":
			frappe.throw(_("Room {0} is not active.").format(self.room))

	def validate_no_dual_party(self):
		if self.employee and self.visitor_name:
			frappe.throw(_("Select either Internal or External, not both."))

	def validate_purpose(self):
		if not self.purpose:
			frappe.throw(_("Purpose is mandatory."))

	def validate_backdated(self):
		if self._starts_dt() < now_datetime():
			frappe.throw(_("Cannot book a room for a past time."))

	def validate_holiday(self):
		if not self.room:
			return
		holiday_list = frappe.db.get_value("Room", self.room, "holiday_list")
		if not holiday_list:
			return
		days = date_diff(getdate(self.ends_on), getdate(self.starts_on)) + 1
		for i in range(days):
			d = add_days(getdate(self.starts_on), i)
			if is_holiday(holiday_list, d):
				frappe.throw(_("Room cannot be booked on a holiday ({0}).").format(d))

	def validate_availability(self):
		if (
			not self.room
			or not self.starts_on
			or not self.starts_time
			or not self.ends_on
			or not self.ends_time
		):
			return
		starts_dt = self._starts_dt()
		ends_dt = self._ends_dt()
		overlap = frappe.db.sql(
			"""
			select name from `tabMeeting Room Reservation`
			where room = %s and docstatus = 1
				and name != %s
				and %s < TIMESTAMP(ends_on, ends_time)
				and TIMESTAMP(starts_on, starts_time) < %s
			for update
			""",
			(self.room, self.name or "", starts_dt, ends_dt),
			as_list=True,
		)
		if overlap:
			frappe.throw(_("This room is already booked for the selected time."))
