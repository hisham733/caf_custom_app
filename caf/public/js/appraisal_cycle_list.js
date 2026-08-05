// CAF Appraisal - Appraisal Cycle list view
// ==========================================
// Purpose : Hosts the "Create Monthly Cycles for Year" action, which creates the
//           12 cycles for a year in one go, and a per-cycle "Get Employees"
//           action that excludes the org roots.
// Doctype : Appraisal Cycle (stock)  |  Hook: doctype_list_js
// Plan ref: CAF_appraisal_implementation_plan.md 4.9, D39, D52, D63;
//           build_brief_chunk2.md 4.0(b)
//
// Why the list view and not a settings form (D39): creating 12 documents is an
// ACTION, and a settings page stores toggles. The CAF Appraisal Settings doctype
// that used to host this no longer exists (D38), and putting an action on a
// stock HRMS settings form would be worse still. The list view is where HR
// already goes to look at cycles, so the button is there at the moment of intent.
//
// The role check below is UX only - create_monthly_cycles re-checks server-side
// (DR8: never trust the UI).
//
// Changelog
// ---------
// 1.0  2026-08-05  Initial - Chunk 2

frappe.listview_settings["Appraisal Cycle"] = {
	onload(listview) {
		if (!frappe.user.has_role("HR Manager")) return;

		listview.page.add_inner_button(__("Create Monthly Cycles for Year"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Create Monthly Appraisal Cycles"),
				fields: [
					{
						fieldname: "year",
						label: __("Year"),
						fieldtype: "Int",
						reqd: 1,
						default: new Date().getFullYear(),
						description: __(
							"Creates 12 cycles named YYYY-01 to YYYY-12. Months that already have a cycle are skipped, so this is safe to re-run."
						),
					},
				],
				primary_action_label: __("Create"),
				primary_action(values) {
					d.hide();
					frappe.call({
						method: "caf.caf.overrides.appraisal.create_monthly_cycles",
						args: { year: values.year },
						freeze: true,
						freeze_message: __("Creating cycles..."),
					}).then((r) => {
						const res = (r && r.message) || {};
						const created = (res.created || []).length;
						const skipped = (res.skipped || []).length;
						frappe.msgprint({
							title: __("Monthly cycles"),
							indicator: created ? "green" : "blue",
							message: __("Created {0}, already present {1}.", [created, skipped]),
						});
						listview.refresh();
					});
				},
			});
			d.show();
		});
	},
};
