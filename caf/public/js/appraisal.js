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
// 1.1  2026-08-06  D89 - fix the "form freezes" report. caf_focus_first_empty_row
//                  opened the grid ROW FORM on every refresh; Frappe's
//                  show_form() calls frappe.dom.freeze() and only hide_form()
//                  unfreezes, so every refresh leaked one freeze and left an
//                  invisible full-screen backdrop swallowing clicks. Also:
//                  namespaced the document-level submit handler (it accumulated
//                  one binding per form load), moved grid column visibility to
//                  the schema (D90), suppressed the stock score chart while
//                  scoring is off (D91), defaulted Company (D92).

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

		// D91 - must be installed before the first refresh, which is when stock
		// hrms setup_chart draws into the form dashboard.
		caf_suppress_score_chart(frm);
	},

	onload(frm) {
		caf_hide_self_appraisal_indicator();
		caf_default_company(frm);
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

		// D89 - runs after the grid has finished rendering (set_focus_on_row
		// itself defers by 100 ms) so .grid-row-open reflects the final state.
		setTimeout(caf_release_orphan_freeze, 300);
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
//
// D90 - the OFF state is now the SCHEMA default, not something this function
// paints on afterwards. Property Setters ship in_list_view=0 for per_weightage /
// goal_completion / goal_score and the CAF custom fields ship in_list_view=1, so
// the grid is already correct on first paint.
//
// That was the "columns come and go" bug. This function reads the setting over
// the network, so the grid always rendered at least once BEFORE the answer
// arrived - with the stock score columns visible and the CAF text columns
// missing. Whether you saw the right columns came down to whether a re-render
// happened to land after the promise resolved, which is why Save (which
// re-renders) appeared to "bring the columns back". Worse, it mutated the
// docfield objects returned by grid.get_docfield(), which are shared per-meta
// and outlive the form, so the mutation leaked into every other Appraisal opened
// in the same session.
//
// Now the network round-trip only matters in the rare ON case, the result is
// cached per session, and grid.refresh() is called only when something actually
// changed.
let caf_score_enabled = null;

function caf_get_score_enabled() {
	if (caf_score_enabled !== null) return Promise.resolve(caf_score_enabled);
	return frappe.db
		.get_single_value("HR Settings", "caf_enable_score_calculation")
		.then((enabled) => {
			caf_score_enabled = Boolean(cint(enabled));
			return caf_score_enabled;
		});
}

function caf_toggle_score_fields(frm) {
	caf_get_score_enabled().then((on) => {
		["final_score", "total_score", "avg_feedback_score", "self_score", "goal_score_percentage"].forEach(
			(f) => frm.toggle_display(f, on)
		);

		// Off is the schema default - nothing to do, and in particular no
		// grid.refresh(), which is what used to make the columns flicker.
		if (!on) return;

		const grid = frm.fields_dict.appraisal_kra && frm.fields_dict.appraisal_kra.grid;
		if (!grid) return;

		let changed = false;
		["per_weightage", "goal_completion", "goal_score"].forEach((f) => {
			const df = grid.get_docfield(f);
			if (df && !df.in_list_view) {
				df.hidden = 0;
				df.in_list_view = 1;
				changed = true;
			}
		});
		// with the score columns back the CAF text columns no longer fit
		["caf_date_cell", "caf_description", "caf_root_cause", "caf_corrective_action", "caf_remarks"].forEach(
			(f) => {
				const df = grid.get_docfield(f);
				if (df && df.in_list_view) {
					df.in_list_view = 0;
					changed = true;
				}
			}
		);
		if (changed) grid.refresh();
	});
}

// --- D91 --------------------------------------------------------------------
// The stock hrms Appraisal form draws a "Scores" bar chart of per_weightage vs
// goal_score into the form dashboard on every refresh. CAF does not score today
// (D2/BR5), so every bar is 0 and the chart says nothing.
//
// It is also the source of the console noise the tester reported:
//     <svg> attribute width: A negative value is not valid. ("-10")
//     <rect> attribute width: A negative value is not valid. ("-2.25")
// frappe.Chart is handed the ".form-graph" container while it still measures 0px
// wide, so it subtracts its margins from 0 and emits negative geometry - one
// <rect> per bar (verified: 12 rects = 6 KRAs x 2 datasets). Harmless in itself,
// but it buries real errors in the console.
//
// Gated on the SAME HR Settings checkbox as the score fields
// (caf_enable_score_calculation), so an HR Manager who turns scoring on in the
// future gets the chart back with it - no code change needed.
// Hiding the chart after the fact is not enough - frappe.Chart has already been
// constructed by then and the console errors have already been emitted. So we
// intercept frm.dashboard.render_graph, which is the single call stock
// setup_chart goes through, and make it a no-op while scoring is off. Installed
// from setup() so it is in place before the first refresh.
function caf_suppress_score_chart(frm) {
	if (frm.__caf_chart_hooked) return;
	if (!frm.dashboard || typeof frm.dashboard.render_graph !== "function") return;
	frm.__caf_chart_hooked = true;

	const dashboard = frm.dashboard;
	const original = dashboard.render_graph.bind(dashboard);

	dashboard.render_graph = function (args) {
		// caf_score_enabled is null until the setting has been fetched; suppress
		// until we know, because off is the CAF default (D2/BR5).
		if (caf_score_enabled === true) return original(args);
		dashboard.hide();
		return null;
	};

	// If scoring turns out to be ON, put the chart back for this form load
	// rather than making the user refresh to see it.
	const was_unknown = caf_score_enabled === null;
	caf_get_score_enabled().then((on) => {
		if (on && was_unknown && !frm.is_new()) frm.trigger("setup_chart");
	});
}

// --- Q4 ---------------------------------------------------------------------
function caf_add_refresh_button(frm) {
	// D95 - visible to both supervisors and HR Managers. The supervisor
	// needs to see live Finger Log values to guide their feedback; HR uses
	// it after correcting Finger Log data.
	if (frm.is_new() || frm.doc.docstatus !== 0) return;

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
				message: __("Refreshed"),
				indicator: "green",
			});
		});
	});
}

