// =================================================================
// HELPER FUNCTIONS & OVERLAYS
// =================================================================
console.log("✅ daily_production.js loaded successfully!");

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => { clearTimeout(timeout); func(...args); };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function show_loading_overlay() {
    if ($('#custom-loading-overlay').length) return;
    $('body').append(`
      <div id="custom-loading-overlay" style="
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(255, 255, 255, 0.85); z-index: 9999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
      ">
        <img src="/assets/caf/images/sunny.gif" alt="Loading..." style="width: 120px; height: 120px;">
        <span style="margin-top: 16px; font-size: 16px; color: #333;">Processing...</span>
      </div>
    `);
}

function hide_loading_overlay() {
    $('#custom-loading-overlay').remove();
}

// Global overrides for UI messages to hide overlays
frappe.throw = (function(original_throw) {
    return function(msg) { hide_loading_overlay(); return original_throw.apply(this, arguments); };
})(frappe.throw);

frappe.msgprint = (function(original_msgprint) {
    return function(msg) { hide_loading_overlay(); return original_msgprint.apply(this, arguments); };
})(frappe.msgprint);

$(document).on("ajaxError", function() { hide_loading_overlay(); });


// =================================================================
// VALIDATION & DATA HELPER FUNCTIONS
// =================================================================

// Helper function to control the child table grid view
const setup_production_grid = function(frm) {
    let grid = frm.get_field("production_table").grid;
    if (!grid) return;

    const grid_layout = {
        "recipe_cook_workstaion": 2,
        "recipe_cook_round": 1,
        "produ_status": 3,
        "recipe_name": 2,
        "size": 1,
        "custom_yield": 1,
        "total_input": 1,
        "total_output": 1,
        "number_of_pack": 1
    };

    grid.docfields.forEach(df => {
        if (df.fieldname === "rq_status") {
            df.hidden = 1;
            df.in_list_view = 0;
            df.columns = 0;
        } else if (grid_layout[df.fieldname]) {
            df.in_list_view = 1;
            df.columns = grid_layout[df.fieldname];
        } else {
            df.in_list_view = 0;
            df.columns = 0;
        }
    });

    grid.visible_columns = [];
    grid.setup_visible_columns();
    grid.refresh();

    setTimeout(() => {
        if (grid.header_row) {
            grid.header_row.refresh();
        }
        if (grid.wrapper) {
            grid.wrapper.find('.grid-pagination-functions').css('display', 'none');
        }
        if (typeof color_recipe_groups === "function") {
            color_recipe_groups(frm);
        }
    }, 250);
};


function color_recipe_groups(frm) {
    const active_recipe_color = '#8EA8BE';
    const grid = frm.get_field("production_table").grid;

    if (!grid || !grid.grid_rows_by_docname || !frm.doc.production_table) return;

    Object.values(grid.grid_rows_by_docname).forEach(ui_row => {
        if (ui_row?.wrapper) {
            $(ui_row.wrapper).css("background-color", "");
            $(ui_row.wrapper).find('[data-fieldname="recipe_cook_round"]').css("background-color", "");
            $(ui_row.wrapper).find('[data-fieldname="custom_yield"]').css("background-color", "");
        }
    });

    const rows = frm.doc.production_table;
    let is_active_group = false;

    rows.forEach(row => {
        const recipe = (row.recipe_name || "").trim();

        if (recipe !== "" && recipe.toLowerCase() !== "no cooking") {
            is_active_group = true;
        }
        else if (recipe.toLowerCase() === "no cooking") {
            is_active_group = false;
        }

        const ui_row = grid.grid_rows_by_docname[row.name];

        if (ui_row?.wrapper) {
            // Red tint for problem workstation rows (matching WPD)
            var ws_name = row.recipe_cook_workstaion;
            if (frm._ws_status && ws_name && frm._ws_status[ws_name] === "Problem") {
                $(ui_row.wrapper).css("background-color", "rgba(239, 68, 68, 0.08)");
                $(ui_row.wrapper).css("opacity", "0.65");
                return;
            }

            if (is_active_group) {
                $(ui_row.wrapper).css("background-color", active_recipe_color);
            }

            const round_cell = $(ui_row.wrapper).find('[data-fieldname="recipe_cook_round"]');

            if (row.recipe_cook_round == 1) {
                round_cell.css("background-color", "#E6E6FA");
            } else if (row.recipe_cook_round == 3) {
                round_cell.css("background-color", "#FFB6C1");
            }

            const yield_cell = $(ui_row.wrapper).find('[data-fieldname="custom_yield"]');
            const yield_val = flt(row.custom_yield);
            if (yield_val > 0) {
                yield_cell.css("background-color", "#C8E6C9");
            } else if (row.recipe_name && row.recipe_name !== "No Cooking") {
                yield_cell.css("background-color", "#FFCDD2");
            }
        }
    });
}

const debounced_apply_colors = debounce((frm) => { color_recipe_groups(frm); }, 250);

// Pack weight validation helper — real-time feedback like WPD
function _validate_pack_weights(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row || !row.recipe_name || row.recipe_name === "No Cooking") return;
    const pack_count = parseInt(row.number_of_pack) || 0;
    if (pack_count <= 1) return;
    var packs = [];
    for (let i = 1; i <= pack_count; i++) {
        let s = (i === 1) ? "" : "_" + i;
        let name = row["pack_name" + s];
        let qty = row["pack_qty" + s];
        if (name) packs.push({ name: name, qty: qty || 0 });
    }
    if (packs.length <= 1) return;
    frappe.call({
        method: "caf.caf.page.production_schedule.production_schedule.validate_pack_weights",
        args: { recipe_name: row.recipe_name, size: row.size, packs: packs },
        callback: function(r) {
            if (r.message && !r.message.valid) {
                frappe.show_alert({ message: r.message.message, indicator: 'red' }, 8);
            }
        }
    });
}
const debounced_validate_pack = debounce((frm, cdt, cdn) => { _validate_pack_weights(frm, cdt, cdn); }, 500);

// Poll the DP until the background worker finishes (rq_status no longer Processing), then reload
function poll_dp_processing(frm, attempts) {
    if (attempts === undefined) attempts = 0;
    if (attempts > 20) { frm.reload_doc(); return; }
    frappe.call({
        method: "caf.caf.doctype.daily_production.daily_production.get_dp_row_statuses",
        args: { dp_name: frm.doc.name },
        callback: function(r) {
            var busy = r.message && r.message.any_processing;
            if (busy) {
                setTimeout(function() { poll_dp_processing(frm, attempts + 1); }, 3000);
            } else {
                frm.reload_doc();
                frappe.show_alert({ message: __('✅ Changes processed'), indicator: 'green' });
            }
        }
    });
}

// Run process_manual_updates directly (WPD-style, synchronous with a loading
// page — same as the page's "Create Work Order" button) only when WOs were
// already created ("Create Work Order" clicked, i.e. custom_submit_ref is set).
// Otherwise this is a no-op — the save is just persisted.
function _dp_extract_server_error(r) {
    let msg = "";
    try {
        if (r && r._server_messages) {
            const parsed = JSON.parse(r._server_messages);
            parsed.forEach(function(m) { if (m && m.message) msg += (msg ? " " : "") + m.message; });
        }
    } catch (e) {}
    if (!msg && r && r.exc) msg = String(r.exc);
    return msg || __("Failed to process. Please review and retry.");
}

function _dp_dialog_show_error(d, msg) {
    if (!d) return;
    const el = $(d.wrapper).find(".dp-wo-error");
    if (el.length) {
        el.html(frappe.utils.escape_html ? frappe.utils.escape_html(msg) : msg).show();
    } else {
        frappe.show_alert({ message: msg, indicator: "red" }, 6);
    }
}

function _dp_dialog_clear_error(d) {
    if (!d) return;
    const el = $(d.wrapper).find(".dp-wo-error");
    if (el.length) el.hide().html("");
}

function maybe_process_dp_changes(frm, row_name, dialog, on_success) {
    const finish_success = function() {
        if (dialog) dialog.hide();
        if (typeof on_success === "function") on_success();
    };
    if (!frm.doc.custom_submit_ref) {
        finish_success();
        return;
    }
    // WPD-style: a dialog save only processes the edited row. Rows already
    // marked Done keep their status marker for the planner and are skipped.
    const pending = (frm.doc.production_table || []).filter(function(r) {
        if (row_name && r.name !== row_name) return false;
        if (r.rq_status === "Done") return false;
        if (r.recipe_name === "No Cooking" || !r.produ_status) return false;
        // "Recipe Change" on a row with no MR/PP/WOs is a passive editable marker
        // (WDP-style) — nothing to regenerate server-side.
        if (r.produ_status === "Recipe Change" && !r.mr_reference && !r.production_plane && !r.wo_list) return false;
        return true;
    });
    if (pending.length === 0) {
        finish_success();
        return;
    }
    _dp_dialog_clear_error(dialog);
    show_loading_overlay();
    frappe.call({
        doc: frm.doc,
        method: 'process_manual_updates',
        args: row_name ? { row_name: row_name } : {},
        callback: function(r) {
            hide_loading_overlay();
            if (r && r.exc) {
                // Server threw (process_manual_updates already rolled back).
                // Keep the dialog open and surface the error so the planner can
                // fix the row and retry.
                _dp_dialog_show_error(dialog, _dp_extract_server_error(r));
                return;
            }
            finish_success();
            frm.reload_doc();
            frappe.show_alert({ message: __('✅ Changes processed'), indicator: 'green' });
        },
        error: function(r) {
            hide_loading_overlay();
            _dp_dialog_show_error(dialog, _dp_extract_server_error(r));
        }
    });
}

function validate_unique_cook_combination(frm, cdt, cdn) {
    const current_row = locals[cdt][cdn]; const workstation = current_row.recipe_cook_workstaion; const round = current_row.recipe_cook_round;
    if (!workstation || !round) return;
    frm.doc.production_table.forEach(function(other_row) {
        if (other_row.name === current_row.name) return;
        if (other_row.recipe_cook_workstaion === workstation && other_row.recipe_cook_round === round) {
            frappe.throw({ title: __("Duplicate Entry"), message: __(`Cooker <b>${workstation}</b> on Round <b>${round}</b> is already assigned in row <b>${other_row.idx}</b> for <b>${other_row.recipe_name}</b>.`) });
        }
    });
}

function validate_unique_cook_combination_pack(frm, cdt, cdn) {
    const current_row = locals[cdt][cdn]; const workstation = current_row.pack_machine; const round = current_row.pack_round;
    if (!workstation || !round) return;
    frm.doc.production_table.forEach(function(other_row) {
        if (other_row.name === current_row.name) return;
        if (other_row.pack_machine === workstation && other_row.pack_round === round) {
            frappe.throw({ title: __("Duplicate Entry"), message: __(`Pack Machine <b>${workstation}</b> on Round <b>${round}</b> is already assigned in row <b>${other_row.idx}</b> for <b>${other_row.pack_name}</b>.`) });
        }
    });
}

function validate_pack_time_against_group_cook_time(frm, cdt, cdn) {
    const current_row = locals[cdt][cdn];
    const pack_time = current_row.pack_time;
    if (!pack_time) return;
    let relevant_cook_time = null;
    for (let i = current_row.idx - 1; i >= 0; i--) {
        const prev_row = frm.doc.production_table[i];
        if (prev_row && prev_row.recipe_cook_time) { relevant_cook_time = prev_row.recipe_cook_time; break; }
    }
}

