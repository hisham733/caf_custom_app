// my_custom_app/public/js/work_order.js

frappe.ui.form.on("Work Order", {
    /**
     * This event runs once after the form is fully rendered.
     * Its job is to safely store the original ERPNext 'setup' function
     * before we override it. This is the key to making our script maintainable.
     */
    onload_post_render: function(frm) {
        console.log("Debug: Storing original ERPNext setup function for Work Order.");
        // Store original 'setup' in a new variable
        if (frm.cscript.setup) {
            frm.cscript.erpnext_original_setup = frm.cscript.setup;
        }
    },

    //================================================================================
    // SETUP: Runs ONCE when the form loads.
    //================================================================================
    setup: function (frm) {
        // --- ✅ STEP 1: RUN THE ORIGINAL ERPNext SETUP LOGIC ---
        // This ensures all standard ERPNext queries and settings are applied first.
        if (frm.cscript.erpnext_original_setup) {
            frm.cscript.erpnext_original_setup(frm);
        }
        console.log("Debug: CAF custom setup logic is now running.");


        // --- ✅ STEP 2: APPLY YOUR EXISTING SETUP CUSTOMIZATIONS ---
        
        // This is a safer way to modify the buttons object.
        // It merges your changes into the existing object.
        frm.custom_make_buttons = {
                    // Customizing which buttons are shown
                    // "Stock Entry": "Start Manufacturing",  // Custom action name
                    // "Pick List": "Create Pick List",
                    // "Job Card": "Create Job Card",
                };


        // (Add your other set_query calls here if you have more)


        // --- ✅ STEP 3: OVERRIDE THE HELPER FUNCTIONS ---
        // This is where you replace the standard ERPNext functions with your custom versions.
        
        console.log("Debug: Overriding erpnext.work_order .");
        erpnext.work_order.show_prompt_for_qty_input = async function (frm, purpose) {
            let self = this;
            let max = self.get_max_transferable_qty(frm, purpose);
        
            // Use a Promise to wrap the entire async operation
            return new Promise(async (resolve, reject) => {
                try {
                    // Step 1: Get BOM details
                    const bom_response = await frappe.call({
                        method: "frappe.client.get",
                        args: { doctype: "BOM", name: frm.doc.bom_no },
                    });
                    let single_scrap_item_code = "";
                    let singel_item_target_warehouse = "";
                    let finish_mark = 1;
                    let scrap_items = bom_response.message?.scrap_items || [];
                    let has_scrap_item = scrap_items.length > 0;
                                        
                    if (has_scrap_item){
                        console.log("has_scrap_item",has_scrap_item);
                    
                        single_scrap_item_code = scrap_items[0].item_code;
                        singel_item_target_warehouse = scrap_items[0].custom_warehouse;
                    }
        

        
                    // Step 2: Get Pack Qty and Item Group in parallel for efficiency
                    const [pack_response, item_group_response] = await Promise.all([
                        frappe.call({
                            doc: frm.doc,
                            method: "get_pack_qty",
                            args: { work_order_id: frm.doc.name },
                        }),
                        frappe.call({
                            doc: frm.doc,
                            method: "get_item_group_for_ig",
                        })
                    ]);
                    console.log("pack_response.message",pack_response.message,"frm.doc.qty",frm.doc.qty)

                    let total_weight = (flt(pack_response.message) > flt(frm.doc.qty))
                        ? flt(pack_response.message) - flt(frm.doc.produced_qty)
                        : flt(frm.doc.qty) - flt(frm.doc.produced_qty);
                    console.log("total_weight",total_weight)
                    const item_group = item_group_response.message;
                    let batch_item_code = frm.doc.production_item;
                    const item_type = frm.doc.custom_item_type;
        
                    // Define the base fields
                    let fields = [{
                        fieldtype: "Float",
                        label: __("Qty for {0}", [__(purpose)]),
                        fieldname: "qty",
                        description: __("Max: {0}", [max]),
                        default: max,
                        read_only: has_scrap_item ? 1 : 0,
                        hidden: (purpose === "Manufacture" && has_scrap_item)? true : false
                    }];
        
                    // --- The logic is now much clearer ---
                    if (purpose === "Material Transfer for Manufacture" && item_group === "CHIC WIP") {
                        console.log(purpose,item_group)
                        const first_material = frm.doc.required_items?.[0];
                        console.log(first_material)
                        if (first_material) {
                            batch_item_code = first_material.item_code;
                            
                            // Step 3 (Conditional): Get the latest batch
                            const batch_res = await frappe.call({
                                method: "frappe.client.get_list",
                                args: {
                                    doctype: "Batch",
                                    filters: { item: batch_item_code },
                                    fields: ["name"],
                                    order_by: "creation desc",
                                    limit_page_length: 1
                                }
                            });
                            const default_batch = batch_res.message?.[0]?.name || "";
                            
                            // Add the batch field
                            fields.push({
                                fieldtype: "Link",
                                label: __("Select Batch for Item"),
                                fieldname: "batch_no",
                                options: "Batch",
                                get_query: () => ({ filters: { item: batch_item_code } }),
                                default: default_batch,
                                reqd: 1
                            });
                        }
                    }
        
                    // Add other conditional fields
                    if (purpose === "Manufacture" && has_scrap_item && item_type) {
                        fields.push(
                            { fieldtype: "Float", label: __("<b>Total Qty</b>"), fieldname: "total_pack_qty", default: total_weight, read_only: 0, bold: 1 },
                            { fieldtype: "Section Break" },
                            {fieldtype: "Float",label: __("Total Balance") + ` (<b>${single_scrap_item_code}</b>)`,fieldname: "total_balance",default: frm.doc.total_balance || 0,read_only: 0},
                            { fieldtype: "Column Break" },
                            { fieldtype: "Data", label: __("<b>Balance warehouse</b>"), fieldname: "warehouse", default: singel_item_target_warehouse, read_only: 1, bold: 1 },
                            { fieldtype: "Section Break" },
                            { fieldtype: "Data", label: __("<b>Item Type</b>"), fieldname: "item_type", default: item_type, read_only: 1, bold: 1 },
                            { fieldtype: "Check", label: __("<b>Finish</b>"), fieldname: "finish_mark", default: finish_mark, read_only: 0, bold: 1 },
                        );
                    }
        
                    // Finally, show the prompt with all the collected fields
                    frappe.prompt(fields, (data) => {
                        max += (frm.doc.qty * (frm.doc.__onload?.overproduction_percentage || 0.0)) / 100;
                        if (data.qty > max) {
                            frappe.msgprint(__("Quantity must not be more than {0}", [max]));
                            return reject();
                        }
        
                        data.purpose = purpose;
                        data.total_pack_qty = data.total_pack_qty || total_weight;
                        data.item_type = item_type;
        
                        if (data.batch_no) {
                            frm.doc.selected_batch = data.batch_no;
                            frm.doc.batch_for_item_code = batch_item_code;
                        }
                        
                        resolve(data);
                    }, __("Select Quantity"), __("Create"));
        
                } catch (err) {
                    console.error("Error in show_prompt_for_qty_input:", err);
                    reject(err);
                }
            });
        }.bind(erpnext.work_order);
        
        

        
        // ---- Override of helper function: make_se (Stock Entry) ----
        erpnext.work_order.make_se = function (frm, purpose) {
            let self = this;
            self.show_prompt_for_qty_input(frm, purpose)
                .then((data) => {
                    // Call the standard backend method with your new custom fields
                    return frappe.xcall("erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry", {
                        work_order_id: frm.doc.name, purpose: purpose, qty: data.qty,
                        total_balance: data.total_balance, total_pack_qty: data.total_pack_qty, item_type: data.item_type, warehouse: data.warehouse,
                        finish_mark: data.finish_mark
                    });
                })
                .then((stock_entry) => {
                    frappe.model.sync(stock_entry);
                    return frm.reload_doc().then(() => {
                        frappe.set_route("Form", stock_entry.doctype, stock_entry.name);

                });
            })
                .catch((err) => {
                    frappe.msgprint(err.message || __("Error creating stock entry. See console for details."));
                    console.error("Error in make_se:", err);
                });
        }.bind(erpnext.work_order); // .bind() is CRITICAL for 'this' to work correctly
        frm.cscript.old_weight_record = frm.doc.custom_weight_record;
    },
        // This is the trigger that runs when the user selects a new value.
    // IMPORTANT: Replace 'custom_weight_record' with your REAL fieldname.
    custom_weight_record: function(frm) {
        
        // 1. Get the NEW Weight Record the user just selected.
        let new_weight_record = frm.doc.custom_weight_record;
        
        // 2. Get the OLD Weight Record from the variable we saved in setup.
        let old_weight_record = frm.cscript.old_weight_record;
        
        // 3. Get the name of the current Work Order.
        let current_work_order = frm.doc.name;

        // --- Step A: Clear the link from the OLD record ---
        
        // Check if there was an old record and if it's different from the new one.
        if (old_weight_record && old_weight_record !== new_weight_record) {
            console.log("Clearing Work Order from old record: " + old_weight_record);
            
            // This makes ONE efficient call to the server to update all three fields.
            frappe.db.set_value('Weight Record', old_weight_record, {
                'work_order': null,
                'link_id': null,
                'wo_item': null
            })

                .then(r => {
                    frappe.show_alert({
                        message: __('Unlinked from previous record: ' + old_weight_record),
                        indicator: 'orange'
                    }, 3);
                });
        }

        // --- Step B: Set the link on the NEW record ---
        
        // Check if the user selected a new record.
        if (new_weight_record) {
            console.log("Linking Work Order '" + current_work_order + "' to new record: " + new_weight_record);
            
            // Set the 'work_order' field in the new record to the current Work Order name.
            frappe.db.set_value('Weight Record', new_weight_record, 'work_order', current_work_order)
                .then(r => {
                    frappe.show_alert({
                        message: __('Updated new record: ' + new_weight_record),
                        indicator: 'green'
                    }, 5);
                });
        }
        
        // --- Step C: Update our memory for the next change ---
        
        // After we're done, we update our 'old_weight_record' variable
        // so it's ready for the next time the user changes the field.
        frm.cscript.old_weight_record = new_weight_record;
    }

    // You can add your custom refresh logic here later if needed
});
// ------------------------------------------------------------------------------------------

