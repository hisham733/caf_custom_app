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
        "recipe_name": 2,
        "size": 1,
        "recipe_cook_workstaion": 2,
        "recipe_cook_round": 1,
        "custom_yield": 1,
        "produ_status": 3,
        "number_of_pack": 1
    };

    grid.docfields.forEach(df => {
        if (grid_layout[df.fieldname]) {
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

function filter_produ_status(frm, cdn) {
    const grid = frm.fields_dict["production_table"]?.grid;
    if (!grid) return;
    const row = locals["Create ProExl Items"]?.[cdn];
    if (!row) return;
    const grid_row = grid.get_row(cdn);
    if (!grid_row) return;
    const field = grid_row.get_field("produ_status");
    if (!field) return;
    const full = "\nNew Schedule\nRecipe Change\nCancelled\nChange Slot\nRearrange\nOnly Remark\nPack Change\nSingle WO";
    const options = (!row.recipe_name || row.recipe_name === "No Cooking") ? "\nNew Schedule\nChange Slot" : full;
    field.df.options = options;
    field.set_options();
}


// =================================================================
// PARENT DOCTYPE: DAILY PRODUCTION (Unified Block)
// =================================================================

frappe.ui.form.on("Daily Production", {
    onload: function(frm) {
        if (frm.is_new()) { frm.set_value("planner_name", frappe.session.user_fullname); }
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
            grid.cannot_add_rows = (frm.doc.production_table || []).length >= MAX_ROWS;
        }
        setup_production_grid(frm);

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
        if (frm.doc.docstatus === 1 && frm.doc.workflow_state === "Submitted") {
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

    after_save: function(frm) { debounced_apply_colors(frm); },

    before_submit: function(frm) {
        show_loading_overlay();
        const cancel_rows = (frm.doc.production_table || []).filter(r => r.produ_status === 'Cancelled');
        if (cancel_rows.length > 0) {
            frappe.validated = false;
            const recipe_list = cancel_rows.map(r => `<li>${r.recipe_name || 'Row ' + r.idx}</li>`).join('');
            frappe.confirm(
                __(`<b>${cancel_rows.length} row(s) are marked for cancellation:</b><ul>${recipe_list}</ul> Their Work Orders will be cancelled on submit. Proceed?`),
                () => { frappe.validated = true; frm.save('Submit'); },
                () => { hide_loading_overlay(); }
            );
        }
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

        const start_index = current_row.idx - 1;
        frappe.model.set_value(cdt, cdn, 'number_of_pack', 0);

        const pack_fields_to_clear = ['pack_name', 'pack_machine', 'pack_time', 'pack_round'];
        for (let i = start_index + 1; i < frm.doc.production_table.length; i++) {
            const subsequent_row = frm.doc.production_table[i];
            if (subsequent_row.recipe_name) break;
            pack_fields_to_clear.forEach(field => { frappe.model.set_value(subsequent_row.doctype, subsequent_row.name, field, null); });
        }

        // ── Fetch custom_yield from BOM ──
        if (!current_row.recipe_name || current_row.recipe_name === "No Cooking") {
            frappe.model.set_value(cdt, cdn, 'custom_yield', null);
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
        const size = flt(row.size);

        if (size <= 0.0 && flt(row.number_of_pack) !== 0) {
            frappe.show_alert({ message: __("Size is required!"), indicator: 'red' }, 3);
            frappe.model.set_value(cdt, cdn, "number_of_pack", 0);

            const grid_row = frm.fields_dict["production_table"].grid.get_row(cdn);
            if (grid_row) {
                const $size_field = grid_row.get_field("size").$wrapper;
                $size_field.css({"background-color": "#ffcccc", "border": "2px solid red", "transition": "all 0.3s"});
                $size_field.find('input').focus();
                setTimeout(() => {
                    $size_field.css({"background-color": "", "border": ""});
                }, 2500);
            }
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
    },

    size: function(frm, cdt, cdn) { validate_field_dependency(frm, cdt, cdn, 'size', 'recipe_name', 'Recipe Name'); },
    recipe_cook_workstaion: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'recipe_cook_workstaion', 'recipe_name', 'Recipe Name')) { try { validate_unique_cook_combination(frm, cdt, cdn); } catch (e) { frappe.model.set_value(cdt, cdn, 'recipe_cook_round', ''); } } },
    recipe_cook_round: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'recipe_cook_round', 'recipe_name', 'Recipe Name')) { try { validate_unique_cook_combination(frm, cdt, cdn); } catch (e) { frappe.model.set_value(cdt, cdn, 'recipe_cook_workstaion', ''); } } },
    pack_machine: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'pack_machine', 'pack_name', 'Pack Name')) { try { validate_unique_cook_combination_pack(frm, cdt, cdn); } catch (e) { frappe.model.set_value(cdt, cdn, 'pack_round', ''); } } },
    pack_round: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'pack_round', 'pack_name', 'Pack Name')) { try { validate_unique_cook_combination_pack(frm, cdt, cdn); } catch (e) { frappe.model.set_value(cdt, cdn, 'pack_machine', ''); } } },
    recipe_cook_time: function(frm, cdt, cdn) { if (validate_field_dependency(frm, cdt, cdn, 'recipe_cook_time', 'recipe_name', 'Recipe Name')) { revalidate_subsequent_pack_times(frm, cdt, cdn); } }
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

