// Copyright (c) 2026, CAF and contributors

frappe.ui.form.on("Ingress Sync Settings", {
    refresh(frm) {
        // Reachability is an operational fact, not a code fact: the machine is a
        // PC in the office and the network is not ours. Give whoever configures
        // this a way to find out NOW rather than from a failed run at 04:00.
        frm.add_custom_button(__("Test connection"), () => {
            frappe.call({
                method: "caf.caf.doctype.ingress_sync_settings.ingress_sync_settings.test_connection",
                freeze: true,
                freeze_message: __("Reaching the Ingress machine…"),
                callback(r) {
                    if (!r.message) return;
                    frappe.msgprint({
                        title: r.message.ok ? __("Reachable") : __("Not reachable"),
                        indicator: r.message.ok ? "green" : "red",
                        message: frappe.utils.escape_html(r.message.detail),
                    });
                },
            });
        });

        frm.set_intro(
            frm.doc.enabled
                ? __("Scheduled sync is ON. The fetch pass writes drafts only; the submit pass decides.")
                : __("Scheduled sync is OFF — manual imports and test batches still work. Nothing runs on a timer until this is ticked."),
            frm.doc.enabled ? "blue" : "orange");
    },
});