frappe.ui.form.on("Work Order", {
    refresh(frm) {
        // Run our main logic to decide which buttons to show.
        setup_custom_wo_buttons(frm);
    }
});

/**
 * Hides or shows standard Work Order buttons based on a condition.
 * @param {object} frm - The form object.
 * @param {boolean} hide - If true, hides the buttons. If false, shows them.
 */

function toggle_standard_wo_buttons(frm, hide) {
    const action = hide ? 'hide' : 'show';
    
    // Use a short delay with setTimeout to ensure all buttons are rendered before we try to manipulate them.
    // This is the most reliable way to handle timing issues.
    setTimeout(() => {
        // --- Selector for the PRIMARY ACTION BUTTONS (like 'Start' or 'Stop') ---
        // These are often primary buttons, not just dropdown items.
        // We find any button in the page header that has the text "Start" or "Stop".
        frm.page.wrapper.find(`.page-head .btn-primary:contains('Start')`)[action]();
        frm.page.wrapper.find(`.page-head .btn-primary:contains('Stop')`)[action]();
        frm.page.wrapper.find(`.page-head .btn-primary:contains('Finish')`)[action]();

        // --- Selector for the "Create" dropdown menu ---
        const create_button_group = frm.page.inner_toolbar.find(".buttons-in-group");

        if (create_button_group.length) {
            // --- Selectors for items INSIDE the "Create" dropdown ---
            // We find the list items (<li>) inside the menu that contain the text we want.
            create_button_group.find("li:contains('Job Card')")[action]();
            create_button_group.find("li:contains('Stock Entry')")[action]();
            create_button_group.find("li:contains('Pick List')")[action]();
        }
    }, 100); // A small delay of 100ms is usually sufficient.
}

