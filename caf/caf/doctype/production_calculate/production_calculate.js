// Copyright (c) 2025, hisham and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Production Calculate", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('Production Calculate', {
      bom_name: function(frm) {
          if (!frm.doc.bom_name) return;
  
          frappe.call({
              method: "caf.caf.doctype.recipe_bom.recipe_bom.get_pack_boms_and_weights_for_client",
              args: {
                  recipe_bom_name: frm.doc.bom_name
              },
              callback: function(r) {
                  if (r.message && Array.isArray(r.message.items)) {
                      frm.clear_table("bom");
  
                      let recipe_qty = r.message.recipe_qty || 1;
  
                      // 🔁 Save it in hidden field for later use
                      frm.set_value("recipe_qty", recipe_qty);
  
                      let total = 0;
  
                      r.message.items.forEach(function(row) {
                          const total_qty = row.qty * row.weight_kg;
                          total += total_qty;
  
                          frm.add_child("bom", {
                              item_name: row.item_name,
                              weight_kg: row.weight_kg ,
                            //   qty: row.qty,
                              total_qty: total_qty || 0
                          });
                      });
  
                      // 🔁 Set total and size
                      frm.set_value("total_bom_qty", total);
                      frm.set_value("size", total * recipe_qty);
  
                      frm.refresh_field("bom");
                      frm.refresh_field("total_bom_qty");
                      frm.refresh_field("size");
                  }
              }
          });
      }
  });
  
  frappe.ui.form.on('Related Recipe BOM Items', {
      quantity: function(frm, cdt, cdn) {
          let row = frappe.get_doc(cdt, cdn);
          row.total_qty = row.quantity * row.weight_kg;
  
          frm.refresh_field('bom');
  
          let total = 0;
          frm.doc.bom.forEach(child => {
              total += (child.total_qty || 0);
          });
  
          frm.set_value('total_bom_qty', total);
  
          // 🔁 Use saved recipe_qty from hidden field
          let recipe_qty = frm.doc.recipe_qty || 1;
          frm.set_value("size", (total / recipe_qty).toFixed(2));
          frm.refresh_field("total_bom_qty");
          frm.refresh_field("size");
      }
  });
  



//   =================================================================================================

frappe.ui.form.on("Production Calculate", {
    output_item(frm) {
        if (!frm.doc.output_item) return;

        frappe.call({
            method: "caf.caf.doctype.recipe_bom.recipe_bom.get_bom_items_for_item",
            args: {
                item_code: frm.doc.output_item
            },
            callback(r) {
                let options = r.message || [];
                frm.set_df_property("raw_mat", "options", options);
                frm.set_value("raw_mat", "");
            }
        });
    }
});


frappe.ui.form.on("Production Calculate", {
    size2(frm) {
        if (frm.scripts_running || !frm.doc.recipe__wip) return;

        if (frm.doc.size2) {
            frm.scripts_running = true;

            // clear qty before calculating
            frm.set_value("qty", "");

            frappe.call({
                method: "caf.caf.doctype.recipe_bom.recipe_bom.calculate_qty_from_size_api",
                args: {
                    item: frm.doc.recipe__wip,
                    size: frm.doc.size2
                },
                callback(r) {
                    if (r.message) {
                        frappe.model.set_value(frm.doctype, frm.docname, "qty", r.message.qty);
                        frappe.model.set_value(frm.doctype, frm.docname, "yeiled", r.message.yeiled);
                    }
                    setTimeout(() => {
                        frm.scripts_running = false;
                    }, 300);
                },
                error: () => {
                    frm.scripts_running = false;
                }
            });
        }
    },

    qty(frm) {
        if (frm.scripts_running || !frm.doc.recipe__wip) return;

        if (frm.doc.qty) {
            frm.scripts_running = true;

            // clear size before calculating
            frm.set_value("size2", "");

            frappe.call({
                method: "caf.caf.doctype.recipe_bom.recipe_bom.calculate_size_from_qty_api",
                args: {
                    item: frm.doc.recipe__wip,
                    qty: frm.doc.qty
                },
                callback(r) {
                    if (r.message) {
                        frappe.model.set_value(frm.doctype, frm.docname, "size2", r.message.size2);
                        frappe.model.set_value(frm.doctype, frm.docname, "yeiled", r.message.yeiled);
                    }
                    setTimeout(() => {
                        frm.scripts_running = false;
                    }, 300);
                },
                error: () => {
                    frm.scripts_running = false;
                }
            });
        }
    }
});


