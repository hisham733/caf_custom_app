frappe.provide("caf.production_schedule");

frappe.pages["production-schedule"].on_page_load = function (wrapper) {
	frappe.production_schedule = new caf.production_schedule.ScheduleBoard(wrapper);
};

frappe.pages["production-schedule"].on_page_show = function () {
	frappe.production_schedule.refresh();
	$(".layout-side-section").hide();
	$(".layout-main-section").addClass("col-md-12").removeClass("col-md-10");
};

caf.production_schedule.ScheduleBoard = class ScheduleBoard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.state = {
			year: new Date().getFullYear(),
			week: null,
			mode: "View Schedule",
			week_monday: null,
			workstations: [],
			days: [],
			day_labels: [],
			dp_names: {},
			schedule: {},
			past_days: [],
			ws_problems: [],
			last_action: null,
		};
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Production Schedule"),
			single_column: false,
		});
		this.make();
		this._ensure_sortable();
	}

	// ══════════════════════════════════════════════════════════════
	//  BOOTSTRAP
	// ══════════════════════════════════════════════════════════════

	make() {
		this.page.main.html(this._toolbar_html() + this._board_container_html());
		this._setup_events();
	}

	refresh() {
		var now = new Date();
		this._compute_iso_week(now);
		this._sync_inputs();
		this._load_week();
	}

	// ══════════════════════════════════════════════════════════════
	//  TOOLBAR
	// ══════════════════════════════════════════════════════════════

	_toolbar_html() {
		var view_opts = ["Edit Schedule", "View Schedule"];
		var mode_sel = view_opts
			.map(function (m) {
				return (
					'<option value="' + m + '"' + (m === "View Schedule" ? " selected" : "") + ">" + m + "</option>"
				);
			})
			.join("");

		return (
			'<div class="schedule-toolbar" role="toolbar" aria-label="' + __("Schedule controls") + '">' +
			'  <div class="schedule-filters">' +
			'    <label for="schedule-year">' + __("Year") + '</label>' +
			'    <input type="number" id="schedule-year" class="form-control" style="width:80px" aria-label="' + __("Year") + '" />' +
			'    <label for="schedule-week">' + __("Week (ISO)") + '</label>' +
			'    <input type="number" id="schedule-week" class="form-control" style="width:70px" min="1" max="53" aria-label="' + __("ISO week number") + '" />' +
			'    <label for="schedule-mode">' + __("Mode") + '</label>' +
			'    <select id="schedule-mode" class="form-control" style="width:150px" aria-label="' + __("View mode") + '">' +
			mode_sel +
			'    </select>' +
			'    <button class="btn btn-primary btn-sm" id="schedule-load-btn">' +
			'      <svg class="icon icon-sm"><use href="#icon-refresh"></use></svg> ' + __("Load") + '</button>' +
			'  </div>' +
			'  <div class="schedule-actions">' +
			'    <span class="schedule-week-info" id="schedule-week-range" aria-live="polite"></span>' +
			'    <button class="btn btn-success btn-sm" id="schedule-submit-btn"' +
			'      title="' + __("Submit all draft DPs") + '">' +
			'      <svg class="icon icon-sm"><use href="#icon-check"></use></svg> ' + __("Submit Week") +
			'    </button>' +
			'  </div>' +
			'</div>'
		);
	}

	_board_container_html() {
		return (
			'<div class="schedule-summary" id="schedule-summary"></div>' +
			'<div class="schedule-board-wrapper" role="region" aria-label="' + __("Production schedule grid") + '">' +
			'  <div class="schedule-board" id="schedule-board"></div>' +
			'</div>' +
			'<div class="schedule-status" id="schedule-status" aria-live="polite"></div>'
		);
	}

	_setup_events() {
		var me = this;
		var m = this.page.main;

		m.find("#schedule-load-btn").on("click", function () {
			me._read_inputs();
			me._load_week();
		});

		m.find("#schedule-submit-btn").on("click", function () {
			me._submit_week();
		});

		m.find("#schedule-year").on("change", function () {
			me._read_inputs();
			me._load_week();
		});

		m.find("#schedule-week").on("change", function () {
			me._read_inputs();
			me._load_week();
		});

		m.find("#schedule-mode").on("change", function () {
			me.state.mode = this.value;
			me._update_action_btns();
			if (me.state.mode === "Edit Schedule") {
				frappe.call({
					method: "caf.caf.page.production_schedule.production_schedule.create_week_version",
					args: { week_number: me.state.week },
					callback: function () { me._load_week(); },
					error: function () { me._load_week(); },
				});
			} else {
				me._load_week();
			}
		});

		m.on("click", ".round-slot .schedule-item", function () {
			var slot = this.closest(".round-slot");
			var row = slot ? slot.closest("tr") : null;
			var ws = row ? row.dataset.workstation : "";
			if (slot && (me.state.past_days.indexOf(slot.dataset.day) !== -1 || me.state.mode === "View Schedule" || me.state.ws_problems.indexOf(ws) !== -1)) {
				me._show_edit_dialog(this, true);
				return;
			}
			me._show_edit_dialog(this);
		});

		m.on("click", ".round-slot-empty.addable", function () {
			if (me.state.mode !== "Edit Schedule") return;
			var slot = this.closest(".round-slot");
			if (!slot) return;
			var row = slot.closest("tr");
			var ws = row ? row.dataset.workstation : "";
			if (me.state.past_days.indexOf(slot.dataset.day) !== -1 || me.state.ws_problems.indexOf(ws) !== -1) return;
			me._show_add_dialog(slot);
		});

		m.on("click", ".note-slot, .pack-slot", function () {
			if (me.state.mode !== "Edit Schedule") return;
			var cell = this;
			var day = cell.dataset.day;
			var row = cell.closest("tr");
			var ws = row ? row.dataset.workstation : "";
			if (me.state.past_days.indexOf(day) !== -1 || me.state.ws_problems.indexOf(ws) !== -1) return;
			var field = cell.classList.contains("note-slot") ? "recipe_note" : "pack_remark";
			me._show_inline_edit(cell, row.dataset.workstation, day, field);
		});

	}

	_read_inputs() {
		var m = this.page.main;
		this.state.year = parseInt(m.find("#schedule-year").val(), 10) || new Date().getFullYear();
		this.state.week = parseInt(m.find("#schedule-week").val(), 10) || this.state.week;
		this.state.mode = m.find("#schedule-mode").val() || "View Schedule";
		this._update_submit_btn();
	}

	_sync_inputs() {
		this.page.main.find("#schedule-year").val(this.state.year);
		this.page.main.find("#schedule-week").val(this.state.week);
		this._update_action_btns();
	}

	_update_submit_btn() {
		var btn = this.page.main.find("#schedule-submit-btn");
		var has_past = this.state.past_days && this.state.past_days.length > 0;
		btn.toggle(this.state.mode !== "View Schedule" && !has_past);
	}

	_update_action_btns() {
		this._update_submit_btn();
	}

	_update_mode_selector() {
		var sel = this.page.main.find("#schedule-mode");
		var all_past = this.state.past_days && this.state.past_days.length === this.state.days.length;
		var edit_opt = sel.find('option[value="Edit Schedule"]');
		if (all_past) {
			edit_opt.prop("disabled", true);
			if (this.state.mode === "Edit Schedule") {
				sel.val("View Schedule");
				this.state.mode = "View Schedule";
				this._update_action_btns();
			}
		} else {
			edit_opt.prop("disabled", false);
		}
	}

	// ══════════════════════════════════════════════════════════════
	//  WEEK HELPERS
	// ══════════════════════════════════════════════════════════════

	_compute_iso_week(date) {
		var d = new Date(date);
		d.setHours(0, 0, 0, 0);
		d.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7));
		var week1 = new Date(d.getFullYear(), 0, 4);
		this.state.week =
			1 + Math.round(((d - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
		this.state.year = d.getFullYear();
	}

	_set_week_monday() {
		var y = this.state.year,
			w = this.state.week;
		var jan4 = new Date(y, 0, 4);
		var jan4_day = (jan4.getDay() + 6) % 7;
		var mon = new Date(jan4);
		mon.setDate(jan4.getDate() - jan4_day + (w - 1) * 7);
		this.state.week_monday = mon;
	}

	_fmt(date) {
		var y = date.getFullYear();
		var m = String(date.getMonth() + 1).padStart(2, "0");
		var d = String(date.getDate()).padStart(2, "0");
		return y + "-" + m + "-" + d;
	}

	// ══════════════════════════════════════════════════════════════
	//  DATA
	// ══════════════════════════════════════════════════════════════

	_load_week() {
		var me = this;
		this._read_inputs();
		this._set_week_monday();
		if (!this.state.week || !this.state.year) {
			frappe.msgprint(__("Select year and week first."));
			return;
		}
		me._set_status(__("Loading…"));

		frappe.call({
			method: "caf.caf.page.production_schedule.production_schedule.get_week_data",
			args: {
				year: this.state.year,
				week_number: this.state.week,
				mode: this.state.mode,
			},
			freeze: true,
			freeze_message: __("Loading week…"),
			callback: function (r) {
				try {
					if (r.message) {
						me.state.workstations = r.message.workstations || [];
						me.state.ws_problems = [];
						me.state.workstations.forEach(function (w) {
							if (w.status === "Problem") me.state.ws_problems.push(w.name);
						});
						me.state.days = r.message.days || [];
						me.state.day_labels = r.message.day_labels || [];
						me.state.dp_names = r.message.dp_names || {};
						me.state.schedule = r.message.schedule || {};

						var today_str = me._fmt(new Date());
						me.state.past_days = [];
						me.state.days.forEach(function (d) {
							if (d < today_str) me.state.past_days.push(d);
						});
						me._update_mode_selector();

						if (!me.state.workstations.length && !me.state.days.length) {
							me._set_status(__("No data for this week."));
							return;
						}

						me._render_board();
						me._update_action_btns();
						me._render_week_info();
						me._set_status("");
					} else {
						me._set_status(__("Empty response from server."));
					}
				} catch (e) {
					console.error("Production schedule render error:", e);
					me._set_status(__("Render error: ") + e.message);
				}
			},
			error: function (err) {
				me._set_status(__("Error loading data."));
				console.error(err);
			},
		});
	}

	_set_status(msg) {
		this.page.main.find("#schedule-status").text(msg);
	}

	_render_week_info() {
		if (!this.state.week_monday) return;
		var mon = this.state.week_monday;
		var sat = new Date(mon);
		sat.setDate(mon.getDate() + 5);
		var mn = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
		this.page.main
			.find("#schedule-week-range")
			.text(mn[mon.getMonth()] + " " + mon.getDate() + " – " + mn[sat.getMonth()] + " " + sat.getDate());
		this.page.set_title(__("Production Schedule") + " — W" + this.state.week);
	}

	// ══════════════════════════════════════════════════════════════
	//  GRID RENDERING
	// ══════════════════════════════════════════════════════════════

	_render_board() {
		var me = this;
		var board = this.page.main.find("#schedule-board");
		board.empty();
		this._destroy_sortable();

		if (!this.state.days.length) {
			board.html('<div class="schedule-empty">' + __("No data for this week.") + "</div>");
			return;
		}

		var html = '<table class="schedule-table" role="grid"><thead>';

		// Row 1 — day names
		html += '<tr><th class="schedule-ws-header" rowspan="2" scope="col">' + __("Workstation") + "</th>";
		for (var di = 0; di < this.state.days.length; di++) {
			var day = this.state.days[di];
			var has_dp = this.state.dp_names[day] !== null;
			var cls = has_dp ? " schedule-has-dp" : " schedule-no-dp";
			var is_past = me.state.past_days.indexOf(day) !== -1;
			var past_cls = is_past ? " schedule-past-day" : "";
			html +=
				'<th colspan="5" class="schedule-day-header' +
				cls +
				past_cls +
				'" scope="colgroup">' +
				this.state.day_labels[di] +
				"</th>";
		}
		html += "</tr>";

		// Row 2 — sub-columns
		html += "<tr>";
		for (var di = 0; di < this.state.days.length; di++) {
			html +=
				'<th class="schedule-sub-col schedule-col-round" scope="col">R1</th>' +
				'<th class="schedule-sub-col schedule-col-round" scope="col">R2</th>' +
				'<th class="schedule-sub-col schedule-col-round" scope="col">R3</th>' +
				'<th class="schedule-sub-col schedule-col-note" scope="col">' + __("Note") + "</th>" +
				'<th class="schedule-sub-col schedule-col-pack" scope="col">' + __("Pack") + "</th>";
		}
		html += "</tr></thead><tbody>";

		var last_class = -1;
		for (var wi = 0; wi < this.state.workstations.length; wi++) {
			var ws = this.state.workstations[wi];
			var ws_schedule = this.state.schedule[ws.name] || {};
			var row_cls = "";
			if (ws.ws_class !== last_class) {
				row_cls = ' class="schedule-section-start"';
				last_class = ws.ws_class;
			}
			var is_ws_problem = me.state.ws_problems.indexOf(ws.name) !== -1;
			if (is_ws_problem) {
				row_cls = row_cls ? row_cls.replace('class="', 'class="ws-problem ') : ' class="ws-problem"';
			}
			html += '<tr data-workstation="' + me._escape(ws.name) + '"' + row_cls + ">";
			html += '<td class="schedule-ws-label" scope="row"><a href="/app/workstation/' + encodeURIComponent(ws.name) + '" target="_blank">' + me._escape(ws.name) + "</a></td>";

			for (var di = 0; di < this.state.days.length; di++) {
				var day = this.state.days[di];
				var is_past_cell = me.state.past_days.indexOf(day) !== -1;
				var past_cell_cls = is_past_cell ? " schedule-past-day" : "";
				var info = ws_schedule[day] || {
					date_label: "",
					has_dp: false,
					dp_name: null,
					rounds: { 1: null, 2: null, 3: null },
					note: "",
					pack: "",
				};

				for (var rn = 1; rn <= 3; rn++) {
					var r = info.rounds[rn];
					var no_dp_cls = !info.has_dp ? " schedule-no-dp" : "";
					var ws_problem_cls = is_ws_problem ? " ws-problem" : "";
					html +=
						'<td class="schedule-col-round round-slot' +
						no_dp_cls +
						past_cell_cls +
						ws_problem_cls +
						'" data-workstation="' +
						me._escape(ws.name) +
						'" data-day="' +
						day +
						'" data-round="' +
						rn +
						'" data-has-dp="' +
						info.has_dp +
						'">';
					html += r ? me._render_round_item(r, info.dp_name) : me._render_empty_slot(info.has_dp, is_past_cell, is_ws_problem);
					html += "</td>";
				}

				var note_esc = me._escape(info.note || "");
				html +=
					'<td class="schedule-col-note note-slot' +
					past_cell_cls +
					ws_problem_cls +
					'" data-day="' +
					day +
					'"' +
					(note_esc ? ' title="' + note_esc + '"' : "") +
					">" +
					(info.note ? '<span class="note-text">' + note_esc + "</span>" : '<span aria-hidden="true">—</span>') +
					"</td>";

				var pack_esc = me._escape(info.pack || "");
				html +=
					'<td class="schedule-col-pack pack-slot' +
					past_cell_cls +
					ws_problem_cls +
					'" data-day="' +
					day +
					'"' +
					(pack_esc ? ' title="' + pack_esc + '"' : "") +
					">" +
					(info.pack ? '<span class="pack-text">' + pack_esc + "</span>" : '<span aria-hidden="true">—</span>') +
					"</td>";
			}
			html += "</tr>";
		}

		html += "</tbody></table>";
		board.html(html);

		if (this.state.mode === "Edit Schedule") {
			this._try_init_sortable();
		}
		this._link_paired_items();
		this._render_status_summary();
	}

	_render_status_summary() {
		var counts = {};
		var total = 0;
		for (var ws in this.state.schedule) {
			for (var day in this.state.schedule[ws]) {
				var info = this.state.schedule[ws][day];
				for (var rn in info.rounds) {
					var r = info.rounds[rn];
					if (r && r.status) {
						counts[r.status] = (counts[r.status] || 0) + 1;
						total++;
					}
				}
			}
		}
		var html = "";
		if (total === 0) {
			html = '<span class="summary-none">' + __("No statuses set") + "</span>";
		} else {
			var order = ["New Schedule", "Change Slot", "Rearrange", "Recipe Change", "Pack Change", "Only Remark", "Cancelled"];
			for (var i = 0; i < order.length; i++) {
				var s = order[i];
				if (counts[s]) {
					var emoji = this._status_emoji(s);
					html += '<span class="summary-chip" data-status="' + s + '">' + emoji + " " + s + " " + counts[s] + "</span>";
				}
			}
		}
		this.page.main.find("#schedule-summary").html(html);
	}

	_link_paired_items() {
		var items = this.page.main.find(".schedule-item[data-pair-id]:not([data-pair-id=''])");
		var seen = {};
		items.each(function () {
			var pid = this.dataset.pairId;
			if (!pid || seen[pid]) return;
			seen[pid] = true;
			var paired = items.filter('[data-pair-id="' + pid.replace(/"/g, '\\"') + '"]');
			if (paired.length > 1) {
				paired.addClass("schedule-item-paired");
			}
		});
	}

	_render_round_item(r, dp_name) {
		var me = this;
		if (r.recipe === "No Cooking" && !r.status) {
			return '<div class="round-slot-empty addable" role="button" tabindex="0" title="' + __("Add recipe") + '">' + __("No Cooking") + '</div>';
		}
		var emoji = this._status_emoji(r.status);
		var label = r.recipe || __("No Cooking");
		var size_label = r.size ? r.size : "0";
		var pack_json = JSON.stringify(r.pack_items || []);
		var badge_html = r.status
			? '<span class="schedule-item-badge">' + emoji + " " + me._escape(r.status) + "</span>"
			: "";
		var wo_badge_html = r.wo_status
			? '<span class="schedule-item-wo-badge" data-value="' + me._escape(r.wo_status) + '">' + me._escape(r.wo_status) + "</span>"
			: "";
		return (
			'<div class="schedule-item' + (r.status ? ' schedule-item-locked' : '') + '"' +
			' data-item-id="' + (r.id || "") + '"' +
			' data-dp-name="' + me._escape(dp_name || "") + '"' +
			' data-recipe="' + me._escape(r.recipe || "") + '"' +
			' data-size="' + (r.size || 0) + '"' +
			' data-status="' + (r.status || "") + '"' +
			' data-pair-id="' + me._escape(r.pair_id || "") + '"' +
			' data-production-type="' + me._escape(r.production_type || "") + '"' +
			' data-cook-time="' + me._escape(r.cook_time || "") + '"' +
			' data-cook-station="' + me._escape(r.cook_station || "") + '"' +
			' data-cook-round="' + (r.cook_round || "1") + '"' +
			' data-yield="' + (r.yield || 0) + '"' +
			' data-link-id="' + me._escape(r.link_id || "") + '"' +
			' data-required-date="' + me._escape(r.required_date || "") + '"' +
			' data-urgent="' + (r.urgent ? "1" : "0") + '"' +
			' data-pack-count="' + (r.pack_count || 0) + '"' +
			' data-pack-items="' + me._escape(pack_json) + '"' +
			' data-recipe-note="' + me._escape(r.recipe_note || "") + '"' +
			' data-production-plane="' + me._escape(r.production_plane || "") + '"' +
			' data-mr-reference="' + me._escape(r.mr_reference || "") + '"' +
			' data-wo-status="' + me._escape(r.wo_status || "") + '"' +
			' role="button" tabindex="0"' +
			' title="' +
			me._escape(label) +
			(r.size ? " | " + __("Size") + ": " + r.size : "") +
			(r.status ? " | " + r.status : "") +
			'">' +
			'<span class="schedule-item-status" aria-hidden="true">' + emoji + "</span>" +
			'<span class="schedule-item-body">' +
			'<span class="schedule-item-name">' + me._escape(label) + "</span>" +
			badge_html +
			wo_badge_html +
			"</span>" +
			'<span class="schedule-item-size">' + size_label + "</span>" +
			"</div>"
		);
	}

	_render_empty_slot(has_dp, is_past, is_ws_problem) {
		if (this.state.mode === "Edit Schedule" && has_dp && !is_past && !is_ws_problem) {
			return '<div class="round-slot-empty addable" role="button" tabindex="0" title="' + __("Add recipe") + '">+</div>';
		}
		return '<div class="round-slot-empty" aria-hidden="true">—</div>';
	}

	_status_emoji(status) {
		return (
			{
				"New Schedule": "🟢",
				"Recipe Change": "🩷",
				Cancelled: "🔴",
				"Change Slot": "🔵",
				Rearrange: "🔶",
				"Only Remark": "🟣",
				"Pack Change": "🩷",
			}[status] || ""
		);
	}

	_escape(str) {
		if (!str) return "";
		return String(str)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;");
	}

	_poll_row_status(item_id, callback, max_attempts) {
		if (max_attempts === undefined) max_attempts = 12;
		var attempts = 0;
		var me = this;
		var interval = setInterval(function () {
			attempts++;
			frappe.call({
				method: "caf.caf.page.production_schedule.production_schedule.get_row_status",
				args: { item_id: item_id },
				callback: function (r) {
					var status = r.message ? r.message.wo_status : "";
					if (status !== "Processing" || attempts >= max_attempts) {
						clearInterval(interval);
						if (callback) callback(status);
					}
				},
			});
		}, 5000);
	}

	_apply_dialog_restrictions(d, status_val, is_no_cook_val) {
		var ALWAYS_READ_ONLY = ['cook_station', 'cook_round', 'yield', 'total_output', 'mr_reference', 'production_plane'];
		var config = {};
		var dlg = d;

		function lock_all() {
			Object.keys(dlg.fields_dict).forEach(function (fn) {
				var f = dlg.fields_dict[fn];
				if (f && f.df && f.df.fieldtype !== "Section Break" && f.df.fieldtype !== "Column Break" && f.df.fieldtype !== "HTML") {
					config[fn] = 1;
				}
			});
		}

		if (status_val === "New Schedule") {
			if (is_no_cook_val) {
				// all editable
			}
		} else if (status_val === "Recipe Change") {
			// all editable
		} else if (status_val === "" || status_val === "Cancelled") {
			lock_all();
			config.status = 0;
		} else if (status_val === "Pack Change") {
			lock_all();
			config.number_of_pack = 0;
			for (var i = 1; i <= 7; i++) {
				var s = i === 1 ? "" : "_" + i;
				config["pack_name" + s] = 0;
				config["pack_qty" + s] = 0;
				config["pack_remark" + s] = 0;
			}
			config.status = 0;
		} else if (["Rearrange", "Change Slot"].includes(status_val)) {
			lock_all();
			config.recipe_note = 0;
			for (var i = 1; i <= 7; i++) {
				var s = i === 1 ? "" : "_" + i;
				config["pack_remark" + s] = 0;
			}
			config.status = 0;
		} else if (status_val === "Only Remark") {
			lock_all();
			config.recipe_note = 0;
			for (var i = 1; i <= 7; i++) {
				var s = i === 1 ? "" : "_" + i;
				config["pack_remark" + s] = 0;
			}
			config.status = 0;
		} else if (status_val === "Single WO") {
			lock_all();
			config.recipe = 0;
			config.size = 0;
			config.status = 0;
		} else {
			// all editable (unknown status or no status)
		}

		if (is_no_cook_val && !["New Schedule", "Single WO", "Recipe Change"].includes(status_val)) {
			config.recipe = 1;
			config.size = 1;
		}

		if (status_val && status_val !== "Cancelled") {
			if (!(status_val === "New Schedule" && is_no_cook_val)) {
				config.status = 0;
			}
		}

		var recipe_val = dlg.get_value("recipe");
		var no_recipe = !recipe_val || recipe_val === "No Cooking";
		if (no_recipe) {
			var except = ["status"];
			if (status_val === "New Schedule") except.push("recipe");
			Object.keys(dlg.fields_dict).forEach(function (fn) {
				var f = dlg.fields_dict[fn];
				if (f && f.df && f.df.fieldtype !== "Section Break" && f.df.fieldtype !== "Column Break" && f.df.fieldtype !== "HTML") {
					if (except.indexOf(fn) === -1 && ALWAYS_READ_ONLY.indexOf(fn) === -1) {
						config[fn] = 1;
					}
				}
			});
		}

		var size_val = parseFloat(dlg.get_value("size")) || 0;
		if (size_val === 0) {
			config.number_of_pack = 1;
			for (var i = 1; i <= 7; i++) {
				var s = i === 1 ? "" : "_" + i;
				config["pack_name" + s] = 1;
				config["pack_qty" + s] = 1;
				config["pack_remark" + s] = 1;
			}
		}

		Object.keys(dlg.fields_dict).forEach(function (fn) {
			var field = dlg.get_field(fn);
			if (field && field.df && field.df.fieldtype !== "Section Break" && field.df.fieldtype !== "Column Break" && field.df.fieldtype !== "HTML") {
				var value = config[fn] !== undefined ? config[fn] : 0;
				if (value === 0 && ALWAYS_READ_ONLY.indexOf(fn) !== -1) {
					return;
				}
				field.df.read_only = value;
				field.refresh();
			}
		});
	}

	_apply_add_dialog_restrictions(d, status_val, is_no_cook_val) {
		var ALWAYS_READ_ONLY = ['cooker', 'round', 'yield', 'total_output', 'mr_reference', 'production_plane'];
		var config = {};
		var dlg = d;

		function lock_all() {
			Object.keys(dlg.fields_dict).forEach(function (fn) {
				var f = dlg.fields_dict[fn];
				if (f && f.df && f.df.fieldtype !== "Section Break" && f.df.fieldtype !== "Column Break" && f.df.fieldtype !== "HTML") {
					config[fn] = 1;
				}
			});
		}

		if (status_val === "New Schedule") {
			if (is_no_cook_val) {
				// all editable
			}
		} else if (status_val === "Recipe Change") {
			// all editable
		} else if (status_val === "" || status_val === "Cancelled") {
			lock_all();
			config.produ_status = 0;
		} else if (status_val === "Pack Change") {
			lock_all();
			config.pack_count = 0;
			for (var i = 1; i <= 7; i++) {
				var s = i === 1 ? "" : "_" + i;
				config["pack_name" + s] = 0;
				config["pack_qty" + s] = 0;
				config["pack_remark" + s] = 0;
			}
			config.produ_status = 0;
		} else if (["Rearrange", "Change Slot"].includes(status_val)) {
			lock_all();
			config.recipe_note = 0;
			for (var i = 1; i <= 7; i++) {
				var s = i === 1 ? "" : "_" + i;
				config["pack_remark" + s] = 0;
			}
			config.produ_status = 0;
		} else if (status_val === "Only Remark") {
			lock_all();
			config.recipe_note = 0;
			for (var i = 1; i <= 7; i++) {
				var s = i === 1 ? "" : "_" + i;
				config["pack_remark" + s] = 0;
			}
			config.produ_status = 0;
		} else if (status_val === "Single WO") {
			lock_all();
			config.recipe = 0;
			config.size = 0;
			config.produ_status = 0;
		} else {
			// all editable (unknown status or no status)
		}

		if (is_no_cook_val && !["New Schedule", "Single WO", "Recipe Change"].includes(status_val)) {
			config.recipe = 1;
			config.size = 1;
		}

		if (status_val && status_val !== "Cancelled") {
			if (!(status_val === "New Schedule" && is_no_cook_val)) {
				config.produ_status = 0;
			}
		}

		var recipe_val = dlg.get_value("recipe");
		var no_recipe = !recipe_val || recipe_val === "No Cooking";
		if (no_recipe) {
			Object.keys(dlg.fields_dict).forEach(function (fn) {
				var f = dlg.fields_dict[fn];
				if (f && f.df && f.df.fieldtype !== "Section Break" && f.df.fieldtype !== "Column Break" && f.df.fieldtype !== "HTML") {
					if (fn !== "recipe" && fn !== "produ_status") {
						config[fn] = 1;
					}
				}
			});
		}

		var size_val = parseFloat(dlg.get_value("size")) || 0;
		if (size_val === 0) {
			config.pack_count = 1;
			for (var i = 1; i <= 7; i++) {
				var s = i === 1 ? "" : "_" + i;
				config["pack_name" + s] = 1;
				config["pack_qty" + s] = 1;
				config["pack_remark" + s] = 1;
			}
		}

		Object.keys(dlg.fields_dict).forEach(function (fn) {
			var field = dlg.get_field(fn);
			if (field && field.df && field.df.fieldtype !== "Section Break" && field.df.fieldtype !== "Column Break" && field.df.fieldtype !== "HTML") {
				var value = config[fn] !== undefined ? config[fn] : 0;
				if (value === 0 && ALWAYS_READ_ONLY.indexOf(fn) !== -1) {
					return;
				}
				field.df.read_only = value;
				field.refresh();
			}
		});
	}

	// ══════════════════════════════════════════════════════════════
	//  DRAG & DROP  (Edit mode only)
	// ══════════════════════════════════════════════════════════════

	_ensure_sortable() {
		if (typeof Sortable !== "undefined") return;
		if (this._sortable_loading) return;
		this._sortable_loading = true;
		var me = this;
		var script = document.createElement("script");
		script.src = "https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js";
		script.onload = function () {
			me._sortable_loaded = true;
			me._try_init_sortable();
		};
		script.onerror = function () {
			me._sortable_loading = false;
			console.warn("SortableJS failed to load from CDN");
		};
		document.head.appendChild(script);
	}

	_try_init_sortable() {
		if (typeof Sortable === "undefined") {
			var me = this;
			if (!this._sortable_retries) this._sortable_retries = 0;
			if (this._sortable_retries < 30) {
				this._sortable_retries++;
				setTimeout(function () {
					me._try_init_sortable();
				}, 200);
			}
			return;
		}
		this._sortable_retries = 0;
		this._init_sortable();
	}

	_init_sortable() {
		var me = this;
		if (typeof Sortable === "undefined") return;

		var slots = this.page.main.find(".round-slot:not(.schedule-no-dp):not(.schedule-past-day):not(.ws-problem)");
		if (!slots.length) return;

		this._destroy_sortable();
		this._sortables = [];

		slots.each(function () {
			var slot = this;
			var s = new Sortable(slot, {
				group: "ps-schedule",
				animation: 180,
				easing: "cubic-bezier(0.25, 0.46, 0.45, 0.94)",
				removeCloneOnHide: true,
				ghostClass: "schedule-item-ghost",
				dragClass: "schedule-item-drag",
				chosenClass: "schedule-item-chosen",
				filter: ".round-slot-empty",
				onStart: function (evt) {
					me.page.main.find(".schedule-table").addClass("drag-active");
					me._highlight_target_slots(evt.item);
				},
				onEnd: function (evt) {
					me.page.main.find(".schedule-table").removeClass("drag-active");
					me._clear_target_highlights();
					me._handle_drop(evt);
				},
				onMove: function (evt) {
					me._pulse_target_slot(evt.to);
				},
			});
			me._sortables.push(s);
		});
	}

	_destroy_sortable() {
		if (this._sortables) {
			this._sortables.forEach(function (s) {
				s.destroy();
			});
			this._sortables = [];
		}
	}

	_highlight_target_slots(item) {
		var size = $(item).data("size") || 0;
		this.page.main.find(".round-slot:not(.schedule-no-dp):not(.ws-problem)").each(function () {
			$(this).attr("data-drag-size", size);
		});
	}

	_clear_target_highlights() {
		this.page.main
			.find(".round-slot")
			.removeClass("round-slot-pulse drop-invalid")
			.removeAttr("data-drag-size");
	}

	_pulse_target_slot(slot, invalid) {
		var $slot = $(slot);
		$slot.removeClass("round-slot-pulse drop-invalid");
		if (invalid) {
			$slot.addClass("drop-invalid");
			clearTimeout(this._pulse_timer);
			var me = this;
			this._pulse_timer = setTimeout(function () {
				me.page.main.find(".drop-invalid").removeClass("drop-invalid");
			}, 350);
		} else {
			$slot.addClass("round-slot-pulse");
			clearTimeout(this._pulse_timer);
			var me = this;
			this._pulse_timer = setTimeout(function () {
				me.page.main.find(".round-slot-pulse").removeClass("round-slot-pulse");
			}, 350);
		}
	}

	_handle_drop(evt) {
		var me = this;
		var el = evt.item;
		if (!el || !el.classList.contains("schedule-item")) return;

		var from_slot = evt.from;
		var to_slot = evt.to;
		if (!from_slot || !to_slot) return;

		var src_ws = from_slot.dataset.workstation;
		var src_day = from_slot.dataset.day;
		var src_round = from_slot.dataset.round;
		var tgt_ws = to_slot.dataset.workstation;
		var tgt_day = to_slot.dataset.day;
		var tgt_round = to_slot.dataset.round;

		if (src_ws === tgt_ws && src_day === tgt_day && src_round === tgt_round) return;

		if (src_day !== tgt_day) {
			frappe.show_alert({ message: __("Cross-day moves are not allowed."), indicator: "red" });
			me._load_week();
			return;
		}

		var other = $(to_slot).children(".schedule-item").not(el).filter(function () {
				return $(this).data("recipe");
			}).first();
		if (other.length) {
			this._swap_recipes(from_slot, to_slot, el, other[0]);
			return;
		}

		this._do_move_item(el, from_slot, to_slot);
	}

	_swap_recipes(from_slot, to_slot, dragged_el, target_el) {
		var me = this;
		var src_id = dragged_el.dataset.itemId;
		var tgt_id = target_el.dataset.itemId;

		$(from_slot).append(target_el);
		$(from_slot).children(".round-slot-empty").remove();

		frappe.call({
			method: "caf.caf.page.production_schedule.production_schedule.swap_recipes",
			args: { source_id: src_id, target_id: tgt_id },
			freeze: true,
			freeze_message: __("Swapping…"),
			callback: function (r) {
				if (r.message && r.message.success) {
					frappe.show_alert({ message: r.message.message, indicator: "green" });
					me._set_metabase_cookie();
					me._load_week();
				} else {
					frappe.show_alert({ message: __("Swap failed — reloading."), indicator: "red" });
					me._load_week();
				}
			},
			error: function () {
				frappe.show_alert({ message: __("Swap failed — reloading."), indicator: "red" });
				me._load_week();
			},
		});
	}

	_do_move_item(el, from_slot, to_slot) {
		var me = this;
		var item_id = el.dataset.itemId;

		frappe.call({
			method: "caf.caf.page.production_schedule.production_schedule.save_move_item",
			args: {
				item_id: item_id,
				source_date: from_slot.dataset.day,
				target_date: to_slot.dataset.day,
				target_cooker: to_slot.dataset.workstation,
				target_round: parseInt(to_slot.dataset.round, 10),
			},
			freeze: true,
			freeze_message: __("Saving…"),
			callback: function (r) {
				if (r.message && r.message.success) {
					frappe.show_alert({ message: r.message.message, indicator: "green" });
					me._set_metabase_cookie();
					me._load_week();
				} else {
					frappe.show_alert({ message: __("Save failed — reloading."), indicator: "red" });
					me._load_week();
				}
			},
			error: function () {
				frappe.show_alert({ message: __("Save failed — reloading."), indicator: "red" });
				me._load_week();
			},
		});
	}

	_refresh_slot_placeholder(slot) {
		var $slot = $(slot);
		var has_item = $slot.children(".schedule-item").length > 0;
		var $ph = $slot.children(".round-slot-empty");

		if (!has_item) {
			if (!$ph.length) {
				var has_dp = $slot.attr("data-has-dp") === "true";
				if (has_dp) {
					$slot.append(
						'<div class="round-slot-empty addable" role="button" tabindex="0" title="' +
						__("Add recipe") +
						'">+</div>'
					);
				} else {
					$slot.append('<div class="round-slot-empty" aria-hidden="true">—</div>');
				}
			}
		} else {
			$ph.remove();
		}
	}

	_set_metabase_cookie() {
		document.cookie = "trigger_metabase_refresh=1; path=/; max-age=30";
	}

	// ══════════════════════════════════════════════════════════════
	//  DIALOGS  (Edit mode)
	// ══════════════════════════════════════════════════════════════

	_show_edit_dialog(el, is_past) {
		var me = this;
		var item_id = el.dataset.itemId;
		var recipe = el.dataset.recipe;
		var status = el.dataset.status;
		var size = el.dataset.size;
		var production_type = el.dataset.productionType || "";
		var cook_time = el.dataset.cookTime || "";
		var cook_station = el.dataset.cookStation || "";
		var cook_round = el.dataset.cookRound || "1";
		var yield_val = el.dataset.yield || 0;
		var link_id = el.dataset.linkId || "";
		var required_date = el.dataset.requiredDate || "";
		var urgent = el.dataset.urgent === "1";
		var pack_count = parseInt(el.dataset.packCount, 10) || 0;
		var pack_items = [];
		try { pack_items = JSON.parse(el.dataset.packItems || "[]"); } catch (e) {}
		var recipe_note = el.dataset.recipeNote || "";
		var production_plane = el.dataset.productionPlane || "";
		var mr_reference = el.dataset.mrReference || "";
		var dp_name = el.dataset.dpName || "";
		var wo_status = el.dataset.woStatus || "";

		var is_no_cook = !recipe || recipe === "No Cooking";
		var _status_options;
		if (is_no_cook) {
			_status_options = "\nNew Schedule\nChange Slot";
		} else {
			_status_options = "\nRecipe Change\nCancelled\nChange Slot\nRearrange\nOnly Remark\nPack Change\nSingle WO";
		}

		var fields = [
			{ fieldname: "sec_slot", fieldtype: "Section Break", label: __("Slot Info") },
			{
				label: __("Workstation"), fieldname: "cook_station", fieldtype: "Data",
				read_only: 1, default: cook_station,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Cook Round"), fieldname: "cook_round", fieldtype: "Data",
				read_only: 1, default: cook_round,
			},
			{
				label: __("Production Status"), fieldname: "status", fieldtype: "Select",
				options: _status_options, default: status,
			},
			{ fieldname: "sec_prod", fieldtype: "Section Break", label: __("Production") },
			{
				label: __("Recipe"), fieldname: "recipe", fieldtype: "Link",
				options: "Item", default: recipe,
				get_query: function () {
					return { filters: { item_group: ["in", ["Recipe", "WIP Floss"]] } };
				},
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Size"), fieldname: "size", fieldtype: "Float",
				default: parseFloat(size) || 0,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Production Type"), fieldname: "production_type", fieldtype: "Select",
				options: "\nNew\nRecook\nReheat\nRepack", default: production_type,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Urgent Order"), fieldname: "urgent_check", fieldtype: "Check",
				default: urgent ? 1 : 0,
			},
			{ fieldname: "sec_info", fieldtype: "Section Break", label: __("Production Info") },
			{
				label: __("Yield (KG)"), fieldname: "yield", fieldtype: "Float",
				read_only: 1, default: parseFloat(yield_val) || 0,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Total Output (KG)"), fieldname: "total_output", fieldtype: "Float",
				read_only: 1, default: 0,
			},
			{ fieldname: "sec_recipe_note", fieldtype: "Section Break", label: __("Recipe Note") },
			{
				label: __("Recipe Note"), fieldname: "recipe_note", fieldtype: "Small Text",
				default: recipe_note,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Number of Packs"), fieldname: "number_of_pack", fieldtype: "Select",
				options: "0\n1\n2\n3\n4\n5\n6\n7", default: String(pack_count || 0),
			},
			{ fieldname: "sec_pack", fieldtype: "Section Break", label: __("Pack Details") },
		];

		for (var i = 1; i <= 7; i++) {
			var pi = pack_items[i - 1] || {};
			var suffix = i === 1 ? "" : "_" + i;
			var pack_label = i === 1 ? __("Pack") : __("Pack {0}", [i]);
			(function (sfx, defaults) {
				fields.push({
					label: pack_label + " — " + __("Name"), fieldname: "pack_name" + sfx,
					fieldtype: "Link", options: "Item", default: defaults.name || "",
					get_query: function () {
						var dlg = cur_dialog;
						var cur_recipe = dlg ? dlg.get_value("recipe") : "";
						if (!cur_recipe) return { filters: { name: ["=", ""] } };
						var excluded = [];
						for (var j = 1; j <= 7; j++) {
							var s = j === 1 ? "" : "_" + j;
							if (s !== sfx) {
								var v = dlg ? dlg.get_value("pack_name" + s) : "";
								if (v) excluded.push(v);
							}
						}
						return {
							query: "caf.caf.doctype.daily_production.daily_production.get_packs_for_recipe",
							filters: { recipe_name: cur_recipe, excluded_items: excluded },
						};
					},
				});
			})(suffix, pi);
		}

		fields.push({ fieldtype: "Column Break" });

		for (var i = 1; i <= 7; i++) {
			var pi = pack_items[i - 1] || {};
			var suffix = i === 1 ? "" : "_" + i;
			var pack_label = i === 1 ? __("Pack") : __("Pack {0}", [i]);
			fields.push({
				label: pack_label + " — " + __("QTY"), fieldname: "pack_qty" + suffix,
				fieldtype: "Float", default: pi.qty || 0,
			});
		}

		fields.push({ fieldtype: "Column Break" });

		for (var i = 1; i <= 7; i++) {
			var pi = pack_items[i - 1] || {};
			var suffix = i === 1 ? "" : "_" + i;
			var pack_label = i === 1 ? __("Pack") : __("Pack {0}", [i]);
			fields.push({
				label: pack_label + " — " + __("Remark"), fieldname: "pack_remark" + suffix,
				fieldtype: "Data", default: pi.remark || "",
			});
		}

		fields.push(
			{ fieldname: "sec_note", fieldtype: "Section Break", label: __("System Info") },
			{
				label: __("Link ID"), fieldname: "link_id", fieldtype: "Data",
				read_only: 1, default: link_id,
			},
			{
				label: __("WO Status"), fieldname: "wo_status", fieldtype: "Data",
				read_only: 1, default: wo_status,
			},
			{
				label: __("MR Reference"), fieldname: "mr_reference", fieldtype: "Data",
				read_only: 1, default: mr_reference,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Production Plane"), fieldname: "production_plane", fieldtype: "Data",
				read_only: 1, default: production_plane,
			}
		);

		if (!is_past && !is_no_cook) {
			fields.push(
				{ fieldname: "sec_actions", fieldtype: "Section Break", label: __("Actions") },
				{
					label: __("Cancel Recipe"), fieldname: "btn_cancel", fieldtype: "Button",
					click: function () {
						if (status === "Cancelled") {
							frappe.msgprint(__("This item is already cancelled."));
							return;
						}
						frappe.confirm(__("Cancel this recipe? Existing WOs will be cancelled."), function () {
							frappe.call({
								method: "caf.caf.page.production_schedule.production_schedule.cancel_item",
								args: { item_id: item_id },
								freeze: true,
								callback: function (r) {
									if (r.message && r.message.success) {
										frappe.show_alert({ message: r.message.message, indicator: "green" });
										d.hide();
										me._load_week();
										me._poll_row_status(item_id, function () {
											me._load_week();
										});
									} else {
										frappe.show_alert({ message: r.message.message, indicator: "orange" });
									}
								},
							});
						});
					},
				},
			);
		}

		// ── Apply edit restrictions matching DP form's apply_edit_restrictions ──

		if (is_past) {
			fields = fields.map(function (f) {
				if (f.fieldname && f.fieldtype !== "Section Break" && f.fieldtype !== "Column Break" && f.fieldtype !== "HTML") {
					return Object.assign({}, f, { read_only: 1 });
				}
				return f;
			});
		}

		var save_fields = [
			{ field: "recipe_name", dialog_field: "recipe" },
			{ field: "produ_status", dialog_field: "status" },
			{ field: "size", dialog_field: "size" },
			{ field: "number_of_pack", dialog_field: "number_of_pack" },
			{ field: "production_type", dialog_field: "production_type" },
			{ field: "urgent_check", dialog_field: "urgent_check" },
		];
		for (var i = 1; i <= 7; i++) {
			var suffix = i === 1 ? "" : "_" + i;
			save_fields.push({ field: "pack_name" + suffix, dialog_field: "pack_name" + suffix });
			save_fields.push({ field: "pack_qty" + suffix, dialog_field: "pack_qty" + suffix });
			save_fields.push({ field: "pack_remark" + suffix, dialog_field: "pack_remark" + suffix });
		}
		save_fields.push(
			{ field: "recipe_note", dialog_field: "recipe_note" },
		);

		var dialog_opts = {
			title: (is_past ? __("View: ") : __("Edit: ")) + recipe,
			fields: fields,
			on_page_show: function () {
				var pc = parseInt(this.get_value("number_of_pack")) || 0;
				for (var i = 1; i <= 7; i++) {
					var s = i === 1 ? "" : "_" + i;
					var show = i <= pc;
					["pack_name", "pack_qty", "pack_remark"].forEach(function (p) {
						$(this.wrapper).find('[data-fieldname="' + p + s + '"]').toggle(show);
					}, this);
				}
			},
		};

		if (!is_past) {
			dialog_opts.primary_action_label = __("Save");
			dialog_opts.primary_action = function (values) {
				if (document.activeElement && document.activeElement !== document.body) {
					document.activeElement.blur();
				}
				values = d.get_values();
				if (!values) return;
				var recipe_val = values.recipe;
				var status_val = values.status || "";
				var size_val = parseFloat(values.size) || 0;
				var nop = parseInt(values.number_of_pack) || 0;
				if (recipe_val && recipe_val !== "No Cooking" && size_val === 0) {
					frappe.msgprint(__("Size is required when a recipe is set."));
					return;
				}
				if (["New Schedule", "Recipe Change"].includes(status_val) && nop >= 1 && !values.pack_name) {
					frappe.msgprint(__("Pack 1 Name is required."));
					return;
				}
				var to_save = [];
				save_fields.forEach(function (sf) {
					var val = values[sf.dialog_field];
					if (val !== undefined) {
						to_save.push({ field: sf.field, value: val });
					}
				});
				me._save_item_fields(item_id, to_save, function (ok) {
					if (ok) {
						if (status_val === "Recipe Change" && recipe_val !== recipe) {
							frappe.call({
								method: "caf.caf.page.production_schedule.production_schedule.process_recipe_change",
								args: { item_id: item_id },
							});
						}
						frappe.call({
							method: "caf.caf.page.production_schedule.production_schedule.process_dp_updates",
							args: { item_id: item_id },
						});
					}
					me._load_week();
					me._poll_row_status(item_id, function () {
						me._load_week();
					});
				});
				d.hide();
			};
		}
		var d = new frappe.ui.Dialog(dialog_opts);
		d.show();

		$(d.wrapper).find("form").on("submit", function (e) {
			e.preventDefault();
		});

		if (!is_past) {
			$(d.wrapper).on("change", "[data-fieldname='status']", function () {
				var new_status = d.get_value("status") || "";
				var recipe_val = d.get_value("recipe");
				var no_cook = !recipe_val || recipe_val === "No Cooking";
				me._apply_dialog_restrictions(d, new_status, no_cook);
			});
			var recipe_f = d.get_field("recipe");
			var _on_recipe_change = function () {
				var recipe_val = d.get_value("recipe");
				var no_cook = !recipe_val || recipe_val === "No Cooking";
				var status_field = d.get_field("status");
				if (status_field) {
					if (no_cook) {
						status_field.df.options = mr_reference ? "\nChange Slot" : "\nNew Schedule\nChange Slot";
					} else {
						var opts = "\nRecipe Change\nCancelled\nChange Slot\nRearrange\nOnly Remark\nPack Change\nSingle WO";
						if (!mr_reference) {
							opts = "\nNew Schedule" + opts;
						}
						status_field.df.options = opts;
					}
					status_field.set_options();
				}
			var cur_status = d.get_value("status") || "";
			me._apply_dialog_restrictions(d, cur_status, no_cook);
			if (cur_status === "Recipe Change" && recipe_val !== recipe) {
				d.set_value("size", 0);
				d.set_value("number_of_pack", "1");
				for (var i = 1; i <= 7; i++) {
					var s = i === 1 ? "" : "_" + i;
					d.set_value("pack_name" + s, "");
					d.set_value("pack_qty" + s, 0);
					d.set_value("pack_remark" + s, "");
				}
			}
			if (!no_cook) {
					frappe.call({
						method: "caf.caf.page.production_schedule.production_schedule.get_recipe_bom_data",
						args: { recipe_name: recipe_val },
						callback: function (r) {
							if (r.message) {
								var y = r.message.yield || 0;
								var rm = r.message.raw_materials || 0;
								d.set_value("yield", y);
								d.$wrapper.data("raw_materials", rm);
								var sz = parseFloat(d.get_value("size")) || 0;
								d.set_value("total_output", rm * sz);
							}
						},
					});
				} else {
					d.set_value("yield", 0);
					d.set_value("total_output", 0);
				}
			};
			if (recipe_f && recipe_f.$input) {
				recipe_f.$input.on('awesomplete-selectcomplete', function () {
					setTimeout(_on_recipe_change, 50);
				});
				recipe_f.$input.on('focusout', function () {
					setTimeout(_on_recipe_change, 100);
				});
			}
			$(d.wrapper).on("change", "[data-fieldname='recipe']", function () {
				_on_recipe_change();
			});
			_on_recipe_change();
			$(d.wrapper).on("change", "[data-fieldname='size']", function () {
				var new_status = d.get_value("status") || "";
				var recipe_val = d.get_value("recipe");
				var no_cook = !recipe_val || recipe_val === "No Cooking";
				me._apply_dialog_restrictions(d, new_status, no_cook);
				var raw_mat = parseFloat(d.$wrapper.data("raw_materials")) || 0;
				var size_val = parseFloat(d.get_value("size")) || 0;
				d.set_value("total_output", raw_mat * size_val);
			});
			var nop_field = d.get_field("number_of_pack");
			if (nop_field) {
				$(nop_field.$input).on("change", function () {
					var n = parseInt(d.get_value("number_of_pack")) || 0;
					for (var i = 1; i <= 7; i++) {
						var s = i === 1 ? "" : "_" + i;
						var show = i <= n;
						["pack_name", "pack_qty", "pack_remark"].forEach(function (p) {
							$(d.wrapper).find('[data-fieldname="' + p + s + '"]').toggle(show);
						});
					}
				});
				$(nop_field.$input).trigger("change");
			}
			setTimeout(function () {
				me._apply_dialog_restrictions(d, status, is_no_cook);
			}, 100);
			if (recipe && recipe !== "No Cooking") {
				var yv = parseFloat(d.get_value("yield")) || 0;
				if (yv === 0) {
					frappe.call({
						method: "caf.caf.page.production_schedule.production_schedule.get_recipe_bom_data",
						args: { recipe_name: recipe },
						callback: function (r) {
							if (r.message) {
								d.set_value("yield", r.message.yield || 0);
								d.$wrapper.data("raw_materials", r.message.raw_materials || 0);
								var sz = parseFloat(d.get_value("size")) || 0;
								d.set_value("total_output", (r.message.raw_materials || 0) * sz);
							}
						},
					});
				}
			}
		}
	}

	_show_add_dialog(slot) {
		var me = this;
		var ws = slot.dataset.workstation;
		var day = slot.dataset.day;
		var round = parseInt(slot.dataset.round, 10);

		var fields = [
			{ fieldname: "sec_slot", fieldtype: "Section Break", label: __("Slot Info") },
			{
				label: __("Workstation"), fieldname: "cooker", fieldtype: "Data",
				default: ws, read_only: 1,
			},
			{
				label: __("Production Status"), fieldname: "produ_status", fieldtype: "Select",
				options: "\nNew Schedule",
				default: "New Schedule",
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Round"), fieldname: "round", fieldtype: "Select",
				options: "1\n2\n3", default: String(round), read_only: 1,
			},
			
			{ fieldname: "sec_prod", fieldtype: "Section Break", label: __("Production") },
			{
				label: __("Recipe"), fieldname: "recipe", fieldtype: "Link",
				options: "Item", reqd: 1,
				get_query: function () {
					return { filters: { item_group: ["in", ["Recipe", "WIP Floss"]] } };
				},
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Size"), fieldname: "size", fieldtype: "Float",
				default: 0,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Production Type"), fieldname: "production_type", fieldtype: "Select",
				options: "\nNew\nRecook\nReheat\nRepack", default: "New",
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Urgent Order"), fieldname: "urgent_check", fieldtype: "Check",
				default: 0,
			},
			{ fieldname: "sec_info", fieldtype: "Section Break", label: __("Production Info") },
			{
				label: __("Yield"), fieldname: "yield", fieldtype: "Float",
				read_only: 1, default: 0,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Total Output"), fieldname: "total_output", fieldtype: "Float",
				read_only: 1, default: 0,
			},
			{ fieldname: "sec_recipe_note", fieldtype: "Section Break", label: __("Recipe Note") },
			{
				label: __("Number of Packs"), fieldname: "pack_count", fieldtype: "Select",
				options: "0\n1\n2\n3\n4\n5\n6\n7", default: "1",
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Recipe Note"), fieldname: "recipe_note", fieldtype: "Small Text",
			},
			
			{ fieldname: "sec_pack", fieldtype: "Section Break", label: __("Pack Details") },
		];

		for (var i = 1; i <= 7; i++) {
			var suffix = i === 1 ? "" : "_" + i;
			var pack_label = i === 1 ? __("Pack") : __("Pack {0}", [i]);
			(function (sfx) {
				fields.push({
					label: pack_label + " — " + __("Name"), fieldname: "pack_name" + sfx,
					fieldtype: "Link", options: "Item",
					get_query: function () {
						var dlg = cur_dialog;
						var recipe = dlg ? dlg.get_value("recipe") : "";
						if (!recipe) return { filters: { name: ["=", ""] } };
						var excluded = [];
						for (var j = 1; j <= 7; j++) {
							var s = j === 1 ? "" : "_" + j;
							if (s !== sfx) {
								var v = dlg.get_value("pack_name" + s);
								if (v) excluded.push(v);
							}
						}
						return {
							query: "caf.caf.doctype.daily_production.daily_production.get_packs_for_recipe",
							filters: { recipe_name: recipe, excluded_items: excluded },
						};
					},
				});
			})(suffix);
		}

		fields.push({ fieldtype: "Column Break" });

		for (var i = 1; i <= 7; i++) {
			var suffix = i === 1 ? "" : "_" + i;
			var pack_label = i === 1 ? __("Pack") : __("Pack {0}", [i]);
			fields.push({
				label: pack_label + " — " + __("QTY"), fieldname: "pack_qty" + suffix,
				fieldtype: "Float",
			});
		}

		fields.push({ fieldtype: "Column Break" });

		for (var i = 1; i <= 7; i++) {
			var suffix = i === 1 ? "" : "_" + i;
			var pack_label = i === 1 ? __("Pack") : __("Pack {0}", [i]);
			fields.push({
				label: pack_label + " — " + __("Remark"), fieldname: "pack_remark" + suffix,
				fieldtype: "Data",
			});
		}

		fields.push(
			{ fieldname: "sec_note", fieldtype: "Section Break", label: __("System Info") },
			
			{
				label: __("Link ID"), fieldname: "link_id", fieldtype: "Data",
				read_only: 1,
			},
			{
				label: __("MR Reference"), fieldname: "mr_reference", fieldtype: "Data",
				read_only: 1,
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Production Plane"), fieldname: "production_plane", fieldtype: "Data",
				read_only: 1,
			},
		
		);

		var d = new frappe.ui.Dialog({
			title: __("Add Recipe"),
			fields: fields,
			primary_action_label: __("Add"),
			on_page_show: function () {
				var pc = parseInt(this.get_value("pack_count")) || 0;
				for (var i = 1; i <= 7; i++) {
					var s = i === 1 ? "" : "_" + i;
					var show = i <= pc;
					["pack_name", "pack_qty", "pack_remark"].forEach(function (p) {
						$(this.wrapper).find('[data-fieldname="' + p + s + '"]').toggle(show);
					}, this);
				}
			},
			primary_action: function (values) {
				if (document.activeElement && document.activeElement !== document.body) {
					document.activeElement.blur();
				}
				values = d.get_values();
				if (!values) return;
				$(d.wrapper).find(".has-error").removeClass("has-error");
				if (!values.recipe) {
					frappe.msgprint(__("Please select a recipe."));
					return;
				}
				if (!values.size || parseFloat(values.size) <= 0) {
					$(d.wrapper).find('[data-fieldname="size"]').closest(".frappe-control").addClass("has-error");
					frappe.msgprint(__("Please enter a valid size."));
					return;
				}
				var pc = parseInt(values.pack_count, 10) || 0;
				var missing_name = false;
				for (var i = 1; i <= pc; i++) {
					var suffix = i === 1 ? "" : "_" + i;
					if (!values["pack_name" + suffix]) {
						$(d.wrapper).find('[data-fieldname="pack_name' + suffix + '"]').closest(".frappe-control").addClass("has-error");
						missing_name = true;
					}
				}
				if (missing_name) {
					frappe.msgprint(__("All packs must have a pack name."));
					return;
				}
				if (pc > 1) {
					var missing_qty = false;
					for (var i = 1; i <= pc; i++) {
						var suffix = i === 1 ? "" : "_" + i;
						var qty = parseFloat(values["pack_qty" + suffix]) || 0;
						if (qty <= 0) {
							$(d.wrapper).find('[data-fieldname="pack_qty' + suffix + '"]').closest(".frappe-control").addClass("has-error");
							missing_qty = true;
						}
					}
					if (missing_qty) {
						frappe.msgprint(__("All packs must have a quantity when using more than 1 pack."));
						return;
					}
				}
				var args = {
					day: day,
					recipe: values.recipe,
					size: values.size,
					cooker: values.cooker,
					pack_count: values.pack_count,
					round_num: values.round,
					production_type: values.production_type,
					urgent_check: values.urgent_check,
					recipe_note: values.recipe_note,
					production_plane: values.production_plane,
					produ_status: values.produ_status,
				};
				for (var i = 1; i <= 7; i++) {
					var suffix = i === 1 ? "" : "_" + i;
					var val = values["pack_name" + suffix];
					if (val) args["pack_name" + suffix] = val;
					val = values["pack_qty" + suffix];
					if (val) args["pack_qty" + suffix] = val;
					val = values["pack_remark" + suffix];
					if (val) args["pack_remark" + suffix] = val;
				}
				frappe.call({
					method: "caf.caf.page.production_schedule.production_schedule.add_recipe",
					args: args,
					freeze: true,
					freeze_message: __("Adding…"),
					callback: function (r) {
						if (r.message && r.message.success) {
							frappe.show_alert({ message: __("Recipe added"), indicator: "green" });
							me._set_metabase_cookie();
							me._load_week();
							var row_id = r.message.item ? r.message.item.id : null;
							if (row_id) {
								me._poll_row_status(row_id, function () {
									me._load_week();
								});
							}
						} else {
							frappe.msgprint(r.message ? r.message.message : __("Failed to add recipe"));
						}
					},
					error: function () {
						frappe.msgprint(__("Failed to add recipe"));
					},
				});
				d.hide();
			},
		});
		d.show();

		$(d.wrapper).find("form").on("submit", function (e) {
			e.preventDefault();
		});

		var pc_field = d.get_field("pack_count");
		if (pc_field) {
			$(pc_field.$input).on("change", function () {
				var n = parseInt(d.get_value("pack_count")) || 0;
				for (var i = 1; i <= 7; i++) {
					var s = i === 1 ? "" : "_" + i;
					var show = i <= n;
					["pack_name", "pack_qty", "pack_remark"].forEach(function (p) {
						$(d.wrapper).find('[data-fieldname="' + p + s + '"]').toggle(show);
					});
				}
			});
			$(pc_field.$input).trigger("change");
		}

		var recipe_f = d.get_field("recipe");
		if (recipe_f && recipe_f.$input) {
			var _on_recipe_change = function () {
				var dlg = d;
				var recipe_val = dlg.get_value("recipe");
				var no_cook = !recipe_val || recipe_val === "No Cooking";
				var status_field = dlg.get_field("produ_status");
				if (status_field) {
					if (no_cook) {
						status_field.df.options = "\nNew Schedule";
					} else {
						status_field.df.options = "\nNew Schedule\nRecipe Change\nCancelled\nOnly Remark\nPack Change\nSingle WO";
					}
					status_field.set_options();
				}
				var cur_status = dlg.get_value("produ_status") || "";
				me._apply_add_dialog_restrictions(dlg, cur_status, no_cook);
				if (!no_cook) {
					frappe.call({
						method: "caf.caf.page.production_schedule.production_schedule.get_recipe_bom_data",
						args: { recipe_name: recipe_val },
						callback: function (r) {
							if (r.message) {
								var y = r.message.yield || 0;
								var rm = r.message.raw_materials || 0;
								dlg.set_value("yield", y);
								dlg.$wrapper.data("raw_materials", rm);
								var sz = parseFloat(dlg.get_value("size")) || 0;
								dlg.set_value("total_output", rm * sz);
							}
						},
					});
				} else {
					dlg.set_value("yield", 0);
					dlg.set_value("total_output", 0);
				}
			};
			recipe_f.$input.on('awesomplete-selectcomplete', function () {
				setTimeout(_on_recipe_change, 50);
			});
			recipe_f.$input.on('focusout', function () {
				setTimeout(_on_recipe_change, 100);
			});
		}

		var status_f = d.get_field("produ_status");
		if (status_f && !d.get_value("produ_status")) {
			d.set_value("produ_status", "New Schedule");
		}

		$(d.wrapper).on("change", "[data-fieldname='produ_status']", function () {
			var status_val = d.get_value("produ_status") || "";
			var recipe_val = d.get_value("recipe");
			var no_cook = !recipe_val || recipe_val === "No Cooking";
			me._apply_add_dialog_restrictions(d, status_val, no_cook);
		});

		$(d.wrapper).on("change", "[data-fieldname='recipe']", function () {
			_on_recipe_change();
		});

		$(d.wrapper).on("change", "[data-fieldname='size']", function () {
			var status_val = d.get_value("produ_status") || "";
			var recipe_val = d.get_value("recipe");
			var no_cook = !recipe_val || recipe_val === "No Cooking";
			me._apply_add_dialog_restrictions(d, status_val, no_cook);
			var raw_mat = parseFloat(d.$wrapper.data("raw_materials")) || 0;
			var size_val = parseFloat(d.get_value("size")) || 0;
			d.set_value("total_output", raw_mat * size_val);
		});

		setTimeout(function () {
			me._apply_add_dialog_restrictions(d, "New Schedule", true);
		}, 100);
	}

	_show_inline_edit(cell, ws, day, field) {
		var me = this;
		var $cell = $(cell);
		var current = $cell.find("span").text() || "";
		if (current === "—") current = "";

		var label = field === "recipe_note" ? __("Recipe Note") : __("Pack Remarks");

		var d = new frappe.ui.Dialog({
			title: label + " — " + ws + " " + day,
			fields: [
				{
					label: label,
					fieldname: "value",
					fieldtype: "Small Text",
					default: current,
				},
			],
			primary_action_label: __("Save"),
			primary_action: function (values) {
				frappe.call({
					method: "caf.caf.page.production_schedule.production_schedule.save_update_item",
					args: {
						item_id: me._find_item_id_for_ws_day(ws, day),
						field: field,
						value: values.value,
					},
					callback: function (r) {
						if (r.message && r.message.success) {
							frappe.show_alert({ message: __("Saved"), indicator: "green" });
							me._load_week();
						}
					},
				});
				d.hide();
			},
		});
		d.show();
	}

	_find_item_id_for_ws_day(ws, day) {
		var info = this.state.schedule[ws] && this.state.schedule[ws][day];
		if (info) {
			for (var rn = 1; rn <= 3; rn++) {
				if (info.rounds[rn] && info.rounds[rn].id) {
					return info.rounds[rn].id;
				}
			}
		}
		return null;
	}

	_save_item_fields(item_id, fields, callback) {
		if (!fields || fields.length === 0) {
			callback(true);
			return;
		}
		frappe.call({
			method: "caf.caf.page.production_schedule.production_schedule.save_item_fields",
			args: { item_id: item_id, fields: fields },
			callback: function (r) {
				if (r.message && r.message.success) {
					callback(true);
				} else {
					frappe.msgprint(r.message ? r.message.message : __("Save failed"));
					callback(false);
				}
			},
			error: function () {
				frappe.msgprint(__("Save failed"));
				callback(false);
			},
		});
	}

	// ══════════════════════════════════════════════════════════════
	//  VIEW MODE  — open ERPNext
	// ══════════════════════════════════════════════════════════════

	// ══════════════════════════════════════════════════════════════
	//  SUBMIT
	// ══════════════════════════════════════════════════════════════

	_submit_week() {
		var me = this;
		if (!this.state.week_monday) {
			frappe.msgprint(__("Load a week first."));
			return;
		}
		var mon_str = this._fmt(this.state.week_monday);

		frappe.confirm(
			__("Submit all draft DPs for the week starting {0}?", [mon_str]),
			function () {
				frappe.call({
					method: "caf.caf.page.production_schedule.production_schedule.submit_week",
					args: { week_monday: mon_str },
					freeze: true,
					freeze_message: __("Submitting week…"),
					callback: function (r) {
						if (r.message && r.message.success) {
							frappe.show_alert({ message: r.message.message, indicator: "green" });
							me._set_metabase_cookie();
							me.page.main.find("#schedule-mode").val("View Schedule");
							me.state.mode = "View Schedule";
							me._update_submit_btn();
							me._load_week();
						} else {
							frappe.show_alert({ message: r.message.message, indicator: "orange" });
						}
					},
					error: function (err) {
						me._set_status(__("Submit failed."));
						console.error(err);
					},
				});
			}
		);
	}
};