// The filters. ⭐ `minutes_early` lives HERE and not on HR Settings — MG's call,
// 2026-09-15: the number belongs to the question being asked today, not to the
// site. 60 is the standing weekly scan; drop it to 15 when chasing one person.
frappe.query_reports["Early Clock-In Without Sanction"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
			reqd: 1,
		},
		{
			// 🔴 A WEEK BACK, not today. Production files the OT Approval a median
			// of one day after the work date and 90% within two, so yesterday has
			// no sanction on file yet and is not yet a problem.
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -7),
			reqd: 1,
			description: __(
				"Defaults to a week ago on purpose: approvals are filed a day or " +
				"two after the fact, so recent days would look unsanctioned."
			),
		},
		{
			fieldname: "minutes_early",
			label: __("More than this many minutes early"),
			fieldtype: "Int",
			default: 60,
			description: __(
				"91.7% of days start early by a minute or two. 60 is the level " +
				"at which somebody was probably asked to come in."
			),
		},
		{
			fieldname: "include_sanctioned",
			label: __("Also show the ones that WERE sanctioned"),
			fieldtype: "Check",
			default: 0,
			description: __(
				"Off by default: 44 of 54 early starts already carry an approval " +
				"saying so, and listing them trains you to ignore the report."
			),
		},
	],
};