frappe.ui.form.on("Production Calculate", {
    output_item(frm) {
        // When user changes the output item, clear related fields
        frm.set_value("raw_mat", "");
        frm.set_value("raw_qty", "");
        frm.set_value("calculated_parent_qty", "");
    },

    raw_mat(frm) {
        // When user changes raw material, clear dependent fields
        frm.set_value("raw_qty", "");
        frm.set_value("calculated_parent_qty", "");

        // Optional: trigger update of available BOM items for the selected output item
        frm.trigger("calculate_parent_qty");
    },

    raw_qty(frm) {
        // When user enters or edits raw_qty, perform calculation
        frm.trigger("calculate_parent_qty");
    },

    calculate_parent_qty(frm) {
        if (!frm.doc.output_item || !frm.doc.raw_mat || !frm.doc.raw_qty) return;

        frappe.call({
            method: "caf.caf.doctype.recipe_bom.recipe_bom.calculate_parent_output",
            args: {
                parent_item: frm.doc.output_item,
                bom_item_code: frm.doc.raw_mat,
                available_qty: frm.doc.raw_qty
            },
            callback(r) {
                if (r.message) {
                    frm.set_value("calculated_parent_qty", r.message.possible_parent_qty);
                    // frappe.msgprint(
                    //     `Based on ${frm.doc.raw_qty} kg of ${frm.doc.raw_mat}, 
                    //     you can produce approximately ${r.message.possible_parent_qty.toFixed(4)} kg of ${frm.doc.output_item}.`
                    // );
                }
            }
        });
    }
});

frappe.ui.form.on("Production Calculate", {
    output_item(frm) {
        frm.set_value("raw_mat", "");
        frm.set_value("raw_qty", "");
        frm.set_value("calculated_parent_qty", "");
    },

    raw_mat(frm) {
        frm.set_value("raw_qty", "");
        frm.set_value("calculated_parent_qty", "");
    },

    raw_qty(frm) {
        if (frm.scripts_running || !frm.doc.raw_mat || !frm.doc.output_item) return;
        frm.scripts_running = true;

        // calculate parent qty from raw_qty
        frappe.call({
            method: "caf.caf.doctype.recipe_bom.recipe_bom.calculate_parent_output",
            args: {
                parent_item: frm.doc.output_item,
                bom_item_code: frm.doc.raw_mat,
                available_qty: frm.doc.raw_qty
            },
            callback(r) {
                if (r.message) {
                    frm.set_value("calculated_parent_qty", r.message.possible_parent_qty);
                }
                setTimeout(() => frm.scripts_running = false, 300);
            },
            error: () => frm.scripts_running = false
        });
    },

    calculated_parent_qty(frm) {
        if (frm.scripts_running || !frm.doc.raw_mat || !frm.doc.output_item) return;
        frm.scripts_running = true;

        // calculate raw_qty from parent_qty
        frappe.call({
            method: "caf.caf.doctype.recipe_bom.recipe_bom.calculate_raw_needed",
            args: {
                parent_item: frm.doc.output_item,
                bom_item_code: frm.doc.raw_mat,
                parent_qty: frm.doc.calculated_parent_qty
            },
            callback(r) {
                if (r.message) {
                    frm.set_value("raw_qty", r.message.required_raw_qty);
                }
                setTimeout(() => frm.scripts_running = false, 300);
            },
            error: () => frm.scripts_running = false
        });
    }
});



frappe.ui.form.on("Production Calculate", {
    refresh(frm) {
        frm.set_query("output_item", function() {
            return {
                query: "caf.caf.doctype.recipe_bom.recipe_bom.get_single_bom_items"
            };
        });
    }
});




let is_scaling = false;

frappe.ui.form.on("Production Calculate", {
    setup: function(frm) {
        // CSS for a dark blue row with bold white text
        $('style').append(`
            .master-row-highlight {
                background-color: #0056b3 !important; 
            }
            .master-row-highlight .grid-static-col {
                color: #ffffff !important;
                font-weight: bold !important;
            }
            /* Ensures inputs inside the highlighted row also look good */
            .master-row-highlight input {
                color: #000000 !important;
                background-color: #ffffff !important;
            }
        `);
    },
    recipe_name1: function(frm) {
        fetch_bom_items(frm);
    },

    // Reset logic when size1 returns to 1 manually
    size1: function(frm) {
        if (frm.doc.size1 === 1 && !is_scaling) {
            fetch_bom_items(frm);
            // Remove highlighting when resetting
            frm.fields_dict.items.grid.grid_rows.forEach(grid_row => {
                $(grid_row.wrapper).removeClass('master-row-highlight');
            });
            frappe.show_alert({message: __("Resetting to original BOM quantities"), indicator: 'info'});
        }
    }
});