function setup_custom_wo_buttons(frm) {
    const our_button_group = "Auto Process Button Group";

    // Only show for submitted Work Orders that are not completed
    if (frm.doc.docstatus === 1 && frm.doc.status !== "Completed") {

        frappe.call({
            method: "caf.caf.overrides.work_order.check_for_job_cards",
            args: { work_order_name: frm.doc.name },
            freeze: true,
            freeze_message: __("Checking Work Order configuration..."),
            callback: function(response) {
                setTimeout(() => {
                    const has_job_cards = response.message;

                    // Remove duplicate button (if any)
                    frm.remove_custom_button("Auto Start + Finish");

                    // CONDITION: No job cards and in Ingredient Room
                    if (!has_job_cards && frm.doc.wip_warehouse === "W Ingredient Room - CAF") {

                        // Hide standard Work Order buttons
                        toggle_standard_wo_buttons(frm, true);

                        // Add our single automation button
                        frm.add_custom_button(
                            __("Auto Start + Finish"),
                            function() {
                                frappe.confirm(
                                    __("Are you sure you want to auto-start and finish this Work Order?"),
                                    function() {
                                        frappe.call({
                                            method: "caf.caf.overrides.work_order.automate_start_finish",
                                            args: {
                                                work_order_name: frm.doc.name,
                                                total_balance: 0,
                                                total_pack_qty: frm.doc.qty || 0
                                            },
                                            freeze: true,
                                            freeze_message: __("Running Auto Process..."),
                                            callback: function() {
                                                // Python already shows frappe.msgprint
                                                frm.reload_doc();
                                            },
                                            error: function() {
                                                frappe.msgprint({
                                                    title: __("Error"),
                                                    message: __("Something went wrong. Please check the Error Log."),
                                                    indicator: "red"
                                                });
                                            }
                                        });
                                    }
                                );
                            },
                            
                        );

                    } else {
                        // Restore default Work Order buttons
                        toggle_standard_wo_buttons(frm, false);
                    }
                }, 0);
            }
        });

    } else {
        // Clean up if Work Order is not in correct state
        frm.remove_custom_button("Auto Start + Finish");
        toggle_standard_wo_buttons(frm, false);
    }
}




