// Attendance Follow-Up — the filters HR actually uses.
//
// `status` is first because the list splits into two different jobs: Blocked
// needs a decision, Ready needs a click. Defaulting to nothing shows both, with
// the status column making the split obvious at a glance.

frappe.query_reports["Attendance Follow-Up"] = {
	filters: [
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "🔴 Blocked", "🟠 Flagged", "✅ Ready"].join("\n"),
			default: "",
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
			get_query: () => ({ filters: { status: "Active" } }),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Colour the status so a long list reads at a glance rather than by
		// being read. Blocked is the one that costs somebody money if ignored.
		if (column.fieldname === "status" && data) {
			if (data.status && data.status.indexOf("Blocked") !== -1)
				value = `<span style="color:var(--red-600)">${value}</span>`;
			else if (data.status && data.status.indexOf("Ready") !== -1)
				value = `<span style="color:var(--green-600)">${value}</span>`;
		}
		return value;
	},
};