// --- D92 --------------------------------------------------------------------
// Company is mandatory on Appraisal but stock leaves it empty on a new form, so
// every supervisor had to pick it by hand. CAF is a single-company site, and the
// field is only ever going to hold "CAF".
//
// Deliberately NOT hardcoded: fall back to the user's Global Default, then to
// the only Company on the site if there is exactly one. If a second company is
// ever added the field goes back to being a genuine choice and this stops
// guessing, which is the behaviour you want at that point.
function caf_default_company(frm) {
	if (!frm.is_new() || frm.doc.company) return;

	const preset = frappe.defaults.get_user_default("Company");
	if (preset) {
		frm.set_value("company", preset);
		return;
	}

	frappe.db.get_list("Company", { fields: ["name"], limit: 2 }).then((rows) => {
		if (rows && rows.length === 1 && !frm.doc.company) {
			frm.set_value("company", rows[0].name);
		}
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
// D89 - THE FREEZE BUG. This used to call grid_row.toggle_view(true), which opens
// the grid ROW FORM. Frappe's GridRow.show_form() calls
// frappe.dom.freeze("", "dark grid-form") and NOTHING unfreezes it except
// GridRow.hide_form(). A form refresh rebuilds the grid DOM without ever calling
// hide_form(), so every refresh incremented frappe.dom.freeze_count and left the
// #freeze backdrop in place. Measured live: freeze_count went 0 -> 1 -> 2 -> 3
// over three reload_doc() calls and never came back down.
//
// The backdrop is a 100%-viewport modal-backdrop at z-index 1020 that renders at
// opacity 0, so the page LOOKS completely normal while
// document.elementFromPoint() at the centre of the screen returns
// .freeze-message-container. Every click lands on the backdrop instead of the
// form - which is exactly what the tester described as "the screen freezes".
// It is not a hang: no long task, no request storm, no refresh loop (verified -
// one refresh and six XHRs per load, all under 150 ms).
//
// The replacement uses the EDITABLE-GRID path instead: grid.set_focus_on_row()
// activates the inline row and focuses its first visible input. It touches no
// freeze counter at all. Guarded to once per loaded document so it cannot fight
// a user who has clicked into a different row.
function caf_focus_first_empty_row(frm) {
	if (frm.__caf_focused_docname === frm.doc.name) return;

	const rows = frm.doc.appraisal_kra || [];
	const target = rows.findIndex((r) => !(r.caf_description || "").trim());
	if (target === -1) return;

	const grid = frm.fields_dict.appraisal_kra && frm.fields_dict.appraisal_kra.grid;
	if (!grid || !grid.grid_rows || !grid.grid_rows[target]) return;

	frm.__caf_focused_docname = frm.doc.name;
	grid.set_focus_on_row(target);
}

// D89 - belt and braces. Removing our own toggle_view() call fixes the leak we
// caused, but stock Frappe leaks the same way on its own: open a grid row by
// hand, then do anything that rebuilds the grid (Refresh Data, Save, a workflow
// action) and hide_form() is never reached. The user is then left with an
// invisible click-blocker and no way out except F5.
//
// The three conditions below make this safe to run on every render - it can only
// ever cancel a GRID-FORM freeze that has already been orphaned:
//   1. #freeze carries the `grid-form` class, which only GridRow.show_form()
//      sets - so a plain frappe.call({freeze: true}) backdrop is never touched;
//   2. no .grid-row-open element exists, so no row form is actually on screen;
//   3. no request is in flight, so we cannot pull the overlay out from under a
//      long-running server call such as refresh_auto_fill_action.
function caf_release_orphan_freeze() {
	if (!frappe.dom.freeze_count) return;
	if (frappe.request.ajax_count) return;
	if (document.querySelector(".grid-row-open")) return;

	const el = document.getElementById("freeze");
	if (!el || !el.classList.contains("grid-form")) return;

	while (frappe.dom.freeze_count) frappe.dom.unfreeze();
	$("#freeze").remove();
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
// D89 - this used to guard with `frm._caf_submit_hooked`, a flag on the FORM
// OBJECT, while binding to `document`, which outlives every form. Frappe builds
// a new Form object per doctype route but re-enters refresh() on every reload,
// and navigating Appraisal -> Appraisal -> Appraisal accumulated one live
// document handler per visit. They all survived, all closed over their own stale
// `frm`, and one click on "Submit for Review" fired every one of them - N stacked
// msgprint dialogs over a form that had already moved on.
//
// The namespace makes the binding idempotent: off() before on() means there is
// exactly one handler at any time, and it always closes over the current frm.
function caf_intercept_submit_action(frm) {
	$(document).off("click.caf-appraisal");
	$(document).on("click.caf-appraisal", ".actions-btn-group .dropdown-item", function () {
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