frappe.ui.form.on('Work Order', {
    bom_no(frm) {
        if (frm.doc.bom_no) {
            frappe.call({
                // doc: frm.doc,
                method: "caf.caf.overrides.work_order.fetch_bom_custom_procedures",
                args: {
                    bom_no: frm.doc.bom_no
                },
                callback: function(r) {
                    if (r.message) {
                        // Clear existing table
                        frm.clear_table("custom_procedure");

                        // Add fetched rows
                        r.message.forEach(row => {
                            let new_row = frm.add_child("custom_procedure");
                            new_row.procedure = row.procedure;
                            // new_row.description = row.description;
                            // new_row.sequence = row.sequence;
                        });

                        // Refresh the table field
                        frm.refresh_field("custom_procedure");

                        // frappe.show_alert({
                        //     message: __("Custom Procedures loaded from BOM."),
                        //     indicator: "green"
                        // });
                    }
                }
            });
        } else {
            // If BOM is cleared, also clear the custom_procedure table
            frm.clear_table("custom_procedure");
            frm.refresh_field("custom_procedure");
        }
    }
});

frappe.ui.form.on('Work Order', {
    refresh(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('New Weight Record'), function () {
                frappe.call({
                    method: "caf.caf.overrides.work_order.create_weight_record",
                    args: {
                        work_order: frm.doc.name
                    },
                    callback: function (r) {
                        if (r.message && r.message.name) {
                            frappe.msgprint({
                                title: __('Success'),
                                indicator: 'green',
                                message: `✅ Weight Record created: <b>${r.message.name}</b>`
                            });
                            frappe.set_route("Form", "Weight Record", r.message.name);
                        } else {
                            frappe.msgprint({
                                title: __('Error'),
                                indicator: 'red',
                                message: __('❌ Failed to create Weight Record.')
                            });
                        }
                    }
                });
            }, __('Create'));
        }
    }
});



frappe.ui.form.on('Work Order', {
    custom_rawmat_check(frm) {
        frappe.call({
            method: 'caf.caf.overrides.work_order.update_next_rawmat',
            args: {
                work_order: frm.doc.name
            },
            freeze: true,
            callback(r) {
                if (!r.exc) {
                    frm.reload_doc();
                }
            }
        });
    }
});

