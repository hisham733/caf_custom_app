// My Attendance — filters and the new-tab OT Approval link. Chunk 7.1.
// =====================================================================
// Purpose : Self-service view of a person's own Finger Log, so the employee can
//           check the resolved shift, day type, work hours and OT against what
//           they actually remember (OD-12 / OD-63).
// Report  : My Attendance (Script Report)  |  ref doctype: Finger Log
//
// ⚠️ NOTHING HERE IS A PERMISSION. The Employee filter below is a convenience for
// HR; the scoping that matters is in `my_attendance.py:execute()`, because a
// Script Report runs its own SQL and neither permission_query_conditions nor a
// hidden column constrains what comes back. Same lesson as workflow allow_edit.
//
// Changelog
// ---------
// 1.0  2026-08-11  Initial — Chunk 7.1

frappe.query_reports["My Attendance"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			// Shown to everyone, honoured only for HR Manager — execute() ignores
			// it for anyone else rather than trusting the client.
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
			depends_on: "eval:frappe.user_roles.includes('HR Manager')",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "ot_approval_id" && value) {
			// MG asked for this to open in a NEW browser tab: the whole point is to
			// check an approval against the row you are looking at, and navigating
			// away loses your place in the list.
			const href = `/app/ot-approval/${encodeURIComponent(value)}`;
			return `<a href="${href}" target="_blank" rel="noopener">${frappe.utils.escape_html(
				value
			)}</a>`;
		}

		// A rest day or a holiday is NOT an absence — greying it makes the
		// distinction obvious at a glance, which is exactly what the employee is
		// being asked to verify. 287 false Absents once hid behind this.
		if (column.fieldname === "day_type" && value && value !== "Workday") {
			return `<span style="color: var(--text-muted)">${frappe.utils.escape_html(
				value
			)}</span>`;
		}

		// Absent is the one status with a consequence: FBR37 counts an unexplained
		// absence toward the appraisal. If any row here is wrong, THIS is the row
		// the employee needs to spot, so it is the only one coloured.
		if (column.fieldname === "status" && value) {
			const colour =
				value === "Absent"
					? "var(--text-danger, #c0392b)"
					: value === "Present"
					? "var(--text-muted)"
					: "";
			return colour
				? `<span style="color: ${colour}">${frappe.utils.escape_html(value)}</span>`
				: frappe.utils.escape_html(value);
		}

		return default_formatter(value, row, column, data);
	},
};
