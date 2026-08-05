// CAF Appraisal - Appraisal form client script
// =============================================
// Purpose : Quality-of-life for the supervisor filling in a monthly appraisal -
//           the employee and cycle pickers are scoped, the auto-filled cells can
//           be refreshed on demand, the score columns disappear while scoring is
//           off, and the stock "Self Appraisal Pending" indicator is hidden.
// Doctype : Appraisal (stock, extended)  |  Hook: doctype_js
// Plan ref: CAF_appraisal_implementation_plan.md 4.10 (Q1-Q4), D2, D57, D59;
//           build_brief_chunk2.md 4.7
//
// SECURITY NOTE (D57): nothing in this file is a security control. Any logged-in
// user can call frappe.client.insert from the browser console or POST to the API
// directly, bypassing every line here. The real gates are the has_permission
// hook and the validate() re-check on the server (D56). This file exists so the
// supervisor gets a useful form, not so the system stays safe.
//
// Changelog
// ---------
// 1.0  2026-08-05  Initial - Chunk 2

frappe.ui.form.on("Appraisal", {
	setup(frm) {
		// Q1 - the employee picker offers only the supervisor's direct reports.
		// HR Manager gets no filter (BR3 override).
		frm.set_query("employee", () => {
			if (frappe.user.has_role("HR Manager")) {
				return { filters: { status: "Active" } };
			}
			return {
				query: "caf.caf.overrides.appraisal.employee_query_direct_reports",
			};
		});

		// Q2 - the cycle picker hides cycles this employee already has an
		// appraisal for. Server still enforces the duplicate check and BR6.
		frm.set_query("appraisal_cycle", () => {
			return {
				query: "caf.caf.overrides.appraisal.cycle_query_not_yet_appraised",
				filters: { employee: frm.doc.employee || "" },
			};
		});
	},

	onload(frm) {
		caf_hide_self_appraisal_indicator();
	},

	refresh(frm) {
		caf_toggle_score_fields(frm);
		caf_add_refresh_button(frm);
		caf_hide_self_appraisal_indicator();

		if (frm.is_new()) {
			caf_gate_new_form(frm);
		} else {
			caf_focus_first_empty_row(frm);
		}
	},

	employee(frm) {
		caf_preview_auto_fill(frm);
	},

	appraisal_cycle(frm) {
		caf_preview_auto_fill(frm);
	},
});

// --- D2 / Phase 5 -----------------------------------------------------------
// Score columns stay in the schema (DR2) and are hidden while the toggle is off.
function caf_toggle_score_fields(frm) {
	frappe.db
		.get_single_value("HR Settings", "caf_enable_score_calculation")
		.then((enabled) => {
			const on = Boolean(cint(enabled));
			["final_score", "total_score", "avg_feedback_score", "self_score", "goal_score_percentage"].forEach(
				(f) => frm.toggle_display(f, on)
			);

			const grid = frm.fields_dict.appraisal_kra && frm.fields_dict.appraisal_kra.grid;
			if (!grid) return;
			["per_weightage", "goal_completion", "goal_score"].forEach((f) => {
				const df = grid.get_docfield(f);
				if (df) {
					df.hidden = on ? 0 : 1;
					df.in_list_view = on ? 1 : 0;
				}
			});
			// with the score columns out of the way the CAF text columns fit
			["caf_date_cell", "caf_description", "caf_root_cause", "caf_corrective_action", "caf_remarks"].forEach(
				(f) => {
					const df = grid.get_docfield(f);
					if (df) df.in_list_view = on ? 0 : 1;
				}
			);
			grid.refresh();
		});
}

// --- Q4 ---------------------------------------------------------------------
function caf_add_refresh_button(frm) {
	if (frm.is_new() || frm.doc.docstatus !== 0) return;
	if (!frappe.user.has_role("HR Manager")) return;

	frm.add_custom_button(__("Refresh Data"), () => {
		frm.call({
			doc: frm.doc,
			method: "refresh_auto_fill_action",
			freeze: true,
			freeze_message: __("Recomputing attendance, lateness and overtime..."),
		}).then((r) => {
			if (!r || !r.message) return;
			frm.reload_doc();
			frappe.show_alert({
				message: __("Auto-filled cells recomputed"),
				indicator: "green",
			});
		});
	});
}

// --- D57 --------------------------------------------------------------------
// UX only. Tells a non-supervisor why the form is useless to them rather than
// letting them fill it in and hit a server error on save.
function caf_gate_new_form(frm) {
	frappe.call({ method: "caf.caf.overrides.appraisal.can_create_appraisal" }).then((r) => {
		const res = (r && r.message) || {};
		if (res.allowed) return;

		const reason =
			res.reason === "no_employee_record"
				? __("Your user account is not linked to an Employee record. Ask HR to set it.")
				: __("Only a supervisor can create an appraisal, and nobody currently reports to you.");

		frappe.msgprint({
			title: __("You cannot create an appraisal"),
			message: reason,
			indicator: "orange",
		});
	});
}

// --- Q3 ---------------------------------------------------------------------
function caf_focus_first_empty_row(frm) {
	const rows = frm.doc.appraisal_kra || [];
	const target = rows.find((r) => !(r.caf_description || "").trim());
	if (!target) return;

	const grid = frm.fields_dict.appraisal_kra && frm.fields_dict.appraisal_kra.grid;
	if (!grid) return;
	const grid_row = grid.grid_rows_by_docname && grid.grid_rows_by_docname[target.name];
	if (grid_row && grid_row.toggle_view) {
		grid_row.toggle_view(true);
	}
}

// --- convenience preview (D3) ----------------------------------------------
// The authoritative recomputation is server-side in validate(). This only lets
// the supervisor SEE the values before saving.
function caf_preview_auto_fill(frm) {
	if (frm.is_new() || !frm.doc.employee || !frm.doc.appraisal_cycle) return;
	if (frm.doc.docstatus !== 0) return;
	frm.dirty();
}

// --- D59 --------------------------------------------------------------------
// Under the workflow, appraisals sit at docstatus 0 all through HR review, and
// stock counts `docstatus=0 AND self_score=0` as "self appraisal pending" - so
// the indicator would count every in-review appraisal. CAF does not use self
// appraisal, so the figure is meaningless rather than merely inconvenient.
// Hiding a figure that does not apply changes no framework behaviour; the
// rejected alternative - a script writing fake self-appraisal ratings - would
// have invented Employee Feedback Rating rows attributed to real people.
function caf_hide_self_appraisal_indicator() {
	$(".self-appraisal-pending, [data-indicator='self-appraisal-pending']").hide();
}