function revalidate_subsequent_pack_times(frm, cdt, cdn) {
    const current_row = locals[cdt][cdn]; const new_cook_time = current_row.recipe_cook_time;
    if (!new_cook_time) return;
    for (let i = current_row.idx; i < frm.doc.production_table.length; i++) {
        const subsequent_row = frm.doc.production_table[i];
        if (subsequent_row.recipe_name && i > (current_row.idx - 1)) break;
        if (subsequent_row.pack_time && (subsequent_row.pack_time < new_cook_time)) {
            frappe.msgprint({ title: __('Invalid Pack Time'), indicator: 'red', message: __(`Pack Time (${subsequent_row.pack_time}) in row ${subsequent_row.idx} is now invalid due to the updated Cook Time (${new_cook_time}). It has been cleared.`) });
            frappe.model.set_value(subsequent_row.doctype, subsequent_row.name, 'pack_time', '');
        }
    }
}

function validate_field_dependency(frm, cdt, cdn, fieldname, dependency_fieldname, dependency_label) {
    const row = locals[cdt][cdn];
    if (!row[dependency_fieldname]) {
        if (row[fieldname] || row[fieldname] === 0) {
            frappe.msgprint({ title: __(`${dependency_label} Required`), indicator: 'orange', message: __(`Please select a ${dependency_label} before setting the '${frappe.meta.get_label(cdt, fieldname)}' field.`) });
            const field_meta = frappe.meta.get_field(cdt, fieldname);
            const default_value = (["Int", "Float", "Currency"].includes(field_meta.fieldtype)) ? 0 : "";
            frappe.model.set_value(cdt, cdn, fieldname, default_value);
            return false;
        }
    }
    return true;
}

function is_complete_recipe(row) {
    return !!(row.recipe_name && row.recipe_name !== "No Cooking"
        && flt(row.size) > 0
        && (parseInt(row.number_of_pack) || 0) >= 1
        && row.pack_name);
}

function filter_produ_status(frm, cdn) {
    const grid = frm.fields_dict["production_table"]?.grid;
    if (!grid) return;
    const row = locals["Create ProExl Items"]?.[cdn];
    if (!row) return;
    const grid_row = grid.get_row(cdn);
    if (!grid_row) return;
    const field = grid_row.get_field("produ_status");
    if (!field) return;
    const base = "\nNew Schedule\nRecipe Change\nCancelled\nChange Slot\nRearrange\nOnly Remark\nPack Change";
    const no_wo = !row.mr_reference && !row.production_plane && !row.wo_list;
    const complete = is_complete_recipe(row);
    let options;
    if (!row.recipe_name || row.recipe_name === "No Cooking") {
        options = "\nNew Schedule";
    } else if (no_wo) {
        // Recipe set but no MR/PP yet. Change Slot / Rearrange are pure data moves
        // and only make sense once the row is fully set (recipe + size + >= 1 pack).
        options = complete ? "\nNew Schedule\nChange Slot\nRearrange" : "\nNew Schedule";
        if (row.produ_status && row.produ_status !== "New Schedule" && !options.includes(row.produ_status)) options += "\n" + row.produ_status;
    } else {
        // MR/PP rows: "Cancelled" is handled by the dialog Cancel button; "New
        // Schedule" only when it is the current status. "Single WO" stays hidden
        // (matches the doctype's produ_status options).
        options = base.replace("\nCancelled", "");
        if (row.produ_status !== "New Schedule") options = options.replace("\nNew Schedule", "");
        if (row.produ_status && options.split("\n").indexOf(row.produ_status) === -1) options += "\n" + row.produ_status;
    }
    field.df.options = options;
    field.set_options();
}


// =================================================================
// PARENT DOCTYPE: DAILY PRODUCTION (Unified Block)
// =================================================================

frappe.ui.form.on("Daily Production", {
    onload: function(frm) {
        if (frm.is_new()) { frm.set_value("planner_name", frappe.session.user_fullname); }
        if (!frm.doc.workflow_state) { frm.doc.workflow_state = "Draft"; }
    },

  refresh: function(frm) {
        const MAX_ROWS = 64;

        let grid = frm.get_field("production_table").grid;
        if (grid) {
            grid.page_length = MAX_ROWS;
            grid.df.page_length = MAX_ROWS;

            if (grid.grid_pagination) {
                grid.grid_pagination.page_length = MAX_ROWS;
                grid.grid_pagination.go_to_page(1);
            }
            grid.cannot_add_rows = true;
            grid.cannot_delete_rows = true;
            grid.df.cannot_add_rows = true;
            grid.df.cannot_delete_rows = true;
        }
        setup_production_grid(frm);

        // Fetch workstation statuses for problem-row detection
        var ws_names = [...new Set((frm.doc.production_table || []).map(r => r.recipe_cook_workstaion).filter(Boolean))];
        frm._ws_status = {};
        if (ws_names.length) {
            frappe.call({
                method: "frappe.client.get_list",
                args: { doctype: "Workstation", fields: ["name", "status"], filters: [["name", "in", ws_names]] },
                callback: function(r) {
                    (r.message || []).forEach(function(w) { frm._ws_status[w.name] = w.status; });
                    color_recipe_groups(frm);
                    if (typeof window.apply_edit_restrictions === 'function') { window.apply_edit_restrictions(frm); }
                }
            });
        }

        const pack_fields = ["pack_name", "pack_name_2", "pack_name_3", "pack_name_4", "pack_name_5", "pack_name_6"];

        pack_fields.forEach(target_field => {
            frm.set_query(target_field, "production_table", function(doc, cdt, cdn) {
                let row = locals[cdt][cdn];
                let recipe_to_filter_by = "";

                if (row.recipe_name) {
                    recipe_to_filter_by = row.recipe_name;
                } else {
                    let current_idx = frm.doc.production_table.findIndex(d => d.name === row.name);
                    for (let i = current_idx - 1; i >= 0; i--) {
                        if (doc.production_table[i] && doc.production_table[i].recipe_name) {
                            recipe_to_filter_by = doc.production_table[i].recipe_name;
                            break;
                        }
                    }
                }

                let already_selected = [];
                pack_fields.forEach(f => {
                    if (f !== target_field && row[f]) {
                        already_selected.push(row[f]);
                    }
                });

                return {
                    query: "caf.caf.doctype.daily_production.daily_production.get_packs_for_recipe",
                    filters: {
                        recipe_name: recipe_to_filter_by,
                        excluded_items: already_selected
                    }
                };
            });
        });

        // Setup Buttons
        if (frm.doc.workflow_state === "Submitted") {
            if (!frm.doc.custom_submit_ref) {
                frm.add_custom_button(__('Create Work Order'), function() {
                    frappe.confirm(__('This will process all production changes (Swaps, Size Changes, and Cancellations). Are you sure?'), () => {
                        show_loading_overlay();
                        frm.call({
                            doc: frm.doc,
                            method: 'process_manual_updates',
                            callback: function(r) {
                                hide_loading_overlay();
                                if(!r.exc) {
                                    frm.reload_doc();
                                    frappe.show_alert({ message: __('✅ Production updates processed successfully'), indicator: 'green' });
                                }
                            },
                            error: function(r) { hide_loading_overlay(); }
                        });
                    });
                }, __("Actions"));
            } else {
                if (!frm.doc.custom_recipe_requisition_form) {
                    frm.add_custom_button(__('Recipe (Requisition)'), () => call_create_plan(frm, "Recipe", "Creating Requisition Form..."), __('Create Production Plan'));
                }
                if (!frm.doc.custom_tim_form_) {
                    frm.add_custom_button(__('TIM Form'), () => call_create_plan(frm, "WIP TIM", "Creating TIM Form..."), __('Create Production Plan'));
                }
                if (!frm.doc.custom_wip_form) {
                    frm.add_custom_button(__('WIP Form'), () => call_create_plan(frm, "WIP", "Creating WIP Form..."), __('Create Production Plan'));
                }
            }
        }

        if (typeof window.apply_edit_restrictions === 'function') {
            window.apply_edit_restrictions(frm);
        }
    },

    after_save: function(frm) {
        // Synchronous process_manual_updates is triggered ONLY from the custom edit
        // dialog's Save (see maybe_process_dp_changes). Normal Save just persists.
        debounced_apply_colors(frm);
    },

    before_submit: function(frm) {
        show_loading_overlay();
        frappe.validated = false;
        const cancel_rows = (frm.doc.production_table || []).filter(r => r.produ_status === 'Cancelled');
        const do_submit = function() {
            frappe.call({
                method: "caf.caf.doctype.daily_production.daily_production.submit_dp",
                args: { docname: frm.doc.name },
                callback: function(r) {
                    hide_loading_overlay();
                    if (r.message && r.message.success) {
                        frm.reload_doc();
                        frappe.show_alert({ message: __("✅ Submitted"), indicator: "green" });
                    }
                },
                error: function() { hide_loading_overlay(); }
            });
        };
        if (cancel_rows.length > 0) {
            const recipe_list = cancel_rows.map(r => `<li>${r.recipe_name || 'Row ' + r.idx}</li>`).join('');
            frappe.confirm(
                __(`<b>${cancel_rows.length} row(s) are marked for cancellation:</b><ul>${recipe_list}</ul> Their Work Orders will be cancelled on submit. Proceed?`),
                do_submit,
                () => { hide_loading_overlay(); }
            );
        } else {
            do_submit();
        }
        return false;
    },

    on_submit: function(frm) { hide_loading_overlay(); },

    size_calculation: function(frm) { window.open("http://192.168.0.251:8080/app/production-calculate", "_blank"); },

    required_by: function(frm) {
        if (!frm.doc.required_by) return;

        const today = frappe.datetime.get_today();
        if (frm.doc.required_by < today) {
            frm.set_value("required_by", "");
            frappe.throw({ title: __("Invalid Date"), message: __("The 'Required By' date cannot be in the past.") });
            return;
        }
        if (frm.doc.production_table && frm.doc.production_table.length > 0) {
            frappe.confirm(
                __('Changing the date will clear and re-organize the table. Do you want to proceed?'),
                () => { execute_fetch(frm); },
                () => { frm.set_value('required_by', frm.doc._previous_date || null); }
            );
        } else {
            execute_fetch(frm);
        }
        frm.doc._previous_date = frm.doc.required_by;

        if (frm.doc.production_table && frm.doc.production_table.length > 0) {
            frm.doc.production_table.forEach(function(row) {
                frappe.model.set_value(row.doctype, row.name, "required_date", frm.doc.required_by);
            });
            frm.refresh_field("production_table");
        }
    },

    required_by_1: function(frm) {
        if (!frm.doc.required_by_1) return;
        const today = frappe.datetime.get_today();
        if (frm.doc.required_by_1 < today) {
            frm.set_value("required_by_1", "");
            frappe.throw({ title: __("Invalid Date"), message: __("The 'Required By' date cannot be in the past.") });
            return;
        }
        if (frm.doc.items && frm.doc.items.length > 0) {
            frm.doc.items.forEach(function(row) {
                frappe.model.set_value(row.doctype, row.name, "schedule_date", frm.doc.required_by_1);
            });
            frm.refresh_field("items");
        }
    }
});


// =================================================================
// SERVER CALL HELPERS
// =================================================================

function call_create_plan(frm, group_name, freeze_msg) {
    frappe.dom.freeze(__(freeze_msg));
    frappe.call({
        method: "caf.caf.doctype.daily_production.delta.create_production_plan",
        args: { dp_name: frm.doc.name, item_group: group_name },
        callback(r) {
            frappe.dom.unfreeze();
            if (r.message) {
                frappe.show_alert({ message: __("Production Plan {0} created successfully", [r.message]), indicator: 'green' });
                frm.reload_doc();
            }
        },
        error: function() { frappe.dom.unfreeze(); }
    });
}

