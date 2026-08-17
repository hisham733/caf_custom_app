// Copyright (c) 2026, CAF and contributors

frappe.ui.form.on("Ingress Import Batch", {
    refresh(frm) {
        if (frm.doc.__islocal) return;

        if (frm.doc.status === "Reverted") {
            frm.dashboard.set_headline(
                __("This batch has been reverted — its Finger Logs and their Attendance were removed."));
            return;
        }

        frm.add_custom_button(__("Revert this batch"), () => {
            const is_prod = frm.doc.purpose === "Production";
            frappe.confirm(
                is_prod
                    ? __("<b>{0} is a Production batch.</b><br><br>Reverting cancels and <b>deletes</b> {1} Finger Logs and every Attendance row they created. This is not the undo button for a bad correction — it erases the records. Continue?",
                         [frm.doc.name, frm.doc.created])
                    : __("Cancel and delete the {0} Finger Logs this batch created, and their Attendance?",
                         [frm.doc.created]),
                () => {
                    frappe.call({
                        method: "caf.caf.doctype.ingress_import_batch.ingress_import_batch.revert",
                        args: { batch_name: frm.doc.name, force: is_prod ? 1 : 0 },
                        freeze: true,
                        freeze_message: __("Reverting…"),
                        callback(r) {
                            if (!r.message) return;
                            const m = r.message;
                            let msg = __("Removed {0} Finger Logs and {1} Attendance rows.",
                                         [m.removed, m.attendance_removed]);
                            if (m.refused && m.refused.length) {
                                // Named, never counted away: these are rows somebody
                                // is working against, and the person reverting needs
                                // to know which.
                                msg += "<br><br><b>" + __("Left alone — modified since import:")
                                     + "</b><br>" + m.refused.join("<br>");
                            }
                            frappe.msgprint({ title: __("Reverted"), message: msg,
                                              indicator: m.refused.length ? "orange" : "green" });
                            frm.reload_doc();
                        },
                    });
                });
        }, __("Actions"));
    },
});
