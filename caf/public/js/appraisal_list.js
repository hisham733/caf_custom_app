// CAF Appraisal - Appraisal list view
// ====================================
// Purpose : Q5 - make workflow_state the thing you see and filter by, since
//           under D54 that is where an appraisal's real state lives (docstatus
//           stays 0 right through HR review, so the stock submitted/draft
//           indicator says almost nothing).
// Doctype : Appraisal (stock)  |  Hook: doctype_list_js
// Plan ref: CAF_appraisal_implementation_plan.md 4.10 Q5, D54, D82;
//           build_brief_chunk3.md 4.4
//
// Changelog
// ---------
// 1.0  2026-08-05  Initial - Chunk 3

frappe.listview_settings["Appraisal"] = {
	add_fields: ["workflow_state", "employee_name", "appraisal_cycle", "reported_by"],

	// Colour by workflow state rather than docstatus. Draft and Pending HR
	// Review are BOTH docstatus 0 (D54), so the stock indicator cannot tell
	// them apart - which is exactly the distinction HR cares about.
	get_indicator(doc) {
		const map = {
			Draft: ["Draft", "red", "workflow_state,=,Draft"],
			"Pending HR Review": ["Pending HR Review", "orange", "workflow_state,=,Pending HR Review"],
			Completed: ["Completed", "green", "workflow_state,=,Completed"],
		};
		return map[doc.workflow_state] || [doc.workflow_state || __("Unknown"), "gray", ""];
	},

	onload(listview) {
		// sidebar counts per state, so HR can see the size of the queue without
		// running a report
		frappe.call({
			method: "frappe.workflow.doctype.workflow.workflow.get_workflow_state_count",
			args: {
				doctype: "Appraisal",
				workflow_state_field: "workflow_state",
				states: JSON.stringify([]),
			},
		}).then((r) => {
			const counts = (r && r.message) || [];
			if (!counts.length) return;

			const $sidebar = listview.page.sidebar.find(".list-tags").length
				? listview.page.sidebar.find(".list-tags")
				: listview.page.sidebar;

			const html = counts
				.map((c) => {
					const state = c.workflow_state;
					return `<li class="list-link">
						<a class="btn btn-default btn-sm caf-state-filter" data-state="${frappe.utils.escape_html(state)}">
							${frappe.utils.escape_html(state)}
							<span class="badge">${c.count}</span>
						</a>
					</li>`;
				})
				.join("");

			const $block = $(`<div class="caf-state-counts sidebar-section">
					<div class="sidebar-label">${__("Workflow State")}</div>
					<ul class="list-unstyled sidebar-menu">${html}</ul>
				</div>`);
			$block.appendTo($sidebar);

			$block.on("click", ".caf-state-filter", function () {
				listview.filter_area.add([
					["Appraisal", "workflow_state", "=", $(this).data("state")],
				]);
			});
		});
	},
};