function execute_fetch(frm) {
    frappe.dom.freeze(__('Fetching and Organizing Rounds...'));

    const freeze_timeout = setTimeout(() => {
        frappe.dom.unfreeze();
        frappe.show_alert({ message: __('Request timed out, please try again'), indicator: 'red' });
    }, 15000);

    frappe.call({
        method: "caf.caf.doctype.daily_production.daily_production.get_merged_production_items",
        args: { date: frm.doc.required_by, doctype: frm.doc.doctype },
        callback: function(r) {
            clearTimeout(freeze_timeout);
            frappe.dom.unfreeze();

            if (r.message && r.message.rows && r.message.rows.length > 0) {
                frm.set_value("custom_submit_ref", r.message.submit_ref || "");
                frm.clear_table("production_table");

                let sorted_rows = r.message.rows.sort((a, b) => {
                    return a.idx - b.idx;
                });

                const excluded_keys = ["name", "parent", "parentfield", "parenttype", "doctype", "idx", "owner", "creation", "modified", "modified_by"];

                sorted_rows.forEach(item => {
                    let row = frm.add_child("production_table");
                    for (let key in item) {
                        if (!excluded_keys.includes(key)) {
                            row[key] = item[key];
                        }
                    }
                });

                frm.refresh_field("production_table");

                if (typeof window.apply_edit_restrictions === 'function') {
                    window.apply_edit_restrictions(frm);
                }

                frm.save().then(() => {
                    frappe.show_alert({ message: __('Table updated and ordered by Index'), indicator: 'green' });
                });

            } else {
                frm.set_value("custom_submit_ref", "");
                frm.clear_table("production_table");
                frm.refresh_field("production_table");
                frappe.show_alert({ message: __('No data found for this date'), indicator: 'orange' });
            }
        },
        error: function(r) {
            clearTimeout(freeze_timeout);
            frappe.dom.unfreeze();
            frappe.show_alert({ message: __('Failed to fetch production data'), indicator: 'red' });
        }
    });
}
// =================================================================
// CHILD DOCTYPE: Create ProExl Items (Unified Block)
// =================================================================

frappe.ui.form.on("Create ProExl Items", {

    refresh: function(frm) {
        let grid = frm.fields_dict["production_table"].grid;
        if (grid) {
            grid.df.in_place_edit = false;
            grid.refresh();
        }
        (frm.doc.production_table || []).forEach(row => {
            if (!row.__prev_status) {
                row.__prev_status = row.produ_status || '';
            }
            try { filter_produ_status(frm, row.name); } catch (e) { }
        });
        if (typeof window.apply_edit_restrictions === 'function') {
            window.apply_edit_restrictions(frm, null, null);
        }
    },

    form_render: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row && !row.__prev_status) {
            row.__prev_status = row.produ_status || '';
        }
        filter_produ_status(frm, cdn);
        // Lazy-load total_input + total_output for existing rows
        var _row = locals[cdt][cdn];
        if (_row && _row.recipe_name && _row.recipe_name !== "No Cooking" && _row._raw_materials === undefined) {
            frappe.call({
                method: 'caf.caf.page.production_schedule.production_schedule.get_recipe_bom_data',
                args: { recipe_name: _row.recipe_name },
                callback: function(r) {
                    if (r.message) {
                        _row._raw_materials = r.message.raw_materials || 0;
                        _row._max_packs = _row._max_packs || r.message.pack_count || 7;
                        var ti = flt(r.message.raw_materials) * flt(_row.size);
                        frappe.model.set_value(cdt, cdn, 'total_input', ti);
                        frappe.model.set_value(cdt, cdn, 'total_output', ti * flt(_row.custom_yield));
                    }
                }
            });
        }
        if (typeof window.apply_edit_restrictions === 'function') { window.apply_edit_restrictions(frm, cdt, cdn); }
    },

    produ_status: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const current_status = row.produ_status;
        const prev_status = row.__prev_status || '';
        row.__prev_status = current_status;
        const recipe_name = row.recipe_name;

        // ── Reject any status (except New Schedule / Change Slot) if no recipe set ──
        if (current_status && current_status !== "New Schedule" && current_status !== "Change Slot" && (!recipe_name || recipe_name === "No Cooking")) {
            frappe.show_alert({ message: __("Error. Enter Recipe First"), indicator: 'red' }, 3, 'top');
            setTimeout(() => {
                $('.alert').css({
                    'position': 'fixed',
                    'top': '20px',
                    'left': '50%',
                    'transform': 'translateX(-50%)',
                    'z-index': '9999'
                });
            }, 50);
            frappe.model.set_value(cdt, cdn, 'produ_status', '');
            return;
        }

        // ── Clear: wipe all user data back to defaults ──
        if (current_status === "Clear") {
            // Clear produ_status via locals first to prevent recursive handler call
            locals[cdt][cdn].produ_status = "";
            locals[cdt][cdn].__prev_status = "";

            // Reset user-editable fields (protected fields preserved: workstation, round, link_id)
            frappe.model.set_value(cdt, cdn, "recipe_name", "No Cooking");
            frappe.model.set_value(cdt, cdn, "size", 0);
            frappe.model.set_value(cdt, cdn, "number_of_pack", 0);
            frappe.model.set_value(cdt, cdn, "custom_yield", null);
            // frappe.model.set_value(cdt, cdn, "production_type", null);
            frappe.model.set_value(cdt, cdn, "recipe_cook_time", null);
            frappe.model.set_value(cdt, cdn, "recipe_note", null);
            return;
        }

        // ── Rearrange: swap all field values between two slots ──
        if (current_status === "Rearrange") {
            show_rearrange_dialog(frm, cdt, cdn);
            return;
        }

        // ── Change Slot: move this row's data into a different slot ──
        if (current_status === "Change Slot") {
            show_change_slot_dialog(frm, cdt, cdn);
            return;
        }

        // ── Unpair: if status changed away from Rearrange/Change Slot, clear partner too ──
        if (row.custom_pair_id && current_status !== "Rearrange" && current_status !== "Change Slot") {
            const paired = (frm.doc.production_table || []).filter(r =>
                r.name !== row.name && r.custom_pair_id === row.custom_pair_id
            );
            paired.forEach(pr => {
                frappe.model.set_value(pr.doctype, pr.name, 'produ_status', '');
                frappe.model.set_value(pr.doctype, pr.name, 'custom_pair_id', '');
            });
            frappe.model.set_value(cdt, cdn, 'custom_pair_id', '');
        }

        if (typeof window.apply_edit_restrictions === 'function') {
            window.apply_edit_restrictions(frm, cdt, cdn);
        }
    },

    recipe_name(frm, cdt, cdn) {
        const current_row = locals[cdt][cdn];

        filter_produ_status(frm, cdn);

        if (["Cancelled", "Change Slot", "Rearrange"].includes(current_row.produ_status)) {
            return;
        }

        // ── Clear pack fields + size if recipe changed (matching WPD behavior) ──
        if (["Recipe Change", "New Schedule"].includes(current_row.produ_status) || !current_row.produ_status) {
            frappe.model.set_value(cdt, cdn, "size", 0);
            for (let i = 1; i <= 7; i++) {
                let s = i === 1 ? "" : "_" + i;
                frappe.model.set_value(cdt, cdn, "pack_name" + s, null);
                frappe.model.set_value(cdt, cdn, "pack_qty" + s, 0);
                frappe.model.set_value(cdt, cdn, "pack_remark" + s, null);
            }
        }

        const start_index = current_row.idx - 1;
        const is_no_cook = !current_row.recipe_name || current_row.recipe_name === "No Cooking";
        frappe.model.set_value(cdt, cdn, 'number_of_pack', is_no_cook ? 0 : 1);

        const pack_fields_to_clear = ['pack_name', 'pack_machine', 'pack_time', 'pack_round'];
        for (let i = start_index + 1; i < frm.doc.production_table.length; i++) {
            const subsequent_row = frm.doc.production_table[i];
            if (subsequent_row.recipe_name) break;
            pack_fields_to_clear.forEach(field => { frappe.model.set_value(subsequent_row.doctype, subsequent_row.name, field, null); });
        }

        // ── Fetch custom_yield from BOM ──
        if (!current_row.recipe_name || current_row.recipe_name === "No Cooking") {
            frappe.model.set_value(cdt, cdn, 'custom_yield', null);
            frappe.model.set_value(cdt, cdn, 'total_input', 0);
            frappe.model.set_value(cdt, cdn, 'total_output', 0);
            current_row._max_packs = 7;
            current_row._raw_materials = 0;
        } else {
            frappe.call('caf.caf.doctype.daily_production.daily_production.get_bom_info', {
                item_code: current_row.recipe_name
            }).then(r => {
                if (r.message && r.message.bom_yield) {
                    frappe.model.set_value(cdt, cdn, 'custom_yield', r.message.bom_yield);
                } else {
                    frappe.model.set_value(cdt, cdn, 'custom_yield', null);
                }
            }).catch(() => {
                frappe.model.set_value(cdt, cdn, 'custom_yield', null);
            });

            // Fetch pack count from BOM (matching WPD's get_recipe_bom_data)
            frappe.call('caf.caf.page.production_schedule.production_schedule.get_recipe_bom_data', {
                recipe_name: current_row.recipe_name
            }).then(r => {
                if (r.message) {
                    current_row._max_packs = r.message.pack_count || 7;
                    current_row._raw_materials = r.message.raw_materials || 0;
                    var ti = flt(r.message.raw_materials) * flt(current_row.size);
                    frappe.model.set_value(cdt, cdn, 'total_input', ti);
                    frappe.model.set_value(cdt, cdn, 'total_output', ti * flt(current_row.custom_yield));
                }
            }).catch(() => {
                current_row._max_packs = 7;
                current_row._raw_materials = 0;
                frappe.model.set_value(cdt, cdn, 'total_input', 0);
                frappe.model.set_value(cdt, cdn, 'total_output', 0);
            });
        }

        debounced_apply_colors(frm);
        frm.refresh_field("production_table");
    },

    production_table_add(frm, cdt, cdn) {
        if (frm.doc.production_table.length >= 64) {
            frappe.model.clear_doc(cdt, cdn);
            frappe.throw(__("Maximum limit of 64 rows reached."));
        }

        debounced_apply_colors(frm);
        const parent_date = frm.doc.required_by;
        if (parent_date) frappe.model.set_value(cdt, cdn, "required_date", parent_date);

        if (typeof window.apply_edit_restrictions === 'function') {
            window.apply_edit_restrictions(frm, cdt, cdn);
        }
    },

    production_table_remove(frm) { debounced_apply_colors(frm); },

    number_of_pack: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const val = flt(row.number_of_pack);

        if (val > (row._max_packs || 7)) {
            var mp = row._max_packs || 7;
            frappe.show_alert({ message: __('Number of packs cannot exceed {0} for this recipe.', [mp]), indicator: 'red' }, 3);
            frappe.model.set_value(cdt, cdn, "number_of_pack", mp);
            return;
        }

        const num = flt(row.number_of_pack);
        for (let i = 1; i <= 7; i++) {
            if (i > num) {
                let s = (i === 1) ? "" : "_" + i;
                frappe.model.set_value(cdt, cdn, "pack_name" + s, null);
                frappe.model.set_value(cdt, cdn, "pack_qty" + s, 0);
                frappe.model.set_value(cdt, cdn, "pack_note" + s, null);
            }
        }
        debounced_validate_pack(frm, cdt, cdn);
    },

    size: function(frm, cdt, cdn) {
        validate_field_dependency(frm, cdt, cdn, 'size', 'recipe_name', 'Recipe Name');
        if (typeof window.apply_edit_restrictions === 'function') { window.apply_edit_restrictions(frm, cdt, cdn); }
        debounced_validate_pack(frm, cdt, cdn);
        var r = locals[cdt][cdn];
	if (r && r._raw_materials) {
            var ti = flt(r._raw_materials) * flt(r.size);
            frappe.model.set_value(cdt, cdn, 'total_input', ti);
            frappe.model.set_value(cdt, cdn, 'total_output', ti * flt(r.custom_yield));
        }
    },
    recipe_cook_workstaion: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'recipe_cook_workstaion', 'recipe_name', 'Recipe Name')) { try { validate_unique_cook_combination(frm, cdt, cdn); } catch (e) { frappe.model.set_value(cdt, cdn, 'recipe_cook_round', ''); } } },
    recipe_cook_round: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'recipe_cook_round', 'recipe_name', 'Recipe Name')) { try { validate_unique_cook_combination(frm, cdt, cdn); } catch (e) { frappe.model.set_value(cdt, cdn, 'recipe_cook_workstaion', ''); } } },
    pack_machine: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'pack_machine', 'pack_name', 'Pack Name')) { try { validate_unique_cook_combination_pack(frm, cdt, cdn); } catch (e) { frappe.model.set_value(cdt, cdn, 'pack_round', ''); } } },
    pack_round: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'pack_round', 'pack_name', 'Pack Name')) { try { validate_unique_cook_combination_pack(frm, cdt, cdn); } catch (e) { frappe.model.set_value(cdt, cdn, 'pack_machine', ''); } } },
    recipe_cook_time: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'recipe_cook_time', 'recipe_name', 'Recipe Name')) { revalidate_subsequent_pack_times(frm, cdt, cdn); } },
    pack_qty_2: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const nop = parseInt(row.number_of_pack) || 1;
        if (nop <= 2) return;
        if (row.pack_qty_2 && !row.pack_qty) {
            frappe.msgprint(__('Please fill Pack 1 Qty first before entering Pack 2 Qty.'));
            frappe.model.set_value(cdt, cdn, 'pack_qty_2', 0);
        }
        debounced_validate_pack(frm, cdt, cdn);
    },
    pack_qty_3: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const nop = parseInt(row.number_of_pack) || 1;
        if (nop <= 3) return;
        if (row.pack_qty_3 && !row.pack_qty_2) {
            frappe.msgprint(__('Please fill Pack 2 Qty first before entering Pack 3 Qty.'));
            frappe.model.set_value(cdt, cdn, 'pack_qty_3', 0);
        }
        debounced_validate_pack(frm, cdt, cdn);
    },
    pack_qty_4: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const nop = parseInt(row.number_of_pack) || 1;
        if (nop <= 4) return;
        if (row.pack_qty_4 && !row.pack_qty_3) {
            frappe.msgprint(__('Please fill Pack 3 Qty first before entering Pack 4 Qty.'));
            frappe.model.set_value(cdt, cdn, 'pack_qty_4', 0);
        }
        debounced_validate_pack(frm, cdt, cdn);
    },
    pack_qty_5: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const nop = parseInt(row.number_of_pack) || 1;
        if (nop <= 5) return;
        if (row.pack_qty_5 && !row.pack_qty_4) {
            frappe.msgprint(__('Please fill Pack 4 Qty first before entering Pack 5 Qty.'));
            frappe.model.set_value(cdt, cdn, 'pack_qty_5', 0);
        }
        debounced_validate_pack(frm, cdt, cdn);
    },
    pack_qty_6: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const nop = parseInt(row.number_of_pack) || 1;
        if (nop <= 6) return;
        if (row.pack_qty_6 && !row.pack_qty_5) {
            frappe.msgprint(__('Please fill Pack 5 Qty first before entering Pack 6 Qty.'));
            frappe.model.set_value(cdt, cdn, 'pack_qty_6', 0);
        }
        debounced_validate_pack(frm, cdt, cdn);
    },
    pack_qty_7: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const nop = parseInt(row.number_of_pack) || 1;
        if (nop <= 7) return;
        if (row.pack_qty_7 && !row.pack_qty_6) {
            frappe.msgprint(__('Please fill Pack 6 Qty first before entering Pack 7 Qty.'));
            frappe.model.set_value(cdt, cdn, 'pack_qty_7', 0);
        }
        debounced_validate_pack(frm, cdt, cdn);
    }
});