// Logic for the Child Table
frappe.ui.form.on('Bom Items for Size', { 
    quntity: function(frm, cdt, cdn) {
        // 1. Exit if the script itself is changing values
        if (is_scaling) return;

        let row = locals[cdt][cdn];

        // 2. Only run if user enters a number and base qty exists
        if (row.quntity && row.quntity !== 0 && row.qty && row.qty !== 0) {
            
            // 3. Validation: Block if another quntity field is already filled
            let other_input = (frm.doc.items || []).find(d => d.name !== cdn && d.quntity && d.quntity !== 0);
            if (other_input) {
                is_scaling = true;
                frappe.model.set_value(cdt, cdn, 'quntity', 0);
                frappe.msgprint({
                    title: __('Input Blocked'),
                    indicator: 'red',
                    message: __('Please clear the value in <b>' + other_input.item_code + '</b> before using a different item.')
                });
                is_scaling = false;
                return;
            }

            // 4. Highlight the "Master Row"
            frm.fields_dict.items.grid.grid_rows.forEach(grid_row => {
                $(grid_row.wrapper).removeClass('master-row-highlight');
            });
            let current_grid_row = frm.fields_dict.items.grid.get_row(cdn);
            $(current_grid_row.wrapper).addClass('master-row-highlight');

            // 5. Perform Calculation
            is_scaling = true;
            try {
                let factor = row.quntity / row.qty;
                
                // Update parent size factor
                frm.set_value('size1', factor);

                // Update all items
                frm.doc.items.forEach(d => {
                    let calculated_qty = d.qty * factor;
                    
                    // Set the new calculated value into the base 'qty' field
                    frappe.model.set_value(d.doctype, d.name, 'qty', calculated_qty);
                    
                    // Clear the helper input so it's ready for the next change
                    frappe.model.set_value(d.doctype, d.name, 'quntity', 0);
                });

                frm.refresh_field('items');
                
                frappe.show_alert({
                    message: __("Applied scaling factor: {0}", [factor.toFixed(4)]),
                    indicator: 'green'
                });

            } finally {
                // Delay resetting the flag to ensure UI updates are complete
                setTimeout(() => { is_scaling = false; }, 300);
            }
        }
    }
});

// Reusable function to fetch BOM items from server
function fetch_bom_items(frm) {
    const recipe_value = frm.doc.recipe_name1;
    if (!recipe_value) {
        frm.clear_table("items");
        frm.refresh_field("items");
        return;
    }

    frappe.call({
        method: "caf.caf.doctype.production_calculate.production_calculate.calculate_items_from_size_js",
        args: { 
            docname: frm.doc.name,
            recipe_name1: recipe_value
        },
        callback: function(r) {
            is_scaling = true; // Block triggers during load
            frm.clear_table("items");
            
            if (r.message && r.message.length) {
                r.message.forEach(item => {
                    const row = frm.add_child("items");
                    row.item_code = item.item_code;
                    row.qty = item.qty;
                    row.uom = item.uom;
                    row.quntity = 0; // Ensure calculator is empty
                });
                
                frm.set_value('size1', 1);
            }
            
            frm.refresh_field("items");
            
            setTimeout(() => { 
                is_scaling = false; 
                frm.dirty(); // Refresh form state
            }, 200);
        }
    });
}

/**
 * Recipe-Based Item Sizing Calculator
 * 
 * Manages the child table `custom_get_items_by_size` on the Production Calculate form.
 * When a recipe is selected, BOM items are fetched from the server and loaded into the table.
 * When the size multiplier changes, each item's qty is scaled accordingly.
 */

// Stores original BOM quantities per item_code.
// Used as the source of truth to prevent compounding errors on repeated size changes.
let base_quantities = {};

frappe.ui.form.on("Production Calculate", {

    // Fires when the user selects or clears the recipe field.
    custom_recipe: function(frm) {

        // If recipe is cleared, empty the table and reset stored quantities.
        if (!frm.doc.custom_recipe) {
            frm.clear_table("custom_get_items_by_size");
            frm.refresh_field("custom_get_items_by_size");
            base_quantities = {};
            return;
        }

        // Fetch BOM items from the server ordered by idx (same order as BOM).
        frappe.call({
            method: "caf.caf.doctype.production_calculate.production_calculate.get_recipe_items",
            args: { custom_recipe: frm.doc.custom_recipe },
            callback: function(r) {

                // Reset before loading new recipe data.
                base_quantities = {};
                frm.clear_table("custom_get_items_by_size");

                if (r.message && r.message.length) {
                    r.message.forEach(item => {

                        // Store original BOM qty before any size scaling.
                        base_quantities[item.item_code] = item.qty;

                        // Populate the child table row.
                        let row = frm.add_child("custom_get_items_by_size");
                        row.item_code = item.item_code;
                        row.qty = item.qty;
                        row.uom = item.uom;
                    });
                }

                // Always reset size to 1 when a new recipe is loaded.
                frm.set_value("custom_recipe_size", 1);
                frm.refresh_field("custom_get_items_by_size");
            }
        });
    },

    // Fires when the user changes the size multiplier.
    custom_recipe_size: function(frm) {
        const size = frm.doc.custom_recipe_size;

        // Guard: size must be a positive number.
        if (!size || size <= 0) {
            frappe.show_alert({ message: __("Size must be greater than 0"), indicator: 'red' });
            frm.set_value("custom_recipe_size", 1);
            return;
        }

        // No items loaded yet, nothing to scale.
        if (!Object.keys(base_quantities).length) return;

        // Scale each row: qty = original BOM qty × size.
        // Always multiplied from base_quantities, not the current table value,
        // to avoid compounding errors on repeated size changes.
        frm.doc.custom_get_items_by_size.forEach(row => {
            frappe.model.set_value(row.doctype, row.name, "qty", base_quantities[row.item_code] * size);
        });

        frm.refresh_field("custom_get_items_by_size");
    }

});