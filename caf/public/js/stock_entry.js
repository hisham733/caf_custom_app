frappe.provide("erpnext.stock");

erpnext.stock.StockEntryOverride = class StockEntryOverride {
    constructor(frm) {
        this.frm = frm;
        // Save a reference to the original get_items in the constructor
        if (this.frm && this.frm.cscript && typeof this.frm.cscript.get_items === 'function') {
            this.orig_get_items = this.frm.cscript.get_items;
        } else {
            this.orig_get_items = null;
        }
    }

    fg_completed_qty() {
        // Check Manufacturing Settings for overproduction control
        frappe.db.get_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order")
            .then(overproduction_percentage_for_work_order => {
                if (overproduction_percentage_for_work_order < 1) {
                    // Call the original function if the condition is met

                    if (typeof this.orig_get_items === 'function') {
                        this.orig_get_items.call(this); // Use .call to set the correct 'this' context
                    } else {
                        console.warn("Original get_items function not found.");
                    }

                } else {
                    console.log("Overproduction control enabled. Skipping get_items().");
                }
            })
            .catch(error => {
                console.error("Error fetching overproduction setting:", error);
            });
    }
};

frappe.ui.form.on("Stock Entry", {
    refresh: function(frm) {
        // this if logic is to avoid the user to edit the UOM field in the child table before the qty set is saved.
        //  so the user can only edit the qty field.
        if (frm.is_new() && frm.doc.purpose === "Material Receipt") {
            if (frm.doc.items && frm.doc.items.length > 0) {
                
                // Loop through all rows
                frm.doc.items.forEach(row => {
                    console.log("Setting qty to 0 for row: " + row.name);
                    
                    // Use frappe.model.set_value for child tables
                    frappe.model.set_value(row.doctype, row.name, "qty", 0);
                });

                // CRITICAL: This tells Frappe to re-check "Depends On" rules
                frm.refresh_field("items");
            }
        }
        // Ensure StockEntryOverride is only initialized once
        if (!frm.stockEntryOverride) {
            frm.stockEntryOverride = new erpnext.stock.StockEntryOverride(frm);
        }

        // Extend the cscript with the StockEntryOverride instance
        extend_cscript(cur_frm.cscript, frm.stockEntryOverride);
    },
    fg_completed_qty: function(frm) {
        // Call the fg_completed_qty method of the StockEntryOverride instance
        frm.stockEntryOverride.fg_completed_qty();
    }
});

frappe.ui.form.on('Stock Entry', {
    refresh: function(frm) {
        console.log("User Roles:", frappe.user_roles); // Print user roles to console

        if (frappe.user.has_role("Manufacturing Usersss")) {
            console.log(`items hided in child table.`);
            // Hide fields in the child table
            let child_fields_to_hide = ["qty", "basic_rate", "basic_amount", "amount", "actual_qty"];
            child_fields_to_hide.forEach(function(field) {
                if (frm.fields_dict.items.grid.get_field(field)) {
                    frm.fields_dict.items.grid.toggle_display(field, false);
                } else {
                    console.warn(`Field '${field}' not found in items child table.`);
                }
            });

            // Hide fields in the parent Stock Entry form
            let parent_fields_to_hide = ["total_incoming_value", "total_outgoing_value", "value_difference"];
            parent_fields_to_hide.forEach(function(field) {
                if (frm.fields_dict[field]) {
                    frm.toggle_display(field, false);
                } else {
                    console.warn(`Field '${field}' not found in Stock Entry.`);
                }
            });
        }
    }
});






// frappe.ui.form.on("Stock Entry", {
//     items_on_form_rendered: function(frm) {
//         frm.fields_dict.items.grid.wrapper.on('change', function() {
//             let total_qty = 0;
//             frm.doc.items.forEach(function (item) {
//                 total_qty += flt(item.qty);
//             });
//             frm.set_value("fg_completed_qty", total_qty);
//         });
//     }
// });




// frappe.ui.form.on("Stock Entry", {
//     custom_recalculate: function (frm) {
//         let total_qty = 0;

//         // Loop through all rows in 'items' child table
//         frm.doc.items.forEach(function (item) {
//             total_qty += flt(item.qty); // flt() ensures proper float conversion
//         });

//         // Set the calculated total to 'fg_completed_qty'
//         frm.set_value("fg_completed_qty", total_qty);
//         frm.refresh_field("fg_completed_qty");
//         console.log("from click")
//     }
// });


// frappe-bench/apps/your_app/your_app/doctype/stock_entry/stock_entry.js

frappe.ui.form.on('Stock Entry', {
    fg_completed_qty: function(frm) {
        // Call only for relevant types
        if (["Manufacture", "Repack"].includes(frm.doc.purpose) && frm.doc.docstatus === 0) {
            console.log("get qi start")
            frappe.call({
                doc: frm.doc,

                method: "set_qi_items",
                args: {
                    stock_entry_name: frm.doc.name
                },
                callback: function(r) {
                    if (!r.exc) {
                        frm.reload_doc();
                    }
                }
            });
        }
    }
});


frappe.ui.form.on('Stock Entry', {

    refresh: function(frm) {

        console.log("🔵 Stock Entry Refresh Triggered");
        console.log("Doc Status:", frm.doc.docstatus);
        console.log("Is Local:", frm.doc.__islocal);

        // ✅ Only run for new document
        if (!frm.doc.__islocal) {
            console.log("⛔ Not a new document — stopping.");
            return;
        }

        frappe.call({
            method: "caf.caf.overrides.stock_entry.detect_batch_info",
            args: {
                doc: frm.doc
            },
            freeze: true,  // 🔥 Show loading
            freeze_message: __("Detecting batch info..."),
            callback: function(r) {

                console.log("📩 Backend Response:", r);

                if (!r.message) {
                    console.log("⚠ No message returned from backend");
                    return;
                }

                let data = r.message;

                console.log("✅ Batch Data Received:", data);

                // Set batch
                frm.set_value("custom_batch_to_use", data.batch_no);

                // Update first row
                if (frm.doc.items && frm.doc.items.length > 0) {

                    let items = frm.doc.items;

                    items[0].qty = data.qty;
                    items[0].s_warehouse = data.warehouse;

                    frm.refresh_field("items");

                    console.log("✅ Items table updated");
                }

            },
            error: function(err) {
                console.error("❌ Error calling backend:", err);
            }
        });

    }

});