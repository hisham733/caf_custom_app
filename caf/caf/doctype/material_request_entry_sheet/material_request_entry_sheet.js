frappe.ui.form.on("Material Request Entry Sheet", {
    refresh(frm) {
        if (frm.doc.docstatus === 1) {  // ✅ Only show button when document is submitted
            frm.add_custom_button("Create Material Requests", () => {
                frappe.call({
                    doc: frm.doc,
                    method: "create_material_requests_from_entry_lines",
                    callback(r) {
                        if (r.message && r.message.length > 0) {
                            frappe.msgprint({
                                title: "✅ Material Requests Created",
                                message: `<ul>${r.message.map(mr => `<li><a href="/app/material-request/${mr}" target="_blank">${mr}</a></li>`).join("")}</ul>`,
                                indicator: "green",
                                wide: true
                            });
                        } else {
                            frappe.msgprint("No Material Requests were created.");
                        }
                        frm.reload_doc();
                    }
                });
            });
        }
    }
});


frappe.ui.form.on('Material Request Entry Sheet', {
    required_by(frm) {
        let new_date = frm.doc.required_by;

        if (!new_date) return;

        let updated_rows = 0;

        // Loop through all rows and update
        frm.doc.material_request_entry_line.forEach(row => {
            if (row.required_by !== new_date) {
                row.required_by = new_date;
                updated_rows++;
            }
        });

        frm.refresh_field('material_request_entry_line');

        if (updated_rows > 0) {
            frappe.msgprint(`${updated_rows} rows updated with new Required By date.`);
        }
    }
});

frappe.ui.form.on('Material Request Entry Sheet', {
    required_by(frm) {
        if (!frm.doc.required_by) return;

        const date = frappe.datetime.str_to_obj(frm.doc.required_by);
        const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
        const day_name = days[date.getDay()];

        frm.set_value('day', day_name);
    }
});