const PROTECTED_HARDWARE = ['recipe_cook_workstaion', 'recipe_cook_round', 'link_id'];
const SYSTEM_FIELDS = ['name', 'owner', 'creation', 'modified', 'modified_by', 'parent', 'parentfield', 'parenttype', 'idx', 'doctype'];

/** Gets all user-data fields that are allowed to be moved or swapped */
function get_moveable_fields(doctype) {
    const meta = frappe.get_meta(doctype);
    const non_data_types = ['Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Heading', 'Fold'];
    return meta.fields
        .filter(f => !PROTECTED_HARDWARE.includes(f.fieldname) && !SYSTEM_FIELDS.includes(f.fieldname) && !non_data_types.includes(f.fieldtype))
        .map(f => f.fieldname);
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
            row.show_form();
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

            const fields = get_moveable_fields(source_row.doctype);
            const swaps = fields.map(fn => ({ fn, s_val: source_row[fn], t_val: target_row[fn] }));
            // Direct locals assignment bypasses field change handlers that could corrupt values
            swaps.forEach(({ fn, s_val, t_val }) => {
                locals[source_row.doctype][source_row.name][fn] = t_val;
                locals[target_row.doctype][target_row.name][fn] = s_val;
            });

            action_applied = true;
            const pair_id = Date.now().toString(36) + Math.random().toString(36).substr(2, 9);
            frappe.model.set_value(source_row.doctype, source_row.name, 'produ_status', 'Rearrange');
            frappe.model.set_value(target_row.doctype, target_row.name, 'produ_status', 'Rearrange');
            frappe.model.set_value(source_row.doctype, source_row.name, 'custom_pair_id', pair_id);
            frappe.model.set_value(target_row.doctype, target_row.name, 'custom_pair_id', pair_id);

            frm.refresh_field("production_table");
            frm.save().then(() => { d.hide(); reopen_pencil_dialog(frm, source_row.name); }, () => { d.hide(); });
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

            const fields = get_moveable_fields(child_doctype);
            const swaps = fields.map(fn => ({ fn, s_val: source_row[fn], t_val: target_row[fn] }));
            swaps.forEach(({ fn, s_val, t_val }) => {
                locals[source_row.doctype][source_row.name][fn] = t_val;
                locals[target_row.doctype][target_row.name][fn] = s_val;
            });

            action_applied = true;
            const pair_id = Date.now().toString(36) + Math.random().toString(36).substr(2, 9);

            frappe.model.set_value(target_row.doctype, target_row.name, 'produ_status', 'Change Slot');
            frappe.model.set_value(source_row.doctype, source_row.name, 'produ_status', 'Change Slot');
            frappe.model.set_value(target_row.doctype, target_row.name, 'custom_pair_id', pair_id);
            frappe.model.set_value(source_row.doctype, source_row.name, 'custom_pair_id', pair_id);

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
        let field_configs = {};
        const status = row.produ_status;
        const is_no_cook = !row.recipe_name || row.recipe_name === "" || row.recipe_name === "No Cooking";

        if (status === "New Schedule" ){
            if (is_no_cook){
            all_fields.forEach(f => field_configs[f] = 0);}
        }
        else if (status === "Recipe Change") {
            all_fields.forEach(f => field_configs[f] = 0);
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
            field_configs.custom_pair_id = 0;
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
            all_fields.forEach(f => field_configs[f] = 0);
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

        Object.keys(field_configs).forEach(fn => {
            frm.set_df_property('production_table', 'read_only', field_configs[fn], frm.doc.name, fn, row.name);
        });

        PROTECTED_HARDWARE.forEach(fn => {
            frm.set_df_property('production_table', 'read_only', 1, frm.doc.name, fn, row.name);
        });

        let grid = frm.get_field("production_table").grid;
        if (grid) {
            grid.refresh_row(row.name);
            if (grid.grid_row_form && grid.grid_row_form.wrapper.is(':visible')) grid.grid_row_form.refresh();
        }
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
    }
});

