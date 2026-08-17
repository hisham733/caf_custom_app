// Finger Log calendar view — fix session 2026-08-15, D-7 / D-5.
// Auto-loaded by frappe (desk/form/meta.py: <doctype>_calendar.js).
//
// Each box = one Finger Log doc. The events (title with in/out/lunch, DRAFT /
// SUBMITTED label, pink when the joined Attendance verdict is Absent) come from
// the whitelisted method caf.caf.finger_log_scope.get_employee_events — scoped
// server-side to the caller's own rows (AC-1), never by a client filter.
frappe.views.calendar["Finger Log"] = {
	get_events_method: "caf.caf.finger_log_scope.get_employee_events",
	field_map: {
		start: "start",
		end: "end",
		id: "name",
		title: "title",
		allDay: "allDay",
	},
};
