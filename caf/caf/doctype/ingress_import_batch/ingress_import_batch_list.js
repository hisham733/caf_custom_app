// Copyright (c) 2026, CAF and contributors
// The list view is where an import STARTS — there is no "new batch" form to
// fill in, because a batch is a record of a run, not a request for one.

frappe.listview_settings["Ingress Import Batch"] = {
    add_fields: ["status", "purpose", "created", "held", "failed"],

    get_indicator(doc) {
        const map = {
            Running: "orange",
            Completed: doc.failed ? "yellow" : "green",
            Failed: "red",
            Reverted: "grey",
        };
        return [__(doc.status), map[doc.status] || "grey", "status,=," + doc.status];
    },

    onload(listview) {
        listview.page.add_inner_button(__("Import from Ingress"), () => {
            const d = new frappe.ui.Dialog({
                title: __("Import from Ingress"),
                fields: [
                    {
                        fieldname: "from_date", fieldtype: "Date", reqd: 1,
                        label: __("From work date"),
                        default: frappe.datetime.add_days(frappe.datetime.get_today(), -3),
                    },
                    {
                        fieldname: "to_date", fieldtype: "Date", reqd: 1,
                        label: __("To work date"),
                        default: frappe.datetime.add_days(frappe.datetime.get_today(), -1),
                    },
                    { fieldtype: "Column Break" },
                    {
                        fieldname: "purpose", fieldtype: "Select", reqd: 1,
                        label: __("Purpose"), options: "Test\nProduction", default: "Test",
                        description: __("A Test batch can be reverted in one click. A Production batch needs a force."),
                    },
                    {
                        fieldname: "submit_logs", fieldtype: "Check",
                        label: __("Submit the logs"),
                        description: __("Leave off to import as drafts only. A log refused at submit stays a draft either way — that draft is the HR worklist, not an error."),
                    },
                    { fieldtype: "Section Break", label: __("Employees") },
                    {
                        fieldname: "employees", fieldtype: "MultiSelectList",
                        label: __("Limit to"),
                        description: __("Leave empty for every active employee with an Attendance Device ID."),
                        get_data(txt) {
                            return frappe.db.get_link_options("Employee", txt, { status: "Active" });
                        },
                    },
                ],
                primary_action_label: __("Import"),
                primary_action(values) {
                    d.hide();
                    frappe.dom.freeze(__("Reading the Ingress machine…"));
                    frappe.call({
                        method: "caf.caf.doctype.ingress_import_batch.ingress_import_batch.run_manual_import",
                        args: {
                            from_date: values.from_date,
                            to_date: values.to_date,
                            employees: values.employees && values.employees.length
                                ? values.employees : null,
                            submit: values.submit_logs ? 1 : 0,
                            purpose: values.purpose,
                        },
                        callback(r) {
                            frappe.dom.unfreeze();
                            if (!r.message) return;
                            const c = r.message.counts;
                            frappe.msgprint({
                                title: __("Batch {0}", [r.message.batch]),
                                indicator: c.failed ? "orange" : "green",
                                message: __("Read {0} · created {1} · updated {2} · submitted {3} · held {4} · already present {5} · human-owned {6} · drift {7} · failed {8}",
                                    [c.read_rows, c.created, c.updated, c.submitted, c.held,
                                     c.already_present, c.skipped_locked, c.drift, c.failed]),
                            });
                            listview.refresh();
                        },
                        error() {
                            frappe.dom.unfreeze();
                        },
                    });
                },
            });
            d.show();
        });
    },
};