// =================================================================
// OTHER CHILD DOCTYPE: Single WO Items
// =================================================================

frappe.ui.form.on('Single WO Items', {
    qty: function(frm, cdt, cdn) { let row = locals[cdt][cdn]; calculate_qty_or_size(frm, row, 'qty'); },
    size: function(frm, cdt, cdn) { let row = locals[cdt][cdn]; calculate_qty_or_size(frm, row, 'size'); }
});

function calculate_qty_or_size(frm, row, field_changed) {
    if (!row.item_code) return;
    frappe.call({
        method: "frappe.client.get_value",
        args: { doctype: "Item", filters: { name: row.item_code }, fieldname: ["stock_uom"] },
        callback: function(uom_r) {
            if (!uom_r.message) { frappe.msgprint(`Cannot get UOM for item ${row.item_code}`); return; }
            let stock_uom = uom_r.message.stock_uom.toLowerCase();
            frappe.call({
                method: "caf.caf.doctype.daily_production.daily_production.get_bom_info",
                args: { item_code: row.item_code },
                callback: function(r) {
                    if (!r.message) { return; }
                    let bom_total = r.message.bom_total; let bom_yield = r.message.bom_yield;
                    if (field_changed === 'size' && row.size) { row.qty = bom_total * row.size * bom_yield; }
                    else if (field_changed === 'qty' && row.qty) { row.size = row.qty / (bom_total * bom_yield); }
                    if (stock_uom === "gram") { if (row.qty) row.qty = row.qty * 1000; if (row.size) row.size = row.size; }
                    row.yeiled = bom_yield;
                    frm.refresh_field('items');
                }
            });
        }
    });
}

function calculate_qty_or_size_WO(frm, row, field_changed) {
    if (!row.recipe_name) return;

    let do_calculation = (bom_total, bom_yield) => {
        let qty = flt(row.qty);
        let size = flt(row.size);

        if (field_changed === 'size' && row.size) {
            qty = bom_total * row.size * bom_yield;
            frappe.model.set_value(row.doctype, row.name, "qty", qty);
        }
        else if (field_changed === 'qty' && row.qty) {
            size = row.qty / (bom_total * bom_yield);
            frappe.model.set_value(row.doctype, row.name, "size", size);
        }

        if (row.stock_uom === "gram") {
            if (field_changed === 'size') {
                frappe.model.set_value(row.doctype, row.name, "qty", qty * 1000);
            }
        }

        frappe.model.set_value(row.doctype, row.name, "yeiled", bom_yield);
        frm.refresh_field("production_table");
    };

    frappe.call({
        method: "frappe.client.get_value",
        args: {
            doctype: "Item",
            filters: { name: row.recipe_name },
            fieldname: ["stock_uom"]
        },
        callback: function(uom_r) {
            if (!uom_r.message) {
                frappe.msgprint(`Cannot get UOM for item ${row.recipe_name}`);
                return;
            }
            let stock_uom = uom_r.message.stock_uom?.toLowerCase();
            frappe.call({
                method: "caf.caf.doctype.daily_production.daily_production.get_bom_info",
                args: { item_code: row.recipe_name },
                callback: function(r) {
                    if (!r.message) {
                        frappe.msgprint(`No BOM info found for item ${row.recipe_name}`);
                        return;
                    }
                    let bom_total = flt(r.message.bom_total);
                    let bom_yield = flt(r.message.bom_yield);
                    do_calculation(bom_total, bom_yield);
                }
            });
        }
    });
}
// =================================================================
// DYNAMIC FIELD HELPERS
// =================================================================

const ALWAYS_READ_ONLY = ['recipe_cook_workstaion', 'recipe_cook_round', 'link_id',
    'mr_reference', 'rq_status', 'custom_yield', 'total_input', 'total_output', 'production_plane', 'custom_pair_id'];
const SYSTEM_FIELDS = ['name', 'owner', 'creation', 'modified', 'modified_by', 'parent', 'parentfield', 'parenttype', 'idx', 'doctype'];
// MR/PP travel with the recipe during a slot swap/rearrange; link_id stays fixed
// to the slot so the server-side WO migration (by link_id) still works.
const SWAP_EXTRA_FIELDS = ['mr_reference', 'production_plane'];

/** Gets all user-data fields that are allowed to be moved or swapped */
function get_moveable_fields(doctype) {
    const meta = frappe.get_meta(doctype);
    const non_data_types = ['Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Heading', 'Fold'];
    return meta.fields
        .filter(f => SWAP_EXTRA_FIELDS.includes(f.fieldname) ||
            (!ALWAYS_READ_ONLY.includes(f.fieldname) && !SYSTEM_FIELDS.includes(f.fieldname) && !non_data_types.includes(f.fieldtype)))
        .map(f => f.fieldname);
}

// =================================================================
// CUSTOM ROW EDIT DIALOG (WPD-STYLE)
// Rows are edited through this dialog. Values are STAGED inside the
// dialog and applied to the row only when the user clicks Save.
// Closing the dialog (X / ESC / outside click) discards all edits.
// =================================================================

function _dp_dialog_set_pack_visibility(d) {
    const nop = parseInt(d.get_value("number_of_pack")) || 0;
    for (let i = 1; i <= 7; i++) {
        const s = i === 1 ? "" : "_" + i;
        const show = i <= nop;
        ["pack_name", "pack_qty", "pack_remark"].forEach(function(p) {
            $(d.wrapper).find('[data-fieldname="' + p + s + '"]').closest(".frappe-control").toggle(show);
        });
    }
}

function _dp_dialog_restrict(d) {
    const recipe = d.get_value("recipe") || "";
    const no_cook = !recipe || recipe === "No Cooking";
    const size_val = flt(d.get_value("size"));
    const status = d.get_value("produ_status") || "";

    const always_ro = ["cook_station", "cook_round", "custom_yield", "total_input", "total_output",
        "link_id", "mr_reference", "production_plane", "rq_status"];
    const pack_fields = [];
    for (let i = 1; i <= 7; i++) {
        const s = i === 1 ? "" : "_" + i;
        pack_fields.push("pack_name" + s, "pack_qty" + s, "pack_remark" + s);
    }
    const all_user_fields = ["produ_status", "recipe", "size", "production_type", "urgent_check",
        "recipe_note", "number_of_pack"].concat(pack_fields);

    let editable = [];
    if (no_cook) {
        editable = ["produ_status"];
        if (status === "New Schedule") editable.push("recipe");
    } else if (status === "New Schedule") {
        editable = ["recipe", "produ_status", "size"];
        if (size_val > 0) editable = editable.concat(["production_type", "urgent_check", "recipe_note", "number_of_pack"].concat(pack_fields));
    } else if (status === "Recipe Change") {
        editable = ["recipe", "produ_status", "size", "production_type", "urgent_check", "recipe_note", "number_of_pack"].concat(pack_fields);
    } else if (status === "" || status === "Cancelled") {
        editable = ["produ_status"];
    } else if (status === "Pack Change") {
        editable = ["produ_status", "number_of_pack"].concat(pack_fields);
    } else if (status === "Only Remark") {
        editable = ["produ_status", "recipe_note"];
    } else if (status === "Single WO") {
        editable = ["produ_status", "recipe", "size"];
    } else {
        editable = all_user_fields;
    }

    // Lock pack fields when size is 0 (matching WPD / apply_edit_restrictions)
    if (size_val <= 0 && !no_cook) {
        editable = editable.filter(function(f) { return f !== "number_of_pack" && !f.startsWith("pack_"); });
    }

    all_user_fields.forEach(function(fn) {
        const f = d.fields_dict[fn];
        if (!f) return;
        const enabled = editable.includes(fn) && !always_ro.includes(fn);
        f.df.read_only = !enabled;
        f.refresh();
    });
}

