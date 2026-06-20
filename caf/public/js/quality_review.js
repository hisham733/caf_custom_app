frappe.ui.form.on("Quality Review", {
    // This function is now correct
    custom_pre_operation_cleaning: function (frm) {
        let now = frappe.datetime.now_time();
        let user = frappe.user_info(frappe.session.user).fullname;
        
        frappe.call({
            doc: frm.doc,
            method: "update_pre_post_operation_cleaning",
            args: {
                updates: {
                    "PRE-TIME": now,
                    "PRE-CLEAN BY": user
                }
            },
            callback: function(response) {
                if (response.message) {
                    frappe.msgprint(response.message);
                    frm.reload_doc();
                }
            }
        });
    },

    // FIXED: Removed the redundant 'docname' argument
    custom_postoperation_cleaning: function (frm) {
        let now = frappe.datetime.now_time();
        let user = frappe.user_info(frappe.session.user).fullname;

        frappe.call({
            doc: frm.doc,
            method: "update_pre_post_operation_cleaning",
            args: {
                // 'docname' has been removed. 'doc: frm.doc' handles it.
                updates: {
                    "POST-TIME": now,
                    "POST-CLEAN BY": user
                }
            },
            callback: function(response) {
                if (response.message) {
                    frappe.msgprint(response.message);
                    frm.reload_doc();
                }
            }
        });
    },

    // FIXED: Removed the redundant 'docname' argument
    custom_preverified: function (frm) {
        let user = frappe.user_info(frappe.session.user).fullname;

        frappe.call({
            doc: frm.doc,
            method: "custom_verification",
            args: {
                // 'docname' has been removed.
                updates: {
                    "PRE-VERIFIED BY": user
                }
            },
            callback: function(response) {
                if (response.message) {
                    frappe.msgprint(response.message);
                    frm.reload_doc();
                }
            }
        });
    },

    // FIXED: Removed the redundant 'docname' argument
    custom_postverified: function (frm) {
        let user = frappe.user_info(frappe.session.user).fullname;

        frappe.call({
            doc: frm.doc,
            method: "custom_verification",
            args: {
                // 'docname' has been removed.
                updates: {
                    "POST-VERIFIED BY": user
                }
            },
            callback: function(response) {
                if (response.message) {
                    frappe.msgprint(response.message);
                    frm.reload_doc();
                }
            }
        });
    },
});



frappe.ui.form.on("Quality Review", {
    goal: function(frm) {
        if (frm.doc.goal === "OPRP Temperature Record") {
            frappe.call({
                method: "frappe.client.get_list",
                args: {
                    doctype: "Quality Goal",
                    filters: { goal: frm.doc.goal },
                    fields: ["name"],
                    limit: 1,
                    order_by: "creation desc"
                },
                callback: function(response) {
                    if (response.message && response.message.length > 0) {
                        const goal_name = response.message[0].name;

                        // Now fetch the child table data from Quality Goal
                        frappe.call({
                            method: "frappe.client.get",
                            args: {
                                doctype: "Quality Goal",
                                name: goal_name
                            },
                            callback: function(r) {
                                if (r.message) {
                                    let rows = r.message.custom_chiller_table || [];

                                    // Clear current table (if any)
                                    frm.clear_table("custom_chiller_table");

                                    // Add rows to Quality Review
                                    rows.forEach(row => {
                                        let child = frm.add_child("custom_chiller_table");
                                        frappe.model.set_value(child.doctype, child.name, "machine_name", row.machine_name);
                                        // frappe.model.set_value(child.doctype, child.name, "temperature", row.temperature);
                                        // Add other fields as needed
                                    });

                                    frm.refresh_field("custom_chiller_table");
                                }
                            }
                        });
                    }
                }
            });
        }
    }
});


frappe.ui.form.on("Quality Review", {
    after_save: function(frm) {
	console.log("after_save triggered");
        const current_user = frappe.session.user;

        // Only fetch and set if custom_employee_name is empty
        if (!frm.doc.custom_employee_name) {
            frappe.db.get_value("Employee", { user_id: current_user }, "employee_name")
                .then(r => {
                    if (r.message && r.message.employee_name) {
                        frm.set_value("custom_employee_name", r.message.employee_name);
                        frm.save();  // Save to persist the change
                    } else {
                        frappe.msgprint("No Employee found linked to this user.");
                    }
                });
        }
    }
});

frappe.ui.form.on("Quality Review", {
    custom_approved_by_me: function(frm) {
        if (frm.doc.custom_approved_by_me && !frm.doc.custom_employee_name_approved_by) {
            const current_user = frappe.session.user;

            frappe.db.get_value("Employee", { user_id: current_user }, "employee_name")
                .then(r => {
                    if (r.message && r.message.employee_name) {
                        frm.set_value("custom_employee_name_approved_by", r.message.employee_name);
                    } else {
                        frappe.msgprint("No Employee found linked to this user.");
                    }
                });
        } else if (!frm.doc.custom_approved_by_me) {
            // Optionally clear the name if box is unchecked
            frm.set_value("custom_employee_name_approved_by", null);
        }
    }
});
