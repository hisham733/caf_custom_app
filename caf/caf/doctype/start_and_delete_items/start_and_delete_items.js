// Copyright (c) 2025, hisham and contributors
// For license information, please see license.txt

// frappe.ui.form.on("start and delete items", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on("start and delete items", {
    refresh: function(frm) {
        // Only show "New Version" button if doc is submitted
        if(frm.doc.docstatus === 1) {
            frm.add_custom_button("New Version", function() {
                frappe.call({
                    method: "caf.caf.doctype.start_and_delete_items.start_and_delete_items.create_new_version",
                    args: { docname: frm.doc.name },
                    callback: function(r) {
                        if(r.message) {
                            frappe.msgprint("New version created successfully!");
                            frappe.set_route("Form", "Start and Delete Items", r.message);
                        }
                    }
                });
            });
        }
    }
});

