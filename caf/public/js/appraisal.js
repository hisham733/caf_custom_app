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
			caf_render_feedback(frm);
			caf_intercept_submit_action(frm);
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
// The AUTHORITATIVE recomputation is server-side in validate(), so the stored
// document always matches the data at save time. This only lets the supervisor
// SEE the figures before committing to them - which matters more than it
// sounds: D40 removed their direct read on Finger Log, so this form is the only
// place they ever see these numbers.
function caf_preview_auto_fill(frm) {
	if (!frm.doc.employee || !frm.doc.appraisal_cycle) return;
	if (frm.doc.docstatus !== 0) return;

	const rows = frm.doc.appraisal_kra || [];
	if (!rows.length) return; // grid is built server-side on first save

	frappe.call({
		method: "caf.caf.overrides.appraisal.preview_auto_fill",
		args: { employee: frm.doc.employee, appraisal_cycle: frm.doc.appraisal_cycle },
	}).then((r) => {
		const res = (r && r.message) || {};

		if (res.month_ended === false) {
			frappe.show_alert({
				message: __("{0} has not ended yet — attendance and overtime will be filled in once it has.", [
					frm.doc.appraisal_cycle,
				]),
				indicator: "blue",
			});
			return;
		}

		const cells = res.cells || {};
		let touched = false;
		(frm.doc.appraisal_kra || []).forEach((row) => {
			if (!(row.kra in cells)) return;
			// never overwrite something the supervisor typed
			if ((row.caf_date_cell || "").trim()) return;
			frappe.model.set_value(row.doctype, row.name, "caf_date_cell", cells[row.kra]);
			touched = true;
			if (row.kra === "Attendance" && !(row.caf_remarks || "").trim() && res.working_days) {
				frappe.model.set_value(row.doctype, row.name, "caf_remarks",
					__("{0} working days", [res.working_days]));
			}
		});

		if (touched) {
			frm.refresh_field("appraisal_kra");
			frappe.show_alert({
				message: __("Attendance, punctuality and overtime filled in from Finger Log — not saved yet."),
				indicator: "green",
			});
		}
	});
}

// --- D60/D61/D62: the CAF feedback widget -----------------------------------
// Replaces the stock widget, which queries by APPRAISAL. Under D60 an EPF is a
// standing note about a person, so the stock widget cannot see any of the
// unlinked ones - which is all of them, in CAF's usage.
function caf_render_feedback(frm) {
	// Deliberately NOT feedback_html. Stock appraisal.js renders into that
	// wrapper from inside a frappe.require("performance.bundle.js") callback
	// which resolves after us, so it overwrites whatever we paint - observed
	// live, the widget showed stock's "No feedback has been received yet" with a
	// submitted standing EPF sitting right there. Winning that race with a
	// timeout would break as soon as bundle caching changed the timing, so CAF
	// gets its own field and the stock one is hidden.
	frm.toggle_display("feedback_html", false);

	const wrapper = frm.fields_dict.caf_feedback_html && frm.fields_dict.caf_feedback_html.wrapper;
	if (!wrapper || !frm.doc.employee) return;

	// D61 - the window ends at the CYCLE's end date, not today, so reopening an
	// old appraisal shows what was visible when it was written.
	const finish = () => {
		frappe.call({
			method: "caf.caf.overrides.performance_feedback.get_caf_feedback_history",
			args: {
				employee: frm.doc.employee,
				appraisal: frm.doc.name,
				end_date: frm._caf_cycle_end || null,
			},
		}).then((r) => {
			const data = (r && r.message) || {};
			$(wrapper).empty().append(caf_feedback_html(data));
		});
	};

	if (frm.doc.appraisal_cycle && !frm._caf_cycle_end) {
		frappe.db.get_value("Appraisal Cycle", frm.doc.appraisal_cycle, "end_date").then((res) => {
			frm._caf_cycle_end = (res && res.message && res.message.end_date) || null;
			finish();
		});
	} else {
		finish();
	}
}

function caf_feedback_html(data) {
	const rows = data.feedback || [];
	const w = data.window;
	const header = w
		? __("Feedback from {0} to {1} ({2} months)", [w.from, w.to, w.months])
		: __("Feedback");

	if (!rows.length) {
		return `<div class="text-muted">${header} — ${__("none recorded.")}</div>`;
	}

	const items = rows.map((f) => {
		const author = data.show_author
			? `<b>${frappe.utils.escape_html(f.reviewer_name || f.reviewer || "")}</b>` +
			  (f.reviewer_designation ? ` <span class="text-muted">${frappe.utils.escape_html(f.reviewer_designation)}</span>` : "")
			: `<span class="text-muted">${__("Author hidden")}</span>`;

		// D65 - a standing (unlinked) EPF carries no rating criteria and scores
		// 0 by stock design, so showing a score would be misleading.
		const score = f.is_standing
			? `<span class="indicator blue">${__("Standing feedback")}</span>`
			: `<span class="indicator green">${__("Score {0}", [f.total_score])}</span>`;

		return `
			<div class="caf-feedback-item" style="border-bottom:1px solid var(--border-color); padding:8px 0;">
				<div class="d-flex justify-content-between">
					<div>${author}</div>
					<div class="text-muted small">${frappe.datetime.str_to_user(f.added_on)} ${score}</div>
				</div>
				<div class="mt-1">${f.feedback || ""}</div>
			</div>`;
	}).join("");

	return `<div class="caf-feedback">
			<div class="text-muted mb-2">${header} — ${__("{0} entries", [rows.length])}</div>
			${items}
		</div>`;
}

// --- Q6: submit confirmation ------------------------------------------------
// Shows the auto-filled values before the appraisal leaves the supervisor's
// hands. They are computed from Finger Log and the supervisor never sees that
// data directly (D40), so this is their only chance to sanity-check it.
function caf_intercept_submit_action(frm) {
	if (frm._caf_submit_hooked) return;
	frm._caf_submit_hooked = true;

	$(document).on("click", ".actions-btn-group .dropdown-item", function () {
		const label = ($(this).text() || "").trim();
		if (label !== __("Submit for Review")) return;
		caf_show_submit_summary(frm);
	});
}

function caf_show_submit_summary(frm) {
	const rows = frm.doc.appraisal_kra || [];
	const cell = (name) => {
		const row = rows.find((r) => r.kra === name);
		return (row && row.caf_date_cell) || __("(none)");
	};

	frappe.msgprint({
		title: __("Submitting for HR review"),
		indicator: "blue",
		message: `
			<p>${__("These values were computed from Finger Log for this cycle:")}</p>
			<table class="table table-sm">
				<tr><td>${__("Attendance")}</td><td><b>${frappe.utils.escape_html(cell("Attendance"))}</b></td></tr>
				<tr><td>${__("Punctuality")}</td><td><b>${frappe.utils.escape_html(cell("Punctuality"))}</b></td></tr>
				<tr><td>${__("OT Hours")}</td><td><b>${frappe.utils.escape_html(cell("OT Hours"))}</b></td></tr>
			</table>
			<p class="text-muted small">${__("Once submitted you cannot edit this appraisal until HR sends it back.")}</p>`,
	});
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
