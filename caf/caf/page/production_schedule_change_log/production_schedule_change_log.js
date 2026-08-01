frappe.provide("caf.change_log_combined");

frappe.pages["production-schedule-change-log"].on_page_load = function (wrapper) {
	frappe.change_log_combined = new caf.change_log_combined.ChangeLogCombinedPage(wrapper);
};

caf.change_log_combined.ChangeLogCombinedPage = class ChangeLogCombinedPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Production Schedule — Change Log"),
			single_column: true,
		});
		this.today = frappe.datetime.get_today();
		this.active_filter = "all";
		this.workstation_filter = "all";
		this.all_entries = [];
		this.make();
	}

	make() {
		var me = this;

		me.page.main.html(`
			<div class="pscb-controls">
				<div class="pscb-controls-row">
					<div class="pscb-date-group">
						<label class="pscb-label">${__("Date")}</label>
						<input type="date" class="form-control pscb-date-input" id="pscb-date"
							value="${me.today}" />
					</div>
					<button class="btn btn-primary btn-sm" id="pscb-load-btn">
						<i class="fa fa-search"></i> ${__("Load Changes")}
					</button>
				</div>
			</div>
			<div id="pscb-chips" style="display:none"></div>
			<div id="pscb-results">
				<div class="pscb-empty text-muted text-center" style="padding:60px 0">
					<i class="fa fa-th-large" style="font-size:40px;opacity:0.3"></i>
					<p style="margin-top:12px">${__("Select a date and click Load Changes.")}</p>
				</div>
			</div>
		`);

		me.page.main.find("#pscb-load-btn").on("click", function () { me.load(); });
		me.page.main.find("#pscb-date").on("keydown", function (e) { if (e.which === 13) me.load(); });
		me.page.main.find("#pscb-date").on("change", function () { me.load(); });
	}

	load() {
		var me = this;
		var date = me.page.main.find("#pscb-date").val();
		if (!date) { frappe.msgprint(__("Please select a date.")); return; }

		var results = me.page.main.find("#pscb-results");
		var chips = me.page.main.find("#pscb-chips");
		results.html('<div class="text-muted text-center" style="padding:40px 0"><i class="fa fa-spinner fa-spin"></i> ' + __("Loading…") + '</div>');
		chips.hide();
		me.active_filter = "all";
		me.workstation_filter = "all";

		frappe.call({
			method: "caf.caf.page.production_schedule_change_log.production_schedule_change_log.get_change_log_for_date",
			args: { date: date },
			callback: function (r) {
				var data = r.message || { entries: [], summary: {} };
				me.all_entries = data.entries || [];
				me.render_chips(data.entries, data.summary);
				me.render_grouped(data.entries);
			},
			error: function () {
				results.html('<div class="text-danger text-center" style="padding:40px 0"><i class="fa fa-exclamation-triangle"></i> ' + __("Failed to load change log.") + '</div>');
			},
		});
	}

	render_chips(entries) {
		var me = this;
		var el = me.page.main.find("#pscb-chips");
		if (!entries || !entries.length) { el.hide(); return; }

		var action_counts = {};
		var ws_counts = {};
		for (var i = 0; i < entries.length; i++) {
			var e = entries[i];
			var a = (e.summary && e.summary.indexOf("Added rounds") === 0) ? "Add Rounds" : (e.action_type || "Other");
			action_counts[a] = (action_counts[a] || 0) + 1;
			var ws = e.workstation ? (e.workstation + " / R" + (e.cook_round || 1)) : "__system__";
			ws_counts[ws] = (ws_counts[ws] || 0) + 1;
		}

		var chip_colors = {
			"Edit": "var(--green-500)", "Move": "var(--blue-500)", "Swap": "var(--purple)",
			"Add Recipe": "var(--teal-500)", "Cancel": "var(--red)",
			"Create WO": "var(--orange-500)", "Submit Week": "var(--text-muted)",
			"Add Rounds": "var(--indigo-500)",
		};

		var html = '<div class="pscb-chip-row">';
		html += '<span class="pscb-chip-label">' + __("Action") + '</span>';
		html += '<div class="pscb-chip-list">';
		html += '<div class="pscb-chip pscb-chip-all" data-type="action" data-filter="all">' + __("All") + ' <span class="chip-count">' + entries.length + '</span></div>';
		var action_order = ["Edit","Move","Swap","Add Recipe","Cancel","Create WO","Submit Week","Add Rounds"];
		for (var i = 0; i < action_order.length; i++) {
			var action = action_order[i];
			var count = action_counts[action];
			if (!count) continue;
			var color = chip_colors[action] || "var(--text-muted)";
			html += '<div class="pscb-chip" data-type="action" data-filter="' + frappe.utils.escape_html(action) + '" data-color="' + color + '">' + frappe.utils.escape_html(action) + ' <span class="chip-count">' + count + '</span></div>';
		}
		html += '</div></div>';

		var ws_keys = Object.keys(ws_counts).sort();
		if (ws_keys.length > 1) {
			html += '<div class="pscb-chip-row">';
			html += '<span class="pscb-chip-label">' + __("Workstation") + '</span>';
			html += '<div class="pscb-chip-list">';
			html += '<div class="pscb-chip pscb-chip-all" data-type="ws" data-filter="all">' + __("All") + ' <span class="chip-count">' + entries.length + '</span></div>';
			for (var i = 0; i < ws_keys.length; i++) {
				var key = ws_keys[i];
				var label = key === "__system__" ? __("System actions") : key;
				html += '<div class="pscb-chip" data-type="ws" data-filter="' + frappe.utils.escape_html(key) + '" data-color="var(--gray-600)">' + frappe.utils.escape_html(label) + ' <span class="chip-count">' + ws_counts[key] + '</span></div>';
			}
			html += '</div></div>';
		}

		el.html(html).show();

		el.find(".pscb-chip[data-type='action']").on("click", function () {
			me.active_filter = $(this).data("filter");
			me.highlight_chip(el, "action", me.active_filter);
			me.apply_filter();
		});

		el.find(".pscb-chip[data-type='ws']").on("click", function () {
			me.workstation_filter = $(this).data("filter");
			me.highlight_chip(el, "ws", me.workstation_filter);
			me.apply_filter();
		});

		me.highlight_chip(el, "action", "all");
		me.highlight_chip(el, "ws", "all");
	}

	highlight_chip(el, type, active) {
		el.find(".pscb-chip[data-type='" + type + "']").each(function () {
			var fc = $(this).data("color") || "var(--gray-600)";
			var is_all = $(this).data("filter") === "all";
			var default_bg = type === "action" ? "var(--primary)" : "var(--gray-600)";
			if ($(this).data("filter") === active) {
				$(this).css({background: is_all ? default_bg : fc, color: "#fff", borderColor: is_all ? default_bg : fc});
			} else {
				$(this).css({background: "transparent", color: is_all ? default_bg : fc, borderColor: is_all ? default_bg : fc});
			}
		});
	}

	apply_filter() {
		var me = this;
		var action_f = me.active_filter;
		var ws_f = me.workstation_filter;

		me.page.main.find(".pscb-entry").each(function () {
			var action = $(this).data("action");
			var ws = $(this).data("ws");
			var show = (action_f === "all" || action === action_f) && (ws_f === "all" || ws === ws_f);
			$(this).toggleClass("hidden", !show);
		});

		me.page.main.find(".pscb-group").each(function () {
			var visible = $(this).find(".pscb-entry:not(.hidden)").length;
			$(this).toggleClass("hidden", visible === 0);
			if (visible > 0) $(this).find(".pscb-group-count").text(visible);
		});
	}

	render_grouped(entries) {
		var me = this;
		var container = me.page.main.find("#pscb-results");

		if (!entries || !entries.length) {
			container.html('<div class="pscb-empty text-muted text-center" style="padding:60px 0"><i class="fa fa-th-large" style="font-size:40px;opacity:0.3"></i><p style="margin-top:12px">' + __("No changes found for this date.") + '</p></div>');
			return;
		}

		var groups = {};
		var system_entries = [];

		for (var i = 0; i < entries.length; i++) {
			var e = entries[i];
			if (e.workstation) {
				var key = e.workstation + " / R" + (e.cook_round || 1);
				if (!groups[key]) groups[key] = [];
				groups[key].push(e);
			} else {
				system_entries.push(e);
			}
		}

		var html = '<div class="pscb-groups">';

		var keys = Object.keys(groups).sort();
		for (var k = 0; k < keys.length; k++) {
			var key = keys[k];
			var items = groups[key];
			html += '<div class="pscb-group" data-group="' + frappe.utils.escape_html(key) + '">';
			html += '<div class="pscb-group-header">';
			html += '<span class="mono">' + frappe.utils.escape_html(key) + '</span>';
			html += '<span class="pscb-group-count">' + items.length + '</span>';
			html += '</div>';
			html += '<div class="pscb-group-body">';
			for (var j = 0; j < items.length; j++) {
				html += me.render_entry(items[j]);
			}
			html += '</div></div>';
		}

		if (system_entries.length) {
			html += '<div class="pscb-group" data-group="__system__">';
			html += '<div class="pscb-group-header psca-system">';
			html += '<span>' + __("System actions") + '</span>';
			html += '<span class="pscb-group-count">' + system_entries.length + '</span>';
			html += '</div>';
			html += '<div class="pscb-group-body">';
			for (var j = 0; j < system_entries.length; j++) {
				html += me.render_entry(system_entries[j]);
			}
			html += '</div></div>';
		}

		html += '</div>';
		container.html(html);
	}

	render_entry(log) {
		var when = log.change_datetime ? frappe.datetime.str_to_user(log.change_datetime, "HH:mm") : "";
		var badge_cls = {"Move":"label-primary","Swap":"label-info","Edit":"label-success","Add Recipe":"label-success","Cancel":"label-danger","Create WO":"label-warning","Submit Week":"label-default"};
		var cls = badge_cls[log.action_type] || "label-default";

		// Distinguish "Add Extra Rounds" from generic "Edit"
		var action_label = log.action_type || "";
		if (log.summary && log.summary.indexOf("Added rounds") === 0) {
			action_label = __("Add Rounds");
			cls = "label-info";
		}

		var recipe = log.recipe_name
			? '<span class="pscb-entry-recipe">' + frappe.utils.escape_html(log.recipe_name) + '</span>'
			: "";

		var summary = log.summary
			? '<span class="pscb-entry-recipe">' + frappe.utils.escape_html(log.summary) + '</span>'
			: "";

		var dp = log.dp_name
			? '<a class="pscb-dp-link" href="/app/daily-production/' + frappe.utils.escape_html(log.dp_name) + '">' + frappe.utils.escape_html(log.dp_name) + '</a>'
			: "";

		var ws_key = log.workstation ? log.workstation + " / R" + (log.cook_round || 1) : "__system__";

		var changes_html = "";
		if (log.changes_json) {
			try {
				var parsed = JSON.parse(log.changes_json);
				// Handle "Add Rounds" flat object format
				if (parsed && parsed.added_rounds) {
					changes_html = '<div class="pscb-entry-changes">' + __("Rounds added: {0} (total: {1})", [parsed.added_rounds.join(", "), parsed.total_rounds]) + '</div>';
				} else if (parsed && parsed.length) {
					changes_html = '<div class="pscb-entry-changes"><table class="pscb-diff">';
					for (var j = 0; j < parsed.length; j++) {
						var c = parsed[j];
						var label = this._field_label(c.field);
						changes_html += '<tr><td>' + frappe.utils.escape_html(label) + ':</td><td class="pscb-old">' + frappe.utils.escape_html(String(c.old==null?"—":c.old)) + '</td><td>→</td><td class="pscb-new">' + frappe.utils.escape_html(String(c.new==null?"—":c.new)) + '</td></tr>';
					}
					changes_html += '</table></div>';
				}
			} catch(e) {}
		}

		return '<div class="pscb-entry" data-action="' + frappe.utils.escape_html(log.action_type||"") + '" data-ws="' + frappe.utils.escape_html(ws_key) + '">'
			+ '<div class="pscb-entry-head">'
			+ '<span class="pscb-entry-time">' + when + '</span>'
			+ '<span class="pscb-badge ' + cls + '">' + frappe.utils.escape_html(action_label) + '</span>'
			+ '<span class="pscb-entry-recipe">' + frappe.utils.escape_html(log.changed_by||"") + '</span>'
			+ recipe
			+ summary
			+ '<span class="pscb-entry-dp">' + dp + '</span>'
			+ '</div>'
			+ changes_html
			+ '</div>';
	}

	_field_label(field) {
		var labels = {
			"size": __("Size"), "produ_status": __("Status"), "recipe_note": __("Recipe Note"),
			"number_of_pack": __("Pack Count"), "production_type": __("Production Type"),
			"urgent_check": __("Urgent"), "production_plane": __("Production Plan"),
			"recipe_name": __("Recipe"), "recipe_cook_workstaion": __("Workstation"),
			"recipe_cook_round": __("Round"), "pack_name": __("Pack Name"),
			"pack_qty": __("Pack Qty"), "pack_note": __("Pack Note"),
			"recipe_cook_time": __("Cook Time"), "action": __("Action"),
		};
		return labels[field] || field;
	}
};
