// Who Is Off — filters and the Stage rendering. Chunk 7.4.
// =========================================================
// Purpose : Who is out and until when (everybody), and where an application is
//           stuck (spec §5 / OD-30).
// Report  : Who Is Off (Script Report)  |  ref doctype: Leave Application
//
// ⚠️ NOTHING HERE IS A PERMISSION. `leave_type` is withheld in
// `who_is_off.py:execute()` by never being put on the row — not by being hidden
// here. A Script Report runs its own SQL, so the server side is the only side.
//
// Changelog
// ---------
// 1.0  2026-08-11  Initial — Chunk 7.4

frappe.query_reports["Who Is Off"] = {
	filters: [
		{
			// Defaults to today .. +30 days: the board's first question is "who is
			// out", which is about now and the near future, not about history.
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), 30),
			reqd: 1,
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			// The second question, in one click.
			fieldname: "pending_only",
			label: __("Pending only"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		// Somebody who is off RIGHT NOW is the headline of a who-is-off board, and
		// on a 30-day window they are a minority of the rows. Bold, not coloured —
		// colour is reserved below for the thing that needs action.
		if (column.fieldname === "employee_name" && data) {
			const today = frappe.datetime.get_today();
			if (data.from_date <= today && data.to_date >= today) {
				return `<b>${frappe.utils.escape_html(value || "")}</b>`;
			}
		}

		if (column.fieldname === "stage" && value) {
			// `Open` is the one value with something outstanding: somebody is waiting
			// on an approver. Everything else has already been decided.
			const pending = value === "Open";
			// 🔴 The fallback made visible. No Workflow is attached to Leave
			// Application yet (Chunk 6 / OD-27), so `workflow_state` is empty on all
			// 775 rows and this value came from `status` instead. Saying so on hover
			// is the difference between a provisional column and a lie: `Open` covers
			// all four pending states at once, which is the very thing OD-30 exists
			// to fix.
			const title = data && data.stage_from_status
				? __("From status — no leave workflow is configured yet, so the four pending states cannot be told apart (Chunk 6)")
				: "";
			const style = pending ? "color: var(--text-warning, #b8860b)" : "";
			return `<span style="${style}" title="${frappe.utils.escape_html(title)}">${
				frappe.utils.escape_html(value)
			}${data && data.stage_from_status ? " *" : ""}</span>`;
		}

		return default_formatter(value, row, column, data);
	},
};