function install_dp_edit_interceptor(frm) {
    const grid = frm.get_field("production_table")?.grid;
    if (!grid) return;

    // Safety net: route ANY native row-form open (pencil, row number, keyboard,
    // insert-row, programmatic toggle_view/show_form) to the custom dialog.
    (grid.grid_rows || []).forEach(function(ui_row) {
        if (!ui_row || !ui_row.doc || ui_row.__dp_wrapped) return;
        ui_row.__dp_wrapped = true;
        const orig_toggle = ui_row.toggle_view && ui_row.toggle_view.bind(ui_row);
        ui_row.show_form = function() {
            show_dp_edit_dialog(frm, ui_row.doc.doctype, ui_row.doc.name);
        };
        if (orig_toggle) {
            ui_row.toggle_view = function(show, callback) {
                if (show === false) {
                    return orig_toggle(show, callback);
                }
                show_dp_edit_dialog(frm, ui_row.doc.doctype, ui_row.doc.name);
                callback && callback();
                return ui_row;
            };
        }
    });

    if (!grid.wrapper || !grid.wrapper[0]) return;
    const el = grid.wrapper[0];
    if (el.__dp_intercept) {
        el.removeEventListener('click', el.__dp_intercept, true);
        el.__dp_intercept = null;
    }
    const handler = function(e) {
        const t = e.target;
        if (!t || !t.closest) return;
        // Clicking the checkbox / row search input must behave normally.
        if (t.closest('.grid-row-check')) return;
        const btn = t.closest('.btn-open-row');
        const rowIndex = t.closest('.row-index');
        if (!btn && (!rowIndex || t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
        const $row = $(t).closest('.grid-row');
        if (!$row.length) return;
        const docname = $row.attr('data-name');
        if (!docname) return;
        e.preventDefault();
        e.stopPropagation();
        show_dp_edit_dialog(frm, 'Create ProExl Items', docname);
    };
    el.__dp_intercept = handler;
    el.addEventListener('click', handler, true);
}

// Recompute the dialog's produ_status options from the staged values. Change Slot /
// Rearrange are offered only once the row is fully set (recipe + size + >= 1 pack).
function refresh_dialog_status_options(d, no_wo) {
    const recipe = d.get_value("recipe") || "";
    const no_cook = !recipe || recipe === "No Cooking";
    const complete = flt(d.get_value("size")) > 0
        && (parseInt(d.get_value("number_of_pack")) || 0) >= 1
        && d.get_value("pack_name");
    let opts;
    if (no_cook) {
        opts = "\nNew Schedule";
    } else if (no_wo) {
        opts = complete ? "New Schedule\nChange Slot\nRearrange" : "New Schedule";
    } else {
        opts = "\nRecipe Change\nOnly Remark\nPack Change\nChange Slot\nRearrange";
    }
    const cur_status = d.get_value("produ_status") || "";
    if (cur_status && opts.split("\n").indexOf(cur_status) === -1) {
        opts += "\n" + cur_status;
    }
    d.fields_dict.produ_status.df.options = opts;
    d.fields_dict.produ_status.set_options();
}

function show_dp_edit_dialog(frm, cdt, cdn) {
    const row = locals[cdt]?.[cdn];
    if (!row) return;

    if (row.rq_status === "Processing") {
        frappe.show_alert({ message: __('Row is being processed. Please wait…'), indicator: 'orange' }, 3);
        return;
    }

    const orig_recipe = row.recipe_name || "";
    const orig_size = flt(row.size);
    const orig_nop = String(row.number_of_pack || 0);
    const orig_status = row.produ_status || "";

    const no_cook = !row.recipe_name || row.recipe_name === "" || row.recipe_name === "No Cooking";
    // Rows that already produced WOs must NOT be treated as a fresh schedule.
    const has_wos = !!(row.wo_list || row.mr_reference);

    const no_wo = !row.mr_reference && !row.production_plane && !row.wo_list;
    const complete = is_complete_recipe(row);
    // Keep the row's current status visible even if it is an immediate-action status
    // (e.g. Change Slot / Rearrange) so it is preserved unless the user changes it.
    let status_options;
    if (no_cook) {
        status_options = "\nNew Schedule";
        if (orig_status && orig_status !== "New Schedule" && !status_options.includes(orig_status)) status_options += "\n" + orig_status;
    } else if (no_wo) {
        // Recipe set but no MR/PP yet (scheduled via "New Schedule"): New Schedule
        // unlocks all fields once size is set, so there is no separate "Change
        // Recipe" — Clear/Cancel are dialog buttons instead. Change Slot / Rearrange
        // are pure data moves here (no WOs to migrate) and require a complete row.
        // No leading "\n": the blank option is removed so an empty status can't be
        // picked on a row that must have a status.
        status_options = complete ? "New Schedule\nChange Slot\nRearrange" : "New Schedule";
        if (orig_status && orig_status !== "New Schedule" && !status_options.includes(orig_status)) status_options += "\n" + orig_status;
    } else {
        // Rows with MR/PP: match WDP — "Recipe Change"/"Only Remark"/"Pack Change"
        // plus the WO-driving moves Change Slot / Rearrange. "Cancelled" is replaced
        // by the dialog's Cancel button; "New Schedule" and "Single WO" are not
        // offered here.
        status_options = "\nRecipe Change\nOnly Remark\nPack Change\nChange Slot\nRearrange";
        if (orig_status && status_options.split("\n").indexOf(orig_status) === -1) status_options += "\n" + orig_status;
    }

    const fields = [
        { fieldname: "sec_slot", fieldtype: "Section Break", label: __("Slot Info") },
        { fieldname: "cook_station", fieldtype: "Data", label: __("Cook Workstation"), read_only: 1, default: row.recipe_cook_workstaion || "" },
        { fieldtype: "Column Break" },
        { fieldname: "cook_round", fieldtype: "Data", label: __("Cook Round"), read_only: 1, default: row.recipe_cook_round || "" },
        { fieldname: "sec_prod", fieldtype: "Section Break", label: __("Production") },
        { fieldname: "produ_status", fieldtype: "Select", label: __("Production Status"), options: status_options, default: orig_status || (no_cook && !has_wos ? "New Schedule" : "") },
        { fieldname: "recipe", fieldtype: "Link", label: __("Recipe"), options: "Item", default: row.recipe_name || "", get_query: function() { return { filters: { item_group: ["in", ["Recipe", "WIP Floss"]] } }; } },
        { fieldtype: "Column Break" },
        { fieldname: "size", fieldtype: "Float", label: __("Size"), default: orig_size, precision: 3 },
        { fieldname: "production_type", fieldtype: "Select", label: __("Production Type"), options: "\nNew\nRecook\nReheat\nRepack", default: row.production_type || "" },
        { fieldtype: "Column Break" },
        { fieldname: "urgent_check", fieldtype: "Check", label: __("Urgent Order"), default: row.urgent_check ? 1 : 0 },
        { fieldname: "recipe_note", fieldtype: "Data", label: __("Recipe Note"), default: row.recipe_note || "" },
        { fieldname: "sec_info", fieldtype: "Section Break", label: __("Production Info") },
        { fieldname: "custom_yield", fieldtype: "Float", label: __("Yield (KG)"), read_only: 1, default: row.custom_yield || 0, precision: 6 },
        { fieldtype: "Column Break" },
        { fieldname: "total_input", fieldtype: "Float", label: __("Total Input (KG)"), read_only: 1, default: row.total_input || 0, precision: 6 },
        { fieldtype: "Column Break" },
        { fieldname: "total_output", fieldtype: "Float", label: __("Total Output (KG)"), read_only: 1, default: row.total_output || 0, precision: 6 },
        { fieldname: "sec_pack", fieldtype: "Section Break", label: __("Pack Details") },
        { fieldname: "number_of_pack", fieldtype: "Select", label: __("Number of Packs"), options: "0\n1\n2\n3\n4\n5\n6\n7", default: orig_nop },
        { fieldname: "sec_pack_grid", fieldtype: "Section Break" }
    ];

    for (let i = 1; i <= 7; i++) {
        const sfx = i === 1 ? "" : "_" + i;
        (function(s) {
            fields.push({
                fieldname: "pack_name" + s, fieldtype: "Link", options: "Item",
                label: i === 1 ? __("Pack Name") : __("Pack {0} Name", [i]),
                default: row["pack_name" + s] || "",
                get_query: function() {
                    const cur_recipe = d.get_value("recipe") || "";
                    if (!cur_recipe || cur_recipe === "No Cooking") return { filters: { name: ["=", ""] } };
                    const excluded = [];
                    for (let j = 1; j <= 7; j++) {
                        const sj = j === 1 ? "" : "_" + j;
                        const v = d.get_value("pack_name" + sj);
                        if (v && sj !== s) excluded.push(v);
                    }
                    return {
                        query: "caf.caf.doctype.daily_production.daily_production.get_packs_for_recipe",
                        filters: { recipe_name: cur_recipe, excluded_items: excluded }
                    };
                }
            });
        })(sfx);
    }
    fields.push({ fieldtype: "Column Break" });
    for (let i = 1; i <= 7; i++) {
        const sfx = i === 1 ? "" : "_" + i;
        fields.push({ fieldname: "pack_qty" + sfx, fieldtype: "Float", label: i === 1 ? __("Pack QTY") : __("Pack {0} QTY", [i]), default: flt(row["pack_qty" + sfx]) });
    }
    fields.push({ fieldtype: "Column Break" });
    for (let i = 1; i <= 7; i++) {
        const sfx = i === 1 ? "" : "_" + i;
        fields.push({ fieldname: "pack_remark" + sfx, fieldtype: "Data", label: i === 1 ? __("Pack Remark") : __("Pack {0} Remark", [i]), default: row["pack_remark" + sfx] || "" });
    }

    fields.push(
        { fieldname: "sec_sys", fieldtype: "Section Break", label: __("System Info") },
        { fieldname: "link_id", fieldtype: "Data", label: __("Link ID"), read_only: 1, default: row.link_id || "" },
        { fieldtype: "Column Break" },
        { fieldname: "mr_reference", fieldtype: "Data", label: __("MR Reference"), read_only: 1, default: row.mr_reference || "" },
        { fieldname: "rq_status", fieldtype: "Data", label: __("RQ Status"), read_only: 1, default: row.rq_status || "" },
        { fieldname: "pack_weight_msg", fieldtype: "HTML", options: '<div class="pack-weight-msg" style="display:none;color:#e53e3e;font-size:12px;padding:6px 0;"></div>' },
        { fieldname: "dp_wo_error", fieldtype: "HTML", options: '<div class="dp-wo-error" style="display:none;color:#e53e3e;font-size:12px;padding:6px 0;"></div>' }
    );

    // WDP-style slot actions: "Clear" when no MR/PP (reset slot to defaults,
    // no WO cancellation), "Cancel" only when MR exists (cancels through to WOs).
    const slot_actions = [];
    if (!no_cook && !no_wo) {
        slot_actions.push('<button type="button" class="btn btn-danger btn-xs dp-slot-btn-cancel">' + __("Cancel Recipe") + '</button>');
    }
    if (!no_cook && no_wo) {
        slot_actions.push('<button type="button" class="btn btn-default btn-xs dp-slot-btn-clear">' + __("Clear") + '</button>');
    }
    if (slot_actions.length) {
        fields.push({ fieldname: "sec_actions", fieldtype: "Section Break", label: __("Actions") });
        fields.push({ fieldname: "slot_actions_html", fieldtype: "HTML", options: '<div class="dp-slot-action-btns">' + slot_actions.join(' ') + '</div>' });
    }

    const d = new frappe.ui.Dialog({
        title: __('Edit Row {0}', [row.idx]) + (row.recipe_name ? ' — ' + row.recipe_name : ''),
        fields: fields,
        primary_action_label: __('Save'),
        primary_action: async function(values) {
            if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
            values = d.get_values();
            if (!values) return;

            const recipe_val = values.recipe || "";
            const status_val = values.produ_status || "";
            const size_val = flt(values.size);
            const nop = parseInt(values.number_of_pack) || 0;
            const no_cook = !recipe_val || recipe_val === "No Cooking";

            // Cannot save a slot that has no recipe yet
            if (no_cook) {
                frappe.msgprint(__("Please enter a recipe first."));
                return;
            }
            if (recipe_val && recipe_val !== "No Cooking" && size_val === 0) {
                frappe.msgprint(__("Size is required when a recipe is set."));
                return;
            }
            if (!no_cook && nop >= 1) {
                for (let i = 1; i <= nop; i++) {
                    const s = i === 1 ? "" : "_" + i;
                    if (!values["pack_name" + s]) {
                        $(d.wrapper).find('[data-fieldname="pack_name' + s + '"]').closest(".frappe-control").addClass("has-error");
                        frappe.msgprint(__("All packs must have a pack name."));
                        return;
                    }
                }
            }
            if (!no_cook && nop > 1) {
                for (let i = 1; i < nop; i++) {
                    const s = i === 1 ? "" : "_" + i;
                    if (flt(values["pack_qty" + s]) <= 0) {
                        frappe.msgprint(__("Please fill qty for all packs except the last one."));
                        return;
                    }
                }
                for (let i = 2; i <= nop; i++) {
                    const s = "_" + i;
                    const prev_s = i === 2 ? "" : "_" + (i - 1);
                    if (flt(values["pack_qty" + s]) > 0 && flt(values["pack_qty" + prev_s]) <= 0) {
                        frappe.msgprint(__("Please fill Pack {0} Qty first before entering Pack {1} Qty.", [i - 1, i]));
                        return;
                    }
                }
                const packs = [];
                for (let i = 1; i <= nop; i++) {
                    const s = i === 1 ? "" : "_" + i;
                    if (values["pack_name" + s]) packs.push({ name: values["pack_name" + s], qty: flt(values["pack_qty" + s]) });
                }
                if (packs.length > 1) {
                    let valid = true;
                    frappe.call({
                        method: "caf.caf.page.production_schedule.production_schedule.validate_pack_weights",
                        args: { recipe_name: recipe_val, size: values.size, packs: JSON.stringify(packs) },
                        async: false,
                        callback: function(vr) {
                            if (vr.message && !vr.message.valid) {
                                valid = false;
                                frappe.msgprint(vr.message.message);
                            }
                        }
                    });
                    if (!valid) return;
                }
            }

            // ── Apply staged values to the row (existing field handlers fire) ──
            // The grid's recipe_name handler clears size/packs/nop on change, so re-apply
            // nop/size/packs unconditionally whenever the recipe changed.
            // NOTE: frappe.model.set_value marks the form dirty asynchronously, so each
            // call must be awaited before frm.is_dirty() is consulted for the save.
            const recipe_changed = recipe_val !== orig_recipe;
            if (recipe_changed) {
                await frappe.model.set_value(cdt, cdn, "recipe_name", recipe_val);
            }
            await frappe.model.set_value(cdt, cdn, "number_of_pack", values.number_of_pack);
            if (recipe_changed || flt(values.size) !== orig_size) {
                await frappe.model.set_value(cdt, cdn, "size", values.size);
            }
            for (let i = 1; i <= 7; i++) {
                const s = i === 1 ? "" : "_" + i;
                const new_name = values["pack_name" + s] || null;
                const new_qty = flt(values["pack_qty" + s]);
                const new_remark = values["pack_remark" + s] || null;
                if (recipe_changed || (new_name || "") !== (row["pack_name" + s] || "")) await frappe.model.set_value(cdt, cdn, "pack_name" + s, new_name);
                if (recipe_changed || new_qty !== flt(row["pack_qty" + s])) await frappe.model.set_value(cdt, cdn, "pack_qty" + s, new_qty);
                if (recipe_changed || (new_remark || "") !== (row["pack_remark" + s] || "")) await frappe.model.set_value(cdt, cdn, "pack_remark" + s, new_remark);
            }
            if ((values.production_type || "") !== (row.production_type || "")) await frappe.model.set_value(cdt, cdn, "production_type", values.production_type || null);
            if (!!values.urgent_check !== !!row.urgent_check) await frappe.model.set_value(cdt, cdn, "urgent_check", values.urgent_check ? 1 : 0);
            if ((values.recipe_note || "") !== (row.recipe_note || "")) await frappe.model.set_value(cdt, cdn, "recipe_note", values.recipe_note || null);
            if (status_val !== orig_status) await frappe.model.set_value(cdt, cdn, "produ_status", status_val);
            // A previously-processed row keeps its status marker (rq_status="Done").
            // Any fresh edit makes it processable again.
            if (row.rq_status === "Done") await frappe.model.set_value(cdt, cdn, "rq_status", "");

            show_loading_overlay();
            // frm.save() never settles its promise when the doc has no changes
            // (frappe skips the server call), which would leave the overlay stuck.
            // Only round-trip when something actually changed.
            const dirty = frm.is_dirty();
            const save_promise = dirty ? frm.save() : Promise.resolve();
            save_promise.then(function() {
                hide_loading_overlay();
                // Keep the dialog open until WO processing completes. maybe_process_dp_changes
                // closes it on success and shows the error inline on failure so the planner
                // can fix the row and retry.
                maybe_process_dp_changes(frm, cdn, d, function() {
                    setTimeout(function() { if (window.opener) window.close(); }, 500);
                });
            }, function(err) {
                hide_loading_overlay();
                _dp_dialog_show_error(d, _dp_extract_server_error(err));
                console.error("❌ DP dialog save failed:", err);
            });
        },
        secondary_action_label: __('Cancel'),
        secondary_action: function() { d.hide(); }
    });
    d._dp_raw_materials = flt(row._raw_materials);
    d._dp_max_packs = row._max_packs || 7;

    // ── Live behaviors (staged inside the dialog only) ──
    d.fields_dict.recipe.df.change = function() {
        const recipe = d.get_value("recipe") || "";
        const is_nc = !recipe || recipe === "No Cooking";
        d.set_value("size", 0);
        d.set_value("number_of_pack", is_nc ? 0 : 1);
        for (let i = 1; i <= 7; i++) {
            const s = i === 1 ? "" : "_" + i;
            d.set_value("pack_name" + s, null);
            d.set_value("pack_qty" + s, 0);
            d.set_value("pack_remark" + s, null);
        }
        d.set_value("custom_yield", 0);
        d.set_value("total_input", 0);
        d.set_value("total_output", 0);
        d._dp_raw_materials = 0;
        d._dp_max_packs = 7;
        if (is_nc) {
            d.fields_dict.produ_status.df.options = "\nNew Schedule";
            d.fields_dict.produ_status.set_options();
            if (!has_wos && d.get_value("produ_status") === "") d.set_value("produ_status", "New Schedule");
            _dp_dialog_restrict(d);
            _dp_dialog_set_pack_visibility(d);
            return;
        }
        let opts;
        const cur_status = d.get_value("produ_status") || "";
        if (no_wo) {
            // Change Slot / Rearrange are pure data moves and only make sense once
            // the row is fully set (recipe + size + >= 1 pack).
            const complete = flt(d.get_value("size")) > 0
                && (parseInt(d.get_value("number_of_pack")) || 0) >= 1
                && d.get_value("pack_name");
            opts = complete ? "New Schedule\nChange Slot\nRearrange" : "New Schedule";
            if (cur_status && cur_status !== "New Schedule" && !opts.includes(cur_status)) opts += "\n" + cur_status;
        } else {
            opts = "\nRecipe Change\nOnly Remark\nPack Change\nChange Slot\nRearrange";
            if (cur_status && opts.split("\n").indexOf(cur_status) === -1) opts += "\n" + cur_status;
        }
        d.fields_dict.produ_status.df.options = opts;
        d.fields_dict.produ_status.set_options();
        frappe.call({
            method: "caf.caf.page.production_schedule.production_schedule.get_recipe_bom_data",
            args: { recipe_name: recipe },
            callback: function(r) {
                if (r.message) {
                    d._dp_max_packs = r.message.pack_count || 7;
                    d._dp_raw_materials = r.message.raw_materials || 0;
                    d.set_value("custom_yield", r.message.yield || 0);
                    const sz = flt(d.get_value("size"));
                    const ti = flt(d._dp_raw_materials) * sz;
                    d.set_value("total_input", ti);
                    d.set_value("total_output", ti * flt(r.message.yield));
                }
            }
        });
        _dp_dialog_restrict(d);
        _dp_dialog_set_pack_visibility(d);
    };

    d.fields_dict.size.df.change = function() {
        const recipe = d.get_value("recipe") || "";
        if (!recipe || recipe === "No Cooking") return;
        const sz = flt(d.get_value("size"));
        const raw = flt(d._dp_raw_materials);
        if (raw) {
            const ti = raw * sz;
            d.set_value("total_input", ti);
            d.set_value("total_output", ti * flt(d.get_value("custom_yield")));
        }
        _dp_dialog_restrict(d);
        refresh_dialog_status_options(d, no_wo);
    };

    d.fields_dict.number_of_pack.df.change = function() {
        const nop = parseInt(d.get_value("number_of_pack")) || 0;
        const maxp = d._dp_max_packs || 7;
        if (nop > maxp) {
            frappe.show_alert({ message: __('Number of packs cannot exceed {0} for this recipe.', [maxp]), indicator: 'red' }, 3);
            d.set_value("number_of_pack", String(maxp));
            return;
        }
        _dp_dialog_set_pack_visibility(d);
        refresh_dialog_status_options(d, no_wo);
    };

    d.fields_dict.produ_status.df.change = function() {
        const v = d.get_value("produ_status") || "";
        if (v === "Change Slot" || v === "Rearrange") {
            // Route to the dedicated action dialog (matching grid-dropdown behavior).
            d.hide();
            if (v === "Change Slot") {
                show_change_slot_dialog(frm, cdt, cdn);
            } else {
                show_rearrange_dialog(frm, cdt, cdn);
            }
            return;
        }
        _dp_dialog_restrict(d);
    };

    d.show();
    _dp_dialog_restrict(d);
    _dp_dialog_set_pack_visibility(d);

    // ── WDP-style slot actions ──
    // Clear: no MR/PP → reset the slot to a clean "No Cooking" slot (no WOs to cancel).
    $(d.wrapper).on("click", ".dp-slot-btn-clear", async function() {
        await frappe.model.set_value(cdt, cdn, "produ_status", "");
        await frappe.model.set_value(cdt, cdn, "recipe_name", "No Cooking");
        await frappe.model.set_value(cdt, cdn, "size", 0);
        await frappe.model.set_value(cdt, cdn, "number_of_pack", 0);
        for (let i = 1; i <= 7; i++) {
            const s = i === 1 ? "" : "_" + i;
            await frappe.model.set_value(cdt, cdn, "pack_name" + s, null);
            await frappe.model.set_value(cdt, cdn, "pack_qty" + s, 0);
            await frappe.model.set_value(cdt, cdn, "pack_remark" + s, null);
        }
        await frappe.model.set_value(cdt, cdn, "production_type", "");
        await frappe.model.set_value(cdt, cdn, "urgent_check", 0);
        await frappe.model.set_value(cdt, cdn, "recipe_note", "");
        await frappe.model.set_value(cdt, cdn, "custom_yield", 0);
        await frappe.model.set_value(cdt, cdn, "mr_reference", "");
        await frappe.model.set_value(cdt, cdn, "production_plane", "");
        await frappe.model.set_value(cdt, cdn, "wo_list", "");
        await frappe.model.set_value(cdt, cdn, "wo_list_with_type", "");
        await frappe.model.set_value(cdt, cdn, "rq_status", "");
        await frappe.model.set_value(cdt, cdn, "custom_pair_id", "");
        show_loading_overlay();
        const dirty = frm.is_dirty();
        const save_promise = dirty ? frm.save() : Promise.resolve();
        save_promise.then(function() {
            hide_loading_overlay();
            d.hide();
        }, function(err) {
            hide_loading_overlay();
            console.error("❌ DP dialog clear failed:", err);
        });
    });

    // Cancel: only for rows WITH MR/PP → cancels all the way through to WOs.
    $(d.wrapper).on("click", ".dp-slot-btn-cancel", function() {
        if (orig_status === "Cancelled") {
            frappe.msgprint(__("This item is already cancelled."));
            return;
        }
        frappe.confirm(__("Cancel this recipe? Existing WOs will be cancelled."), function() {
            frappe.model.set_value(cdt, cdn, "produ_status", "Cancelled").then(function() {
                if (row.rq_status === "Done") frappe.model.set_value(cdt, cdn, "rq_status", "");
                show_loading_overlay();
                const dirty = frm.is_dirty();
                const save_promise = dirty ? frm.save() : Promise.resolve();
                save_promise.then(function() {
                    hide_loading_overlay();
                    // Keep the dialog open until WO cancellation completes; on failure
                    // the error is shown inline so the planner can act on it.
                    maybe_process_dp_changes(frm, cdn, d, function() {
                        setTimeout(function() { if (window.opener) window.close(); }, 500);
                    });
                }, function(err) {
                    hide_loading_overlay();
                    _dp_dialog_show_error(d, _dp_extract_server_error(err));
                    console.error("❌ DP dialog cancel failed:", err);
                });
            });
        });
    });

    // Ctrl+Shift+Enter → Save & Close (Metabase popup flow)
    $(d.wrapper).on("keydown.dp_ctrlshiftenter", function(e) {
        if (e.ctrlKey && e.shiftKey && e.key === "Enter") {
            e.preventDefault();
            e.stopPropagation();
            d.get_primary_btn().trigger("click");
        }
    });
}

// =================================================================
// PENCIL DIALOG RE-OPENER
// =================================================================
function reopen_pencil_dialog(frm, row_name) {
    setTimeout(() => {
        let grid = frm.fields_dict['production_table']?.grid;
        if (!grid) return;
        let row = grid.grid_rows_by_docname?.[row_name];
        if (!row) {
            row = grid.grid_rows?.find(r => r.doc.name === row_name);
        }
        if (row) {
            grid.refresh_row(row.doc.name);
            show_dp_edit_dialog(frm, 'Create ProExl Items', row.doc.name);
        }
    }, 300);
}

// =================================================================
// DYNAMIC REARRANGE DIALOG
// =================================================================

function show_rearrange_dialog(frm, cdt, cdn) {
    if (frm._dialog_open) return;
    frm._dialog_open = true;

    const source_row = locals[cdt][cdn];
    let action_applied = false;
    const other_rows = frm.doc.production_table.filter(r =>
        r.name !== source_row.name && r.recipe_name && r.recipe_name !== "No Cooking" && (r.produ_status == "New Schedule" || r.produ_status == "")
    );

    if (other_rows.length === 0) {
        frappe.msgprint(__('No other recipe slots found to swap with.'));
        frappe.model.set_value(cdt, cdn, 'produ_status', '');
        frm._dialog_open = false;
        return;
    }

    let slot_options = other_rows.map(r =>
        `Slot ${r.idx} — ${r.recipe_name} | ${r.recipe_cook_workstaion || 'N/A'} (Rnd ${r.recipe_cook_round || '-'})`
    );

    let d = new frappe.ui.Dialog({
        title: `🔀 Rearrange Slot (${source_row.recipe_cook_workstaion} - R${source_row.recipe_cook_round})`,
        fields: [{ fieldtype: 'Select', fieldname: 'target_slot', label: 'Swap With', options: ['', ...slot_options], reqd: 1 }],
        primary_action: function(values) {
            const target_row = other_rows.find(r =>
                `Slot ${r.idx} — ${r.recipe_name} | ${r.recipe_cook_workstaion || 'N/A'} (Rnd ${r.recipe_cook_round || '-'})` === values.target_slot
            );
            if (!target_row) return;

            action_applied = true;
            const has_wos = !!frm.doc.custom_submit_ref;

            if (has_wos) {
                // WOs exist: delegate the whole swap + WO migration to the atomic
                // server method (single transaction). No client-side field swap, no
                // status markers, no separate save — on failure the transaction rolls
                // back and the rows stay in their original slots.
                show_loading_overlay();
                frappe.call({
                    method: "caf.caf.doctype.daily_production.rearrange_and_change_slot.process_rearrange_atomic",
                    args: {
                        dp_name: frm.doc.name,
                        row_a_name: source_row.name,
                        row_b_name: target_row.name,
                    },
                    callback: function(r) {
                        hide_loading_overlay();
                        d.hide();
                        if (r.message && r.message.success) {
                            frm.reload_doc();
                            frappe.show_alert({ message: __('✅ Rearranged'), indicator: 'green' });
                        } else {
                            frm.reload_doc();
                            frappe.show_alert({ message: r.message && r.message.message || __('Rearrange failed'), indicator: 'red' }, 6);
                        }
                    },
                    error: function() {
                        hide_loading_overlay();
                        d.hide();
                        frm.reload_doc();
                    }
                });
                return;
            }

            // No WOs: pure data swap — no status markers, no pair_id (WDP-style).
            const fields = get_moveable_fields(source_row.doctype);
            const swaps = fields.map(fn => ({ fn, s_val: source_row[fn], t_val: target_row[fn] }));
            // Direct locals assignment bypasses field change handlers that could corrupt values
            swaps.forEach(({ fn, s_val, t_val }) => {
                locals[source_row.doctype][source_row.name][fn] = t_val;
                locals[target_row.doctype][target_row.name][fn] = s_val;
            });

            frappe.model.set_value(source_row.doctype, source_row.name, 'produ_status', '');
            frappe.model.set_value(target_row.doctype, target_row.name, 'produ_status', '');
            frappe.model.set_value(source_row.doctype, source_row.name, 'custom_pair_id', '');
            frappe.model.set_value(target_row.doctype, target_row.name, 'custom_pair_id', '');

            frm.refresh_field("production_table");
            frm.save().then(() => {
                d.hide();
                reopen_pencil_dialog(frm, source_row.name);
            }, () => { d.hide(); });
        },
        secondary_action_label: __('Cancel'),
        secondary_action: function() { d.hide(); }
    });

    d.onhide = () => {
        frm._dialog_open = false;
        if (!action_applied) frappe.model.set_value(cdt, cdn, 'produ_status', '');
    };
    d.show();
}

// =================================================================
// DYNAMIC CHANGE SLOT DIALOG
// =================================================================

function show_change_slot_dialog(frm, cdt, cdn) {
    if (frm._dialog_open) return;
    frm._dialog_open = true;

    const source_row = locals[cdt][cdn];
    const child_doctype = source_row.doctype;
    let action_applied = false;
    const source_has_recipe = source_row.recipe_name && source_row.recipe_name !== "No Cooking";

    let targets = frm.doc.production_table.filter(r => {
        if (r.name === source_row.name) return false;
        if (source_has_recipe) {
            return !r.recipe_name || r.recipe_name === "No Cooking";
        }
        return r.recipe_name && r.recipe_name !== "No Cooking" && (r.produ_status === "New Schedule" || r.produ_status === "");
    });

    if (targets.length === 0) {
        const msg = source_has_recipe
            ? __("No empty slots available. Clear a slot first before moving.")
            : __("No recipes available to move. Please add a recipe to another slot first.");
        frappe.show_alert({ message: msg, indicator: 'red' }, 3, 'top');
        frappe.model.set_value(cdt, cdn, 'produ_status', '');
        frm._dialog_open = false;
        return;
    }

    let slot_options = targets.map(r => {
        if (!r.recipe_name || r.recipe_name === "No Cooking") {
            return `Slot ${r.idx} — ${r.recipe_cook_workstaion || 'N/A'} (Rnd ${r.recipe_cook_round || '-'})`;
        }
        return `Slot ${r.idx} — ${r.recipe_name} | ${r.recipe_cook_workstaion || 'N/A'} (Rnd ${r.recipe_cook_round || '-'})`;
    });

    let d = new frappe.ui.Dialog({
        title: `➡️ Change Slot (${source_row.recipe_cook_workstaion} - R${source_row.recipe_cook_round})`,
        fields: [{
            fieldtype: 'Select',
            fieldname: 'target_slot',
            label: 'Move To',
            options: ['', ...slot_options],
            reqd: 1
        }],
        primary_action: function(values) {
            const target_row = targets.find(r => {
                let label;
                if (!r.recipe_name || r.recipe_name === "No Cooking") {
                    label = `Slot ${r.idx} — ${r.recipe_cook_workstaion || 'N/A'} (Rnd ${r.recipe_cook_round || '-'})`;
                } else {
                    label = `Slot ${r.idx} — ${r.recipe_name} | ${r.recipe_cook_workstaion || 'N/A'} (Rnd ${r.recipe_cook_round || '-'})`;
                }
                return label === values.target_slot;
            });

            if (!target_row) {
                frappe.msgprint(__("Error identifying target slot."));
                return;
            }

            action_applied = true;
            const has_wos = !!frm.doc.custom_submit_ref;

            if (has_wos) {
                // WOs exist: delegate the whole swap + WO migration to the atomic
                // server method (single transaction). No client-side field swap, no
                // status markers, no separate save — on failure the transaction rolls
                // back and the rows stay in their original slots.
                show_loading_overlay();
                frappe.call({
                    method: "caf.caf.doctype.daily_production.rearrange_and_change_slot.process_slot_swap_atomic",
                    args: {
                        dp_name: frm.doc.name,
                        source_row: source_row.name,
                        target_row: target_row.name,
                    },
                    callback: function(r) {
                        hide_loading_overlay();
                        d.hide();
                        if (r.message && r.message.success) {
                            frm.reload_doc();
                            frappe.show_alert({ message: __('✅ Slot changed'), indicator: 'green' });
                        } else {
                            frm.reload_doc();
                            frappe.show_alert({ message: r.message && r.message.message || __('Slot change failed'), indicator: 'red' }, 6);
                        }
                    },
                    error: function() {
                        hide_loading_overlay();
                        d.hide();
                        frm.reload_doc();
                    }
                });
                return;
            }

            // No WOs: pure data move — no status markers, no pair_id (WDP-style).
            const fields = get_moveable_fields(child_doctype);
            const swaps = fields.map(fn => ({ fn, s_val: source_row[fn], t_val: target_row[fn] }));
            swaps.forEach(({ fn, s_val, t_val }) => {
                locals[source_row.doctype][source_row.name][fn] = t_val;
                locals[target_row.doctype][target_row.name][fn] = s_val;
            });

            frappe.model.set_value(target_row.doctype, target_row.name, 'produ_status', '');
            frappe.model.set_value(source_row.doctype, source_row.name, 'produ_status', '');
            frappe.model.set_value(target_row.doctype, target_row.name, 'custom_pair_id', '');
            frappe.model.set_value(source_row.doctype, source_row.name, 'custom_pair_id', '');

            frm.refresh_field("production_table");
            frm.save().then(() => {
                d.hide();
                frappe.show_alert({ message: __('Slot Changed and Saved'), indicator: 'blue' });
                reopen_pencil_dialog(frm, source_row.name);
            }, () => { d.hide(); });
        },
        secondary_action_label: __('Cancel'),
        secondary_action: function() {
            d.hide();
        }
    });

    d.onhide = () => {
        frm._dialog_open = false;
        if (!action_applied) {
            frappe.model.set_value(cdt, cdn, 'produ_status', '');
        }
    };
    d.show();
}

// =================================================================
// EDIT RESTRICTION LOGIC
// =================================================================

window.apply_edit_restrictions = function(frm, cdt, cdn) {
    if (!frm.doc || !frm.doc.production_table || !frm.doc.production_table.length) return;
    let rows = (cdt && cdn) ? [frappe.get_doc(cdt, cdn)] : frm.doc.production_table;

    const meta = frappe.get_meta(rows[0].doctype);
    const all_fields = meta.fields.map(f => f.fieldname);
    const pack_data_fields = all_fields.filter(f => f.startsWith('pack_') && (f.includes('name') || f.includes('qty') || f.includes('note') || f.includes('remark')));
    const all_note_fields = all_fields.filter(f => f.includes('note') || f.includes('remark'));

    rows.forEach(row => {
        if (!row) return;

        // Lock entire row if workstation has Problem status (matching WPD)
        var ws_name = row.recipe_cook_workstaion;
        if (frm._ws_status && ws_name && frm._ws_status[ws_name] === "Problem") {
            all_fields.forEach(fn => {
                if (!ALWAYS_READ_ONLY.includes(fn)) {
                    frm.set_df_property('production_table', 'read_only', 1, frm.doc.name, fn, row.name);
                }
            });
            ALWAYS_READ_ONLY.forEach(fn => {
                frm.set_df_property('production_table', 'read_only', 1, frm.doc.name, fn, row.name);
            });
            var _grid = frm.get_field("production_table").grid;
            if (_grid) {
                _grid.refresh_row(row.name);
                if (_grid.grid_row_form && _grid.grid_row_form.wrapper.is(':visible')) _grid.grid_row_form.refresh();
            }
            return;
        }

        let field_configs = {};
        const status = row.produ_status;
        const is_no_cook = !row.recipe_name || row.recipe_name === "" || row.recipe_name === "No Cooking";
        var size_val = flt(row.size);

        // Lock the whole row while a background job is running (WPD-style)
        if (row.rq_status === "Processing") {
            all_fields.forEach(function (fn) {
                frm.set_df_property('production_table', 'read_only', 1, frm.doc.name, fn, row.name);
            });
            return;
        }

        if (status === "New Schedule") {
            // Progressive unlock: recipe → size → the rest (WPD-style)
            all_fields.forEach(f => { if (!ALWAYS_READ_ONLY.includes(f)) field_configs[f] = 1; });
            field_configs.produ_status = 0;
            field_configs.recipe_name = 0;
            if (!is_no_cook) {
                if (size_val > 0) {
                    all_fields.forEach(f => { if (!ALWAYS_READ_ONLY.includes(f)) field_configs[f] = 0; });
                } else {
                    field_configs.size = 0;
                }
            }
        }
        else if (status === "Recipe Change") {
            all_fields.forEach(f => { if (!ALWAYS_READ_ONLY.includes(f)) field_configs[f] = 0; });
        }
        else if (status === "" || status === "Cancelled") {
            all_fields.forEach(f => field_configs[f] = 1);
            field_configs.produ_status = 0;
        }
        else if (status === "Pack Change") {
            all_fields.forEach(f => field_configs[f] = 1);
            pack_data_fields.forEach(f => field_configs[f] = 0);
            field_configs.number_of_pack = 0;
            field_configs.produ_status = 0;
        }
        else if (["Rearrange", "Change Slot"].includes(status)) {
            all_fields.forEach(f => field_configs[f] = 1);
            all_note_fields.forEach(f => field_configs[f] = 0);
            field_configs.produ_status = 0;
        }
        else if (status === "Only Remark") {
            all_fields.forEach(f => field_configs[f] = 1);
            all_note_fields.forEach(f => field_configs[f] = 0);
            field_configs.produ_status = 0;
            field_configs.recipe_note = 0;
        }
        else if (status === "Single WO") {
            all_fields.forEach(f => field_configs[f] = 1);
            field_configs.recipe_name = 0;
            field_configs.size = 0;
            field_configs.produ_status = 0;
        }
        else {
            all_fields.forEach(f => { if (!ALWAYS_READ_ONLY.includes(f)) field_configs[f] = 0; });
        }

        // Lock pack fields when size is 0 (matching WPD behavior)
        if (size_val <= 0 && !is_no_cook) {
            field_configs.number_of_pack = 1;
            for (var _pi = 1; _pi <= 7; _pi++) {
                var _ps = _pi === 1 ? "" : "_" + _pi;
                field_configs["pack_name" + _ps] = 1;
                field_configs["pack_qty" + _ps] = 1;
                field_configs["pack_remark" + _ps] = 1;
            }
        }

        if (is_no_cook && !["New Schedule", "Single WO","Recipe Change"].includes(status)) {
            field_configs.recipe_name = 1;
            field_configs.size = 1;
        }

        if (status && status !== "Cancelled") {
            // EXCEPTION: New Schedule on No Cooking — allow user to clear it back to empty
            if (!(status === "New Schedule" && is_no_cook)) {
                field_configs.produ_status = 0;
            }
        }

        // No-recipe lock: when recipe is empty/No Cooking, lock everything except recipe_name and produ_status
        if (is_no_cook) {
            all_fields.forEach(fn => {
                if (fn !== "produ_status" && fn !== "recipe_name"
                    && !ALWAYS_READ_ONLY.includes(fn)) {
                    field_configs[fn] = 1;
                }
            });
        }

        try {
            Object.keys(field_configs).forEach(fn => {
                frm.set_df_property('production_table', 'read_only', field_configs[fn], frm.doc.name, fn, row.name);
            });
        } catch (e) {
            console.warn("apply_edit_restrictions error for row", row.name, e);
        }

        let grid = frm.get_field("production_table").grid;
        if (grid) {
            grid.refresh_row(row.name);
            if (grid.grid_row_form && grid.grid_row_form.wrapper.is(':visible')) grid.grid_row_form.refresh();
        }

        ALWAYS_READ_ONLY.forEach(fn => {
            frm.set_df_property('production_table', 'read_only', 1, frm.doc.name, fn, row.name);
        });
    });
};

frappe.ui.form.on('Create ProExl Items', {
    produ_status(frm, cdt, cdn) {
        const row = locals[cdt]?.[cdn];
        if (!row) return;

        if (row.produ_status === "Single WO") {
            frappe.model.set_value(cdt, cdn, "recipe_name", "No Cooking");
        }

        window.apply_edit_restrictions(frm, cdt, cdn);
    },
    recipe_name(frm, cdt, cdn) {
        window.apply_edit_restrictions(frm, cdt, cdn);
    }
});

// =================================================================
// New Version JS — REMOVED (non-submission workflow)
// =================================================================

// =================================================================
// URL Param Row Opener
// =================================================================

frappe.ui.form.on('Daily Production', {
    refresh: function(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__('Add Extra Round'), function() {
                frappe.call({
                    method: "caf.caf.doctype.daily_production.daily_production.get_template_round_config",
                    callback: function(rc) {
                        if (!rc.message) return;
                        var dr = rc.message.default_rounds || 3;
                        var mr = rc.message.max_rounds || 99;
                        let dialog = new frappe.ui.Dialog({
                            title: __('Add Extra Round'),
                            fields: [
                                {
                                    fieldname: 'workstation',
                                    fieldtype: 'Link',
                                    label: __('Workstation'),
                                    options: 'Workstation',
                                    reqd: 1,
                                    get_query: function() {
                                        return {
                                            query: "caf.caf.doctype.daily_production.daily_production.get_machine_table_workstations",
                                        };
                                    }
                                },
                                {
                                    fieldname: 'total_rounds',
                                    fieldtype: 'Int',
                                    label: __('Total Rounds'),
                                    reqd: 1
                                }
                            ],
                            primary_action_label: __('Add'),
                            primary_action: function(values) {
                                if (parseInt(values.total_rounds) <= dr) {
                                    frappe.show_alert({ message: __('Total rounds must be greater than default ({0})', [dr]), indicator: 'red' }, 3);
                                    return;
                                }
                                if (parseInt(values.total_rounds) > mr) {
                                    frappe.show_alert({ message: __('Total rounds cannot exceed max ({0})', [mr]), indicator: 'red' }, 3);
                                    return;
                                }
                                dialog.hide();
                        frappe.call({
                            method: "caf.caf.doctype.daily_production.daily_production.add_extra_round",
                            args: {
                                docname: frm.docname,
                                workstation: values.workstation,
                                total_rounds: values.total_rounds
                            },
                            callback: function(r) {
                                if (r.message) {
                                    frm.reload_doc();
                                    frappe.show_alert({
                                        message: __('Extra rounds added for {0}', [values.workstation]),
                                        indicator: 'green'
                                    });
                                }
                            }
                        });
                    }
                });
                dialog.show();
                    }
                });
            }, __('Extras'));
        }
        const urlParams = new URLSearchParams(window.location.search);
        const editName = urlParams.get('row');
        const editIdx = urlParams.get('edit_idx');

        if (editName || editIdx) {
            let grid = frm.fields_dict['production_table'].grid;
            let row = null;

            if (editName) {
                row = grid.grid_rows.find(r => r.doc.name === editName);
            } else if (editIdx) {
                row = grid.grid_rows.find(r => r.doc.idx == editIdx);
            }

            if (row) {
                grid.refresh_row(row.doc.name);
                show_dp_edit_dialog(frm, 'Create ProExl Items', row.doc.name);

                const params = new URLSearchParams(window.location.search);
                params.delete('row');
                params.delete('edit_idx');
                const newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
                window.history.replaceState({}, document.title, newUrl);
            }
        }
        install_dp_edit_interceptor(frm);
    }
});
