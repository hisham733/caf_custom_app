// CAF — Shift & Saturday Roster.  Chunk 7.5, OD-72.
// ==================================================
// Page    : shift-roster
// Server  : caf.caf.page.shift_roster.shift_roster
// Refs    : framework §6.14 (OD-72) · roadmap §9d.5 · OD-71 (the detector)
//
// Three things, in the order HR needs them:
//
//   1. ALARMS      a half-done trade, and OD-71's missing-holiday detector.
//                  Both are empty in the healthy case, and the page says
//                  "nothing wrong" rather than showing an empty box — a panel
//                  that finds nothing must not look like a panel that cannot.
//   2. THE GRID    the alternate-Saturday roster, every cell from
//                  resolve_day_type(). Click a cell to trade that Saturday.
//   3. OVERRIDES   every Shift Assignment touching the month, with the
//                  employee's default shift beside the assigned one — MG's
//                  "Mr A's original shift is X but the doc changed it to B".
//
// ⚠️ The grid covers alternating shifts only. A standalone assignment for
// anyone else shows in the table and NOT in the grid, and the page says so
// rather than letting HR read the grid as complete.
//
// Changelog
// ---------
// 1.0  2026-08-12  Initial — Chunk 7.5

frappe.provide("caf.shift_roster");

frappe.pages["shift-roster"].on_page_load = function (wrapper) {
	frappe.shift_roster = new caf.shift_roster.Roster(wrapper);
};

frappe.pages["shift-roster"].on_page_show = function () {
	if (frappe.shift_roster) frappe.shift_roster.refresh();
};

