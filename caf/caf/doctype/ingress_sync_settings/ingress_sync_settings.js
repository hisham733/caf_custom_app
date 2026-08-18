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

        // Say what is TRUE, not what is planned. The switch and the whole window
        // section are inert until Phase 2 exists, and a settings page that
        // implies otherwise is one HR will stop believing.
        // Every field on this page is now read by code — the six that were not
        // were removed 2026-08-18 once FBR44 cancelled the scheduled passes they
        // belonged to. Say what the page IS, not what it might one day be.
        frm.set_intro(
            __("Importing is a <b>human act</b> — there is no scheduled fetch (FBR44). Use <b>Import from Ingress</b> on the Ingress Import Batch list, or <b>Re-import from Ingress</b> on a Finger Log.<br><br>⚠️ Generate the day in Ingress <b>first</b> — its attendance table is not built until somebody does, so importing before that gives ERPNext half a day."),
            "blue");
    },
});