frappe.ui.form.on('Work Order', {
    custom_rawmat_in(frm) {
        frappe.call({
            method: 'caf.caf.overrides.work_order.update_next_rawmat_in',
            args: {
                work_order: frm.doc.name
            },
            freeze: true,
            callback(r) {
                if (!r.exc) {
                    frm.reload_doc();
                }
            }
        });
    }
});




frappe.ui.form.on('Work Order Item', {
  async custom_rawmat_in(frm, cdt, cdn) {
    const child = locals[cdt][cdn];

    if (child.custom_rawmat_in) {
      try {
        // ✅ Use frappe.call instead of frappe.db.exists
        const { message } = await frappe.call({
          method: "frappe.client.get_list",
          args: {
            doctype: "Stock Entry",
            filters: {
              work_order: frm.doc.name,
              stock_entry_type: "Material Transfer for Manufacture",
              docstatus: 1
            },
            fields: ["name"],
            limit: 1
          }
        });

        if (!message || message.length === 0) {
          frappe.model.set_value(cdt, cdn, "custom_rawmat_in", 0);
          frappe.throw(__("Please submit a Stock Entry (Material Transfer for Manufacture) for this Work Order before checking this box."));
        }

        // ✅ If a Stock Entry exists
        frappe.model.set_value(cdt, cdn, "custom_operator_name_for_in", frappe.session.user_fullname);
        frappe.model.set_value(cdt, cdn, "custom_time_in", frappe.datetime.now_datetime());
        frappe.meta.get_docfield("Work Order Item", "custom_rawmat_in", frm.doc.name).read_only = 1;
        frm.refresh_field("required_items");

      } catch (e) {
        console.error("Error checking Stock Entry:", e);
        frappe.throw(__("Error while checking Material Transfer for Manufacture status."));
      }
    }
  }
});









frappe.ui.form.on("Work Order Item", {
  custom_rawmat_check: function (frm, cdt, cdn) {
    let total_qty = 0;

    // Sum all qty values
    frm.doc.required_items.forEach(row => {
      total_qty += flt(row.required_qty);
    });

    // Calculate and set percentage
    frm.doc.required_items.forEach(row => {
      let percentage = total_qty ? (flt(row.required_qty) / total_qty) * 100 : 0;
      row.custom_item_percentage = percentage.toFixed(8); // keep up to 8 decimals
    });

    frm.refresh_field("required_items");
  }
});





frappe.ui.form.on('Work Order', {
    refresh: function(frm) {

        // Check if any Job Card exists for this Work Order
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Job Card',
                filters: { work_order: frm.doc.name, status: ['!=', 'Cancelled'], status: ['!=', 'Closed'], status: ['!=', 'Completed'] },
                fields: ['name', 'operation', 'status'],
                limit_page_length: 1
            },
            callback: function(r) {
                if (r.message && r.message.length) {
                    // Add button only if at least one Job Card exists
                    frm.add_custom_button(__('Open Job Card'), function() {

                        // Fetch all Job Cards linked to this Work Order
                        frappe.call({
                            method: 'frappe.client.get_list',
                            args: {
                                doctype: 'Job Card',
                                filters: { work_order: frm.doc.name },
                                fields: ['name', 'operation', 'status'],
                                order_by: 'creation desc',
                                limit_page_length: 100
                            },
                            callback: function(res) {
                                let job_cards = res.message;

                                if (job_cards.length === 1) {
                                    frappe.set_route('Form', 'Job Card', job_cards[0].name);
                                    return;
                                }

                                // Multiple Job Cards → selection dialog
                                let options = job_cards.map(jc => ({
                                    label: `${jc.operation} [${jc.status}]`,
                                    value: jc.name  // still store Job Card ID internally
                                }));

                                let d = new frappe.ui.Dialog({
                                    title: __('Select Job Card to Open by Operation'),
                                    fields: [{
                                        fieldtype: 'Select',
                                        fieldname: 'job_card',
                                        options: options,
                                        label: __('Operation')
                                    }],
                                    primary_action_label: __('Open'),
                                    primary_action(values) {
                                        frappe.set_route('Form', 'Job Card', values.job_card);
                                        d.hide();
                                    }
                                });

                                d.show();
                            }
                        });

                    }).addClass('btn-primary');
                }
            }
        });

    }
});