// =================================================================
// New Version JS
// =================================================================

frappe.ui.form.on("Daily Production", {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.workflow_state === "Submitted") {
            frappe.db.count("Daily Production", {
                filters: {
                    "custom_submit_ref": frm.doc.name
                }
            }).then(count => {
                frm.add_custom_button("New Version", function() {
                    frappe.confirm(
                        "Are you sure you want to create a new version?",
                        function() {
                            frappe.call({
                                method: "caf.caf.doctype.daily_production.daily_production.create_new_dp",
                                args: {
                                    docname: frm.doc.name,
                                    doctype: frm.doc.doctype
                                },
                                callback: function(r) {
                                    if (r.message) {
                                        frappe.msgprint("New version created successfully!");
                                        frappe.set_route("Form", "Daily Production", r.message);
                                    }
                                }
                            });
                        },
                        function() {
                            frappe.msgprint("Action cancelled");
                        }
                    );
                });
            });
        }
    }
});

// =================================================================
// URL Param Row Opener
// =================================================================

frappe.ui.form.on('Daily Production', {
    refresh: function(frm) {
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
                row.show_form();

                const params = new URLSearchParams(window.location.search);
                params.delete('row');
                params.delete('edit_idx');
                const newUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
                window.history.replaceState({}, document.title, newUrl);
            }
        }
    }
});

// =================================================================
// Ctrl+Shift+Enter — Save & Close with Metabase Refresh
// =================================================================

frappe.ui.form.on('Create ProExl Items', {
    form_render: function(frm, cdt, cdn) {
        let table_fieldname = "production_table";
        let grid_row = frm.fields_dict[table_fieldname].grid.grid_rows_by_docname[cdn];

        if (!grid_row || !grid_row.grid_form) return;

        let wrapper = grid_row.grid_form.wrapper;
        wrapper.attr('tabindex', 0);
        wrapper.off('keydown.ctrlshiftenter');

        wrapper.on('keydown.ctrlshiftenter', async function(e) {
            if (e.ctrlKey && e.shiftKey && e.key === 'Enter') {
                e.preventDefault();
                e.stopPropagation();

                try {
                    $(document.activeElement).blur();
                    await frappe.utils.sleep(200);

                    await frm.save();

                    frappe.show_alert({
                        message: __('Success! Syncing Metabase...'),
                        indicator: 'green'
                    });

                    grid_row.hide_form();

                    document.cookie = "trigger_metabase_refresh=true; path=/; domain=192.168.0.251; max-age=10";

                    setTimeout(() => {
                        window.close();
                    }, 500);

                } catch (err) {
                    console.error("❌ ERROR:", err);
                    frappe.msgprint({
                        title: __('Error'),
                        message: err.message || err,
                        indicator: 'red'
                    });
                }
            }
        });
    }
});
