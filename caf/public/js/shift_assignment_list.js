// Shift Assignment list — "Trade a Saturday". Chunk 7.3, OD-65.
// ==============================================================
// A trade is TWO Shift Assignments, one per employee. Filed by hand, one gets
// forgotten and Mr A works the Saturday while Mr B is still rostered for it,
// silently. This files both, or neither.
//
// ⚠️ NOTHING HERE IS A PERMISSION. The button is hidden from non-HR for tidiness;
// the enforcement is `frappe.only_for` in `caf/caf/shift_swap.py` plus the Custom
// DocPerm that gives only HR Manager create/write/submit/cancel. Hiding a button
// is not a lock (PROTOCOL §C4).
//
// The dialog PREVIEWS before it files, because HR should see which way the day
// moves — and whether the operation is a swap or a one-way cover — before
// agreeing to it.
//
// Changelog
// ---------
// 1.0  2026-08-12  Initial — Chunk 7.3

frappe.listview_settings["Shift Assignment"] = {
	onload(listview) {
		if (!frappe.user_roles.includes("HR Manager") && !frappe.user_roles.includes("System Manager")) {
			return;
		}

		listview.page.add_inner_button(__("Trade a Saturday"), () => caf_trade_dialog());
	},
};

function caf_trade_dialog() {
	const d = new frappe.ui.Dialog({
		title: __("Trade a Saturday"),
		fields: [
			{
				fieldname: "work_date",
				label: __("Date"),
				fieldtype: "Date",
				reqd: 1,
			},
			{
				fieldname: "employee_a",
				label: __("Employee"),
				fieldtype: "Link",
				options: "Employee",
				reqd: 1,
				get_query: () => ({ filters: { status: "Active" } }),
			},
			{
				fieldname: "employee_b",
				label: __("Traded with"),
				fieldtype: "Link",
				options: "Employee",
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
				d.fields_dict.preview.$wrapper.html(caf_render_plan(plan));
				d.set_primary_action(__("File it"), () => caf_file_trade(d, values));
			});
		},
	});
	d.show();
}

function caf_render_plan(plan) {
	const esc = frappe.utils.escape_html;
	const line = (side) =>
		`<tr>
			<td>${esc(side.employee_name)}</td>
			<td>${esc(side.day_now)} &middot; ${esc(side.shift_now)}</td>
			<td>${side.shift_new
				? `&rarr; <b>${esc(side.shift_new)}</b>`
				: `<span class="text-muted">${__("no change")}</span>`}</td>
		</tr>`;

	// A cover is NOT a swap and the dialog says so in words, not just in a label.
	// If HR reads "swap" they will believe the day was given back.
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
}

function caf_file_trade(dialog, values) {
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
		cur_list && cur_list.refresh();
	});
}