// ####################################################################
// UPDATE WORKSTATION BUTTON
// ####################################################################

frappe.ui.form.on('Work Order', {
    refresh(frm) {
        // existing Recook button
        if (frm.doc.docstatus === 1 && frm.doc.custom_item_type === "Cook") {
            frm.add_custom_button(__('Recook'), function() {
                show_recook_dialog(frm);
            }, __('Create'));
        }

        // NEW: Update Workstation button (any submitted Work Order with operations)
        if (frm.doc.docstatus === 1 && frm.doc.operations && frm.doc.operations.length) {
            if (frm.doc.custom_item_type === "Pack") {
                frm.add_custom_button(__('Update Workstation'), function() {
                    show_update_workstation_dialog(frm);
                }, __('Create'));
            }
        }
    }
});

// ------------------------------------------------------------------ //
//  DIALOG
// ------------------------------------------------------------------ //
function show_update_workstation_dialog(frm) {
    let operations = frm.doc.operations || [];

    if (!operations.length) {
        frappe.msgprint(__('No operations found on this Work Order.'));
        return;
    }

    // Build one row per operation: [read-only current WS] + [link new WS]
    let fields = [];

    operations.forEach((op, idx) => {
        // Section header = operation name
        fields.push({
            fieldtype: 'Section Break',
            label: __(op.operation || `Operation ${idx + 1}`)
        });

        fields.push({
            fieldtype: 'Column Break'
        });

        // Current workstation (read-only)
        fields.push({
            fieldtype: 'Link',
            fieldname: `current_ws_${idx}`,
            label: __('Current Workstation'),
            options: 'Workstation',
            default: op.workstation || '',
            read_only: 1
        });

        fields.push({
            fieldtype: 'Column Break'
        });

        // New workstation selector
        fields.push({
            fieldtype: 'Link',
            fieldname: `new_ws_${idx}`,
            label: __('New Workstation'),
            options: 'Workstation',
            default: op.workstation || ''
        });
    });

    let dialog = new frappe.ui.Dialog({
        title: __('Update Workstation'),
        size: 'large',
        fields: fields,
        primary_action_label: __('Update'),
        primary_action(values) {
            // Collect only rows where workstation actually changed
            let changes = [];

            operations.forEach((op, idx) => {
                let old_ws = op.workstation || '';
                let new_ws = values[`new_ws_${idx}`] || '';

                if (new_ws && new_ws !== old_ws) {
                    changes.push({
                        row_name: op.name,          // child row name for targeted update
                        operation: op.operation,
                        old_workstation: old_ws,
                        new_workstation: new_ws
                    });
                }
            });

            if (!changes.length) {
                frappe.msgprint(__('No workstation changes detected. Please select a different workstation in at least one row.'));
                return;
            }

            execute_workstation_update(frm, changes, dialog);
        }
    });

    dialog.show();
}

