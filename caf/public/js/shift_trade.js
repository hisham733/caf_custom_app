// The "Trade a Saturday" dialog — shared. Chunk 7.3 (OD-65), extracted in 7.5.
// =============================================================================
// It was born on the Shift Assignment list view and lived there as three
// top-level functions. Chunk 7.5's roster page needs the SAME dialog: a grid
// cell is the most natural place to start a trade from, because HR is looking
// at the wrong Saturday when they decide to fix it.
//
// Two copies of a dialog that files documents is the kind of duplication that
// drifts silently — one gets a validation the other does not. So it moved here,
// under `caf.shift_trade`, and both callers open the same one.
//
// ⚠️ NOTHING HERE IS A PERMISSION. Callers hide the entry point from non-HR for
// tidiness; the enforcement is `frappe.only_for` in `caf/caf/shift_swap.py` plus
// the Custom DocPerm that gives only HR Manager create/write/submit/cancel.
// Hiding a button is not a lock (PROTOCOL §C4).
//
// The dialog PREVIEWS before it files, because HR should see which way the day
// moves — and whether the operation is a swap or a one-way cover — before
// agreeing to it.
//
// Changelog
// ---------
// 1.1  2026-08-12  Extracted from shift_assignment_list.js; `open()` now takes
//                  optional defaults so a grid cell can pre-fill it (7.5, OD-72)
// 1.0  2026-08-12  Initial — Chunk 7.3

frappe.provide("caf.shift_trade");

caf.shift_trade = {
	/**
	 * @param {Object} [defaults]           pre-fill, e.g. from a clicked grid cell
	 * @param {string} [defaults.work_date]
	 * @param {string} [defaults.employee_a]
	 * @param {string} [defaults.employee_b]
	 * @param {Function} [on_filed]         called after a successful file
	 */
	open(defaults, on_filed) {
		defaults = defaults || {};

		const d = new frappe.ui.Dialog({
			title: __("Trade a Saturday"),
			fields: [
				{
					fieldname: "work_date",
					label: __("Date"),
					fieldtype: "Date",
					reqd: 1,
					default: defaults.work_date || null,
				},
				{
					fieldname: "employee_a",
					label: __("Employee"),
					fieldtype: "Link",
					options: "Employee",
					reqd: 1,
					default: defaults.employee_a || null,
					get_query: () => ({ filters: { status: "Active" } }),
				},
				{
					fieldname: "employee_b",
					label: __("Traded with"),
					fieldtype: "Link",
					options: "Employee",
					default: defaults.employee_b || null,
					description: __("Leave empty to simply move one person to a different shift for the day."),
					get_query: () => ({ filters: { status: "Active" } }),
				},
				{
					// Only meaningful for the single-person case; for a trade the two
					// shifts are derived from the pair, which is what "swap" means.
					fieldname: "shift",
					label: __("Shift for the day"),
					fieldtype: "Link",
					options: "Shift Type",
					depends_on: "eval:!doc.employee_b",
				},
				{ fieldtype: "Section Break" },
				{ fieldname: "preview", fieldtype: "HTML" },
			],
			primary_action_label: __("Preview"),
			primary_action(values) {
				frappe.call({
					method: "caf.caf.shift_swap.plan",
					args: {
						work_date: values.work_date,
						employee_a: values.employee_a,
						employee_b: values.employee_b || null,
					},
				}).then((r) => {
					const plan = r && r.message;
					if (!plan) return;
					d.fields_dict.preview.$wrapper.html(caf.shift_trade.render_plan(plan));
					d.set_primary_action(__("File it"), () => caf.shift_trade.file(d, values, on_filed));
				});
			},
		});
		d.show();
		return d;
	},

	render_plan(plan) {
		const esc = frappe.utils.escape_html;
		const line = (side) =>
			`<tr>
				<td>${esc(side.employee_name)}</td>
				<td>${esc(side.day_now)} &middot; ${esc(side.shift_now)}</td>
				<td>${side.shift_new
					? `&rarr; <b>${esc(side.shift_new)}</b>`
					: `<span class="text-muted">${__("no change")}</span>`}</td>
			</tr>`;

		// A cover is NOT a swap and the dialog says so in words, not just in a
		// label. If HR reads "swap" they will believe the day was given back.
		const banner = {
			Swap: `<div class="text-muted">${__("Both people move. {0} works the day and {1} rests it.", [
				esc(plan.a.employee_name), esc((plan.b || {}).employee_name || ""),
			])}</div>`,
			Cover: `<div class="alert alert-warning p-2">${__("One-way.")} ${esc(plan.note || "")}</div>`,
			Single: `<div class="text-muted">${__("One person, one day, no pairing.")}</div>`,
		}[plan.kind] || "";

		return `
			<h6>${esc(plan.kind)} &mdash; ${esc(plan.work_date)}</h6>
			${banner}
			<table class="table table-sm mt-2">
				<thead><tr><th>${__("Who")}</th><th>${__("Today")}</th><th>${__("After")}</th></tr></thead>
				<tbody>${line(plan.a)}${plan.b ? line(plan.b) : ""}</tbody>
			</table>`;
	},

	file(dialog, values, on_filed) {
		frappe.call({
			method: "caf.caf.shift_swap.create",
			args: {
				work_date: values.work_date,
				employee_a: values.employee_a,
				employee_b: values.employee_b || null,
				shift: values.shift || null,
			},
			freeze: true,
			freeze_message: __("Filing both assignments..."),
		}).then((r) => {
			const res = r && r.message;
			if (!res) return;
			dialog.hide();
			frappe.show_alert({
				message: __("{0} filed: {1}", [res.kind, res.created.join(", ")]),
				indicator: "green",
			});
			if (on_filed) {
				on_filed(res);
			} else if (window.cur_list) {
				cur_list.refresh();
			}
		});
	},

	/** HR Manager or System Manager. Tidiness only — see the header. */
	may_file() {
		return frappe.user_roles.includes("HR Manager")
			|| frappe.user_roles.includes("System Manager");
	},
};
