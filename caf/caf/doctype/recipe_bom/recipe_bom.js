frappe.ui.form.on('Recipe BOM', {
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

frappe.ui.form.on("Recipe BOM", {
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


frappe.ui.form.on("Recipe BOM", {
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


frappe.ui.form.on("Recipe BOM", {
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

frappe.ui.form.on("Recipe BOM", {
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



frappe.ui.form.on("Recipe BOM", {
    refresh(frm) {
        frm.set_query("output_item", function() {
            return {
                query: "caf.caf.doctype.recipe_bom.recipe_bom.get_single_bom_items"
            };
        });
    }
});