// ------------------------------------------------------------------ //
//  EXECUTE
// ------------------------------------------------------------------ //
function execute_workstation_update(frm, changes, dialog) {
    frappe.call({
        method: 'caf.caf.overrides.work_order.update_workstation',
        args: {
            work_order_name: frm.doc.name,
            changes: changes          // list of {row_name, operation, old_workstation, new_workstation}
        },
        freeze: true,
        freeze_message: __('Updating workstations...'),
        callback(r) {
            if (r.message && r.message.success) {
                frappe.show_alert({
                    message: r.message.message,
                    indicator: 'green'
                });
                dialog.hide();
                frm.reload_doc();
            } else {
                frappe.msgprint({
                    title: __('Update Failed'),
                    indicator: 'red',
                    message: r.message?.message || __('An unexpected error occurred.')
                });
            }
        }
    });
}
// ------------------------------------------------------------------ //
//  Recook
// ------------------------------------------------------------------ //
function show_recook_dialog(frm) {
    frappe.call({
        method: 'frappe.client.get_value',
        args: {
            doctype: 'Manufacturing Settings',
            fieldname: 'default_scrap_warehouse'
        },
        callback(sr) {
            let default_scrap_wh = sr.message?.default_scrap_warehouse || '';

            let dialog = new frappe.ui.Dialog({
                title: __('Recook Work Order'),
                fields: [
                    {
                        fieldtype: 'Link',
                        fieldname: 'production_item',
                        label: __('Item'),
                        options:'Item',
                        default: frm.doc.production_item,
                        read_only: 0,
                        get_query: function(){
                            return{
                                filters:{
                                    'item_group':'Recipe'
                                }
                            };
                        }

                    },
                    {
                        fieldtype: 'Link',
                        fieldname: 'source_warehouse',
                        label: __('Source Warehouse'),
                        options: 'Warehouse',
                        default: default_scrap_wh,
                        reqd: 1
                    },
                    { fieldtype: 'Section Break' },
                    {
                        fieldtype: 'Float',
                        fieldname: 'qty',
                        label: __('Quantity to Recook'),
                        default: 0,
                        reqd: 1
                    },
                    {
                        fieldtype: 'Check',
                        fieldname: 'auto_submit',
                        label: __('Single Warehouse / FIFO'),
                        default: 1
                    }
                ],
                primary_action_label: __('Create Stock Entry'),
                primary_action(values) {
                    validate_and_create(frm, values, dialog);
                }
            });

            dialog.show();
        }
    });
}

// ------------------------------------------------------------------ //
//  VALIDATE & CREATE
// ------------------------------------------------------------------ //
function validate_and_create(frm, values, dialog) {
    let req_qty = flt(values.qty);

    if (req_qty <= 0) {
        frappe.msgprint(__('Please enter a quantity greater than 0.'));
        return;
    }

    // ✅ Skip stock check if auto_submit is off — just create the draft
    if (!values.auto_submit) {
        execute_recook_creation(frm, values, dialog);
        return;
    }
    

    // Only check qty when auto_submit is enabled
    frappe.call({
        method: 'caf.caf.overrides.work_order.get_item_warehouse_qty',
        args: {
            item_code: frm.doc.production_item,
            warehouse: values.source_warehouse
        },
        freeze: true,
        freeze_message: __('Checking stock availability...'),
        callback(r) {
            let available_qty = flt(r.message) || 0;

            if (available_qty <= 0) {
                frappe.msgprint({
                    title: __('No Stock Available'),
                    indicator: 'red',
                    message: __(
                        'There is <b>no stock</b> available for <b>{0}</b> in warehouse <b>{1}</b>.',
                        [frm.doc.production_item, values.source_warehouse]
                    )
                });
                return;
            }

            if (req_qty > available_qty) {
                frappe.confirm(
                    __(
                        '⚠️ <b>Insufficient Stock</b><br><br>' +
                        'Requested: <b>{0}</b><br>' +
                        'Available in warehouse: <b>{1}</b><br><br>' +
                        'Do you want to proceed anyway?',
                        [req_qty, available_qty]
                    ),
                    () => execute_recook_creation(frm, values, dialog),
                    () => {}
                );
                return;
            }

            execute_recook_creation(frm, values, dialog);
        }
    });
}
// ------------------------------------------------------------------ //
//  CALLBACK TO CREATE RECOOK STOCK ENTRY
// ------------------------------------------------------------------ //
function execute_recook_creation(frm, values, dialog) {
    frappe.call({
        method: 'caf.caf.overrides.work_order.create_recook_stock_entry_backend',
        args: {
            work_order_name: frm.doc.name,
            qty: flt(values.qty),
            source_warehouse: values.source_warehouse,
            auto_submit: values.auto_submit
        },
        freeze: true,
        callback(r) {
            if (r.message && r.message.success) {
                frappe.show_alert({ message: r.message.message, indicator: 'green' });
                if (r.message.submitted) {
                    frm.reload_doc();
                } else {
                    frappe.set_route('Form', 'Stock Entry', r.message.se_name);
                }
                dialog.hide();
            } else {
                frappe.msgprint({
                    title: __('Action Failed'),
                    indicator: 'red',
                    message: r.message?.message || __('An error occurred')
                });
            }
        }
    });
}










