// CAF Appraisal - HR dashboard
// =============================
// Purpose : Renders the three panels of the appraisal dashboard - data health,
//           monthly progress, and the action queue - with role-split sections.
// Page    : hr-appraisal-dashboard
// Plan ref: CAF_appraisal_implementation_plan.md 6, D6/D13/D52/D73;
//           build_brief_chunk3.md 4.2
//
// One page, role-split (D13): HR Manager sees all three panels; a supervisor
// sees only the action queue and their own slice of monthly progress. The
// figures come from the server already scoped through the same permission rule
// as the rest of the product, so this file never filters anything itself.
//
// The Supervisor Performance panel is DEFERRED (D73) and deliberately absent.
//
// Changelog
// ---------
// 1.0  2026-08-05  Initial - Chunk 3

frappe.provide("caf.appraisal_dashboard");

frappe.pages["hr-appraisal-dashboard"].on_page_load = function (wrapper) {
	frappe.appraisal_dashboard = new caf.appraisal_dashboard.Dashboard(wrapper);
};

frappe.pages["hr-appraisal-dashboard"].on_page_show = function () {
	if (frappe.appraisal_dashboard) frappe.appraisal_dashboard.refresh();
};

caf.appraisal_dashboard.Dashboard = class Dashboard {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Appraisal Dashboard"),
			single_column: true,
		});
		this.$body = $('<div class="caf-appraisal-dashboard">').appendTo(this.page.main);

		this.year = new Date().getFullYear();
		this.page.add_field({
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: this.year,
			change: () => {
				this.year = this.page.fields_dict.year.get_value() || this.year;
				this.refresh();
			},
		});

		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.refresh();
	}

	refresh() {
		this.$body.html(`<div class="text-muted p-4">${__("Loading...")}</div>`);

		frappe.call({
			method: "caf.caf.page.hr_appraisal_dashboard.hr_appraisal_dashboard.get_dashboard",
			args: { year: this.year },
		}).then((r) => {
			const data = (r && r.message) || {};
			this.$body.empty();

			if (data.is_hr_manager) {
				this.render_health(data.health);
			} else if (!data.employee) {
				// has_permission resolves the session user through Employee.user_id,
				// so without one every check fails closed and the page would just
				// look empty. Say so instead.
				this.$body.append(this.panel(
					__("Your account is not linked to an Employee record"),
					`<p class="text-muted">${__("Ask HR to set the User ID on your Employee record. Until then this dashboard cannot show your team.")}</p>`
				));
			}

			this.render_queue(data.queue, data.is_hr_manager);
			this.render_monthly(data.monthly, data.is_hr_manager);
			// OD-64. Directly under monthly progress on purpose: that panel counts
			// a submitted appraisal as done, and this is the correction to it.
			this.render_refreshed(data.refreshed);
			this.render_hr_review(data.hr_review);
		});
	}

	panel(title, html) {
		return $(`
			<div class="caf-panel mb-4">
				<h5 class="mb-2">${frappe.utils.escape_html(title)}</h5>
				<div class="caf-panel-body">${html}</div>
			</div>
		`);
	}

	// --- Panel 0: data health (T38) -------------------------------------
	render_health(health) {
		if (!health) return;

		const ok = health.root_count === health.root_expected;
		const rows = [];

		rows.push(this.health_row(
			ok,
			__("Organisation roots"),
			__("{0} found, {1} expected", [health.root_count, health.root_expected]),
			(health.roots || []).map((r) => `${r.employee_name} (${r.name})`).join(", ")
		));

		rows.push(this.health_row(
			(health.roots_unflagged || []).length === 0,
			__("Roots missing the org-root tick"),
			__("{0} employee(s)", [(health.roots_unflagged || []).length]),
			(health.roots_unflagged || []).map((r) => r.name).join(", ")
		));

		rows.push(this.health_row(
			(health.blocked_supervisors || []).length === 0,
			__("Supervisors with no User ID"),
			__("{0} supervisor(s)", [(health.blocked_supervisors || []).length]),
			__("Permission checks fail closed without it - they would see nothing, with no error. ") +
				(health.blocked_supervisors || []).map((r) => `${r.employee_name} (${r.name}, ${r.direct_reports} reports)`).join(", ")
		));

		// Separated on purpose: an org root without a login may well be
		// deliberate, but the people reporting to them still need appraising,
		// and only HR Manager can do it.
		const rootsNoLogin = health.roots_without_login || [];
		rows.push(this.health_row(
			rootsNoLogin.length === 0,
			__("Org roots with no User ID"),
			__("{0} root(s)", [rootsNoLogin.length]),
			rootsNoLogin.length
				? __("May be deliberate, but {0} employee(s) report to them and only HR Manager can appraise those. ", [
						rootsNoLogin.reduce((n, r) => n + (r.direct_reports || 0), 0),
				  ]) + rootsNoLogin.map((r) => `${r.employee_name} (${r.direct_reports} reports)`).join(", ")
				: ""
		));

		rows.push(this.health_row(
			true,
			__("Employees with no User ID"),
			__("{0} employee(s)", [(health.no_user_id || []).length]),
			(health.no_user_id || []).map((r) => r.name).join(", ")
		));

		rows.push(this.health_row(
			(health.no_default_shift || []).length === 0,
			__("Appraisable employees with no default shift"),
			__("{0} employee(s)", [(health.no_default_shift || []).length]),
			__("Their punctuality cell is skipped. ") +
				(health.no_default_shift || []).map((r) => r.name).join(", ")
		));

		const body = `
			<p>
				<a class="btn btn-default btn-sm" href="${health.org_chart_route}">
					${__("Open the organisation chart")}
				</a>
				<span class="text-muted ml-2">${__("The reports_to tree the whole permission model rests on.")}</span>
			</p>
			<table class="table table-sm">${rows.join("")}</table>
		`;
		this.$body.append(this.panel(__("Data health"), body));
	}

	health_row(ok, label, value, detail) {
		const indicator = ok ? "green" : "orange";
		return `
			<tr>
				<td style="width: 34%"><span class="indicator ${indicator}">${frappe.utils.escape_html(label)}</span></td>
				<td style="width: 16%"><b>${frappe.utils.escape_html(value)}</b></td>
				<td class="text-muted small">${frappe.utils.escape_html(detail || "")}</td>
			</tr>
		`;
	}

	// --- Panel 2: action queue ------------------------------------------
	render_queue(queue, is_hr) {
		const rows = (queue && queue.rows) || [];
		const title = is_hr
			? __("Awaiting your review")
			: __("Your appraisals in progress");

		if (!rows.length) {
			this.$body.append(this.panel(title,
				`<p class="text-muted">${__("Nothing needs attention.")}</p>`));
			return;
		}

		const body = `
			<table class="table table-sm">
				<thead><tr>
					<th>${__("Cycle")}</th><th>${__("Employee")}</th>
					<th>${__("Supervisor")}</th><th>${__("State")}</th>
					<th>${__("Comments")}</th><th></th>
				</tr></thead>
				<tbody>
				${rows.map((r) => `
					<tr>
						<td>${frappe.utils.escape_html(r.appraisal_cycle || "")}</td>
						<td>${frappe.utils.escape_html(r.employee_name || r.employee || "")}</td>
						<td>${frappe.utils.escape_html(r.supervisor_name || "")}</td>
						<td><span class="indicator ${r.workflow_state === "Pending HR Review" ? "orange" : "blue"}">
							${frappe.utils.escape_html(r.workflow_state || "")}</span></td>
						<td>${r.comment_count ? `<span class="indicator red">${r.comment_count}</span>` : ""}</td>
						<td><a href="/app/appraisal/${encodeURIComponent(r.name)}">${__("Open")}</a></td>
					</tr>`).join("")}
				</tbody>
			</table>`;
		this.$body.append(this.panel(title, body));
	}

	// --- Panel 3: refreshed after submit (OD-64) ------------------------
	//
	// The panel above counts a SUBMITTED appraisal as done. Since OD-44 and OD-60
	// that is no longer true: a late leave or a late shift assignment rewrites the
	// auto-filled cells of a submitted appraisal, in either direction. Without
	// this, a number moves on a document HR considers closed and nobody is told.
	//
	// Empty is the normal state, and it is worth SAYING so — a panel that renders
	// nothing is indistinguishable from one that is broken.
	render_refreshed(refreshed) {
		const rows = (refreshed && refreshed.rows) || [];
		const title = __("Changed after submission");

		if (!rows.length) {
			this.$body.append(this.panel(title,
				`<p class="text-muted">${__("No submitted appraisal has been recalculated. This panel fills when a late leave or shift assignment moves a number on a closed appraisal.")}</p>`));
			return;
		}

		const body = `
			<p class="text-muted small mb-2">${__("These are counted as complete above, but their figures moved afterwards.")}</p>
			<table class="table table-sm">
				<thead><tr>
					<th>${__("Cycle")}</th><th>${__("Employee")}</th>
					<th>${__("Times")}</th><th>${__("Last change")}</th>
					<th>${__("What changed")}</th><th></th>
				</tr></thead>
				<tbody>
				${rows.map((r) => `
					<tr>
						<td>${frappe.utils.escape_html(r.appraisal_cycle || "")}</td>
						<td>${frappe.utils.escape_html(r.employee_name || r.employee || "")}</td>
						<td><span class="indicator ${r.refresh_count > 1 ? "orange" : "blue"}">${r.refresh_count}</span></td>
						<td>${frappe.datetime.str_to_user(r.last_refreshed)}</td>
						<td class="small text-muted">${frappe.utils.escape_html((r.detail || "").slice(0, 160))}</td>
						<td><a href="/app/appraisal/${encodeURIComponent(r.name)}">${__("Open")}</a></td>
					</tr>`).join("")}
				</tbody>
			</table>`;
		this.$body.append(this.panel(title, body));
	}

	// --- Panel 4: Finger Logs flagged for HR (OD-64) --------------------
	//
	// `caf_hr_review` is raised by Chunk 4 when a re-resolve leaves OT its
	// approval no longer covers. The job flags rather than throwing, because one
	// bad row must not abort the batch (scenario S3) — which meant the flag had
	// nowhere to go. HR Manager only: these carry OT figures.
	render_hr_review(hr_review) {
		if (!hr_review) return;          // not an HR Manager; the key is absent
		const rows = hr_review.rows || [];
		const title = __("Attendance needing review");

		if (!rows.length) {
			this.$body.append(this.panel(title,
				`<p class="text-muted">${__("No flagged attendance. This fills when a re-resolve leaves overtime its approval no longer covers.")}</p>`));
			return;
		}

		const more = hr_review.total > hr_review.shown
			? `<p class="text-muted small">${__("Showing {0} of {1}.", [hr_review.shown, hr_review.total])}</p>`
			: "";

		const body = `
			${more}
			<table class="table table-sm">
				<thead><tr>
					<th>${__("Date")}</th><th>${__("Employee")}</th>
					<th>${__("Day")}</th><th>${__("Final OT")}</th>
					<th>${__("OT Approval")}</th><th>${__("Why")}</th><th></th>
				</tr></thead>
				<tbody>
				${rows.map((r) => `
					<tr>
						<td>${frappe.datetime.str_to_user(r.work_date)}</td>
						<td>${frappe.utils.escape_html(r.employee_name || r.employee || "")}</td>
						<td>${frappe.utils.escape_html(r.day_type || "")}</td>
						<td>${r.final_ot || 0}</td>
						<td>${r.ot_approval_id
							? `<a href="/app/ot-approval/${encodeURIComponent(r.ot_approval_id)}" target="_blank" rel="noopener">${frappe.utils.escape_html(r.ot_approval_id)}</a>`
							: `<span class="indicator red">${__("none")}</span>`}</td>
						<td class="small text-muted">${frappe.utils.escape_html((r.caf_hr_review_note || "").slice(0, 90))}</td>
						<td><a href="/app/finger-log/${encodeURIComponent(r.name)}">${__("Open")}</a></td>
					</tr>`).join("")}
				</tbody>
			</table>`;
		this.$body.append(this.panel(title, body));
	}

	// --- Panel 1: monthly progress --------------------------------------
	render_monthly(monthly, is_hr) {
		const cycles = (monthly && monthly.cycles) || [];
		const title = is_hr
			? __("Monthly progress {0}", [monthly.year])
			: __("Monthly progress {0} - your team", [monthly.year]);

		if (!cycles.length) {
			this.$body.append(this.panel(title,
				`<p class="text-muted">${__("No appraisal cycles for this year.")}</p>`));
			return;
		}

		const body = `
			<table class="table table-sm">
				<thead><tr>
					<th>${__("Cycle")}</th><th class="text-right">${__("Appraisees")}</th>
					<th class="text-right">${__("Created")}</th><th class="text-right">${__("Draft")}</th>
					<th class="text-right">${__("Pending review")}</th><th class="text-right">${__("Completed")}</th>
					<th style="width: 22%">${__("Completion")}</th>
				</tr></thead>
				<tbody>
				${cycles.map((c) => `
					<tr>
						<td><a href="/app/appraisal?appraisal_cycle=${encodeURIComponent(c.cycle)}">${frappe.utils.escape_html(c.cycle)}</a></td>
						<td class="text-right">${c.appraisees}</td>
						<td class="text-right">${c.created}</td>
						<td class="text-right">${c.draft}</td>
						<td class="text-right">${c.pending_review}</td>
						<td class="text-right">${c.completed}</td>
						<td>
							<div class="progress" style="height: 12px; margin-bottom: 2px;">
								<div class="progress-bar" role="progressbar"
									 style="width: ${c.completion_pct}%"></div>
							</div>
							<span class="small text-muted">${c.completion_pct}%</span>
						</td>
					</tr>`).join("")}
				</tbody>
			</table>
			<p class="text-muted small mb-0">
				${__("Appraisees exclude the organisation roots, who are not appraised.")}
			</p>`;
		this.$body.append(this.panel(title, body));
	}
};