caf.shift_roster.Roster = class Roster {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Shift & Saturday Roster"),
			single_column: true,
		});
		this.$body = $('<div class="caf-shift-roster">').appendTo(this.page.main);

		const now = frappe.datetime.get_today().slice(0, 7);
		this.month = now;
		this.page.add_field({
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Data",
			default: now,
			description: __("YYYY-MM"),
			change: () => {
				this.month = this.page.fields_dict.month.get_value() || now;
				this.refresh();
			},
		});

		if (caf.shift_trade.may_file()) {
			this.page.set_primary_action(__("Trade a Saturday"),
				() => caf.shift_trade.open({}, () => this.refresh()));
		}
		this.page.add_menu_item(__("Refresh"), () => this.refresh());

		this.refresh();
	}

	refresh() {
		this.$body.html(`<div class="text-muted p-4">${__("Loading...")}</div>`);

		frappe.call({
			method: "caf.caf.page.shift_roster.shift_roster.get_roster",
			args: { month: this.month },
		}).then((r) => {
			const data = (r && r.message) || {};
			this.$body.empty();
			this.data = data;

			this.render_alarms(data);
			this.render_grid(data);
			this.render_overrides(data);
		});
	}

	// ── helpers ──────────────────────────────────────────────────────────────

	panel(title, body, klass) {
		return $(`
			<div class="frappe-card mb-4 ${klass || ""}">
				<h5 class="mb-3">${title}</h5>
				${body}
			</div>`);
	}

	esc(v) {
		return frappe.utils.escape_html(v == null ? "" : String(v));
	}

	// ── 1. alarms ────────────────────────────────────────────────────────────

	render_alarms(data) {
		const gap = data.holiday_gap || { rows: [], count: 0 };
		const half = data.half_done || { rows: [], count: 0 };

		// OD-71 — the detector MG chose over HR's weekly prompt.
		let gap_body;
		if (!gap.count) {
			gap_body = `<p class="text-muted mb-0">${__("No working day this month was missed by the workforce. Nothing looks like an unrecorded holiday.")}</p>`;
		} else {
			gap_body = `
				<p class="mb-2">${__("These days were rostered as work, and almost nobody clocked in. A public or company holiday may be missing from the Holiday List — and until it is added, every alternate Saturday after it is inverted.")}</p>
				<table class="table table-sm mb-0">
					<thead><tr>
						<th>${__("Date")}</th><th>${__("Rostered")}</th>
						<th>${__("No punch at all")}</th><th>${__("Who")}</th>
					</tr></thead>
					<tbody>${gap.rows.map((r) => `
						<tr>
							<td><b>${this.esc(r.work_date)}</b></td>
							<td>${r.rostered}</td>
							<td>${r.no_punch} (${Math.round(r.share * 100)}%)</td>
							<td class="text-muted small">${r.names.map((n) => this.esc(n)).join(", ")}</td>
						</tr>`).join("")}</tbody>
				</table>`;
		}
		this.$body.append(this.panel(
			`${gap.count ? "⚠️ " : ""}${__("Possible missing holiday")}`, gap_body));

		// Half-done trades — the failure 7.3's pairing exists to make findable.
		let half_body;
		if (!half.count) {
			half_body = `<p class="text-muted mb-0">${__("Every filed trade has both halves. Nothing is half-done.")}</p>`;
		} else {
			half_body = `
				<p class="mb-2">${__("A swap is two assignments. These have only one — so one person's roster moved and the other's did not.")}</p>
				<table class="table table-sm mb-0">
					<thead><tr>
						<th>${__("Date")}</th><th>${__("Employee")}</th>
						<th>${__("Shift")}</th><th>${__("Traded with")}</th><th></th>
					</tr></thead>
					<tbody>${half.rows.map((r) => `
						<tr>
							<td>${this.esc(r.start_date)}</td>
							<td>${this.esc(r.employee_name)}</td>
							<td>${this.esc(r.shift_type)}</td>
							<td>${this.esc(r.caf_swap_with)}</td>
							<td><a href="/app/shift-assignment/${encodeURIComponent(r.name)}">${__("Open")}</a></td>
						</tr>`).join("")}</tbody>
				</table>`;
		}
		this.$body.append(this.panel(
			`${half.count ? "⚠️ " : ""}${__("Half-done trades")}`, half_body));

		this.render_group_rest(data);
	}

	// OD-69(b) — the mirror image of the missing-holiday detector. That one finds
	// a WORK day nobody came to; this finds a REST day the whole group came to.
	//
	// The group size is shown because it IS the evidence: 6 of 6 is a roster
	// error, 2 of 2 could be two people who simply came in. The screen says
	// which, and never blocks anything — working a rest day is legitimate and
	// FBR4 pays it as OT.
	render_group_rest(data) {
		const g = data.group_rest_work || { rows: [], count: 0 };

		let body;
		if (!g.count) {
			body = `<p class="text-muted mb-0">${__("No alternating group worked a Saturday its Holiday List calls a rest day.")}</p>`;
		} else {
			body = `
				<p class="mb-2">${__("Every member of these groups worked a Saturday their list calls rest. One person doing that is overtime; the whole group is a roster error — or a holiday missing from the list.")}</p>
				<table class="table table-sm mb-0">
					<thead><tr>
						<th>${__("Date")}</th><th>${__("Shift")}</th>
						<th>${__("Worked")}</th><th>${__("Signal")}</th><th>${__("Who")}</th>
					</tr></thead>
					<tbody>${g.rows.map((r) => `
						<tr>
							<td><b>${this.esc(r.date)}</b></td>
							<td>${this.esc(r.shift)}</td>
							<td>${r.worked} ${__("of")} ${r.group_size}</td>
							<td>${r.strength === "strong"
								? `<span class="text-danger">${__("strong")}</span>`
								: `<span class="text-muted">${__("weak — small group")}</span>`}</td>
							<td class="text-muted small">${r.employees.map((n) => this.esc(n)).join(", ")}</td>
						</tr>`).join("")}</tbody>
				</table>`;
		}
		this.$body.append(this.panel(
			`${g.count ? "⚠️ " : ""}${__("Group worked a rest Saturday")}`, body));
	}

	// ── 2. the grid ──────────────────────────────────────────────────────────

	render_grid(data) {
		const sats = data.saturdays || [];
		const rows = data.rows || [];

		if (!sats.length) {
			this.$body.append(this.panel(__("Saturday roster"),
				`<p class="text-muted mb-0">${__("No Saturdays in {0}.", [this.esc(data.month_label)])}</p>`));
			return;
		}
		if (!rows.length) {
			this.$body.append(this.panel(__("Saturday roster"),
				`<p class="text-muted mb-0">${__("Nobody is on an alternating shift. Set caf_alt_sat on a Shift Type and put an employee on it.")}</p>`));
			return;
		}

		const head = sats.map((d) => `<th class="text-center">${this.esc(d.slice(8))} ${this.esc(
			frappe.datetime.str_to_obj(d).toLocaleString("en", { month: "short" }))}</th>`).join("");

		const body = rows.map((row) => {
			const cells = row.cells.map((c) => {
				const rest = c.day_type === "Restday";
				const hol = c.day_type === "Holiday";
				// A traded cell is marked, because the whole point of the screen
				// is telling a routine Saturday from one somebody moved.
				const mark = c.overridden ? ' <span title="' + this.esc(c.kind) + '">*</span>' : "";
				const cls = hol ? "text-muted" : (rest ? "text-danger" : "");
				const label = hol ? __("hol") : (rest ? __("REST") : __("work"));
				return `<td class="text-center caf-cell ${cls}"
							data-employee="${this.esc(row.employee)}"
							data-date="${this.esc(c.date)}"
							style="cursor:pointer"
							title="${this.esc(c.shift)}">${label}${mark}</td>`;
			}).join("");
			return `<tr>
					<td>${this.esc(row.employee_name)}</td>
					<td class="text-muted small">${this.esc(row.default_shift)}</td>
					${cells}
				</tr>`;
		}).join("");

		const $p = this.panel(
			__("Saturday roster — {0}", [this.esc(data.month_label)]),
			`<p class="text-muted small">${__("Every cell is resolved live, so a filed trade shows here without being looked up. A column that is entirely work or entirely REST is worth a second look. * = a Shift Assignment moved this day.")}</p>
			<div style="overflow-x:auto">
			<table class="table table-sm table-bordered mb-2">
				<thead><tr><th>${__("Employee")}</th><th>${__("Default shift")}</th>${head}</tr></thead>
				<tbody>${body}</tbody>
			</table></div>
			<p class="text-muted small mb-0">${__("Alternating shifts only. A standalone assignment for anyone else appears in the table below and not in this grid.")}</p>`);

		if (caf.shift_trade.may_file()) {
			$p.on("click", "td.caf-cell", (e) => {
				const $td = $(e.currentTarget);
				caf.shift_trade.open(
					{ work_date: $td.data("date"), employee_a: $td.data("employee") },
					() => this.refresh());
			});
		}
		this.$body.append($p);
	}

	// ── 3. overrides / exceptions ────────────────────────────────────────────

	render_overrides(data) {
		const rows = data.overrides || [];

		if (!rows.length) {
			this.$body.append(this.panel(
				__("Assignments & overrides"),
				`<p class="text-muted mb-0">${__("No Shift Assignment touches {0}. Since the alternation moved into the shift, a routine Saturday needs no document — every row here is a genuine exception.", [this.esc(data.month_label)])}</p>`));
			return;
		}

		const body = rows.map((r) => `
			<tr>
				<td>${this.esc(r.start_date)}${r.end_date !== r.start_date ? " &rarr; " + this.esc(r.end_date) : ""}</td>
				<td>${this.esc(r.employee_name)}</td>
				<td class="text-muted">${this.esc(r.default_shift)}</td>
				<td>${r.changed ? "<b>" + this.esc(r.shift_type) + "</b>" : this.esc(r.shift_type)}</td>
				<td>${this.esc(r.kind)}</td>
				<td>${this.esc(r.traded_with_name || "")}</td>
				<td>${r.kind === "Swap" && !r.partner
					? `<span class="text-danger">${__("unpaired")}</span>`
					: `<span class="text-muted">${this.esc(r.status)}</span>`}</td>
				<td><a href="/app/shift-assignment/${encodeURIComponent(r.name)}">${__("Open")}</a></td>
			</tr>`).join("");

		this.$body.append(this.panel(
			__("Assignments & overrides — {0}", [this.esc(data.month_label)]),
			`<p class="text-muted small">${__("One list, not two. Swap, Cover and a plain single assignment are all the same thing to HR — a document that overrides somebody's default shift — so the kind is a column, not a separate section.")}</p>
			<div style="overflow-x:auto">
			<table class="table table-sm mb-0">
				<thead><tr>
					<th>${__("Date")}</th><th>${__("Employee")}</th>
					<th>${__("Default shift")}</th><th>${__("Assigned shift")}</th>
					<th>${__("Kind")}</th><th>${__("Traded with")}</th>
					<th>${__("State")}</th><th></th>
				</tr></thead>
				<tbody>${body}</tbody>
			</table></div>`));
	}
};
