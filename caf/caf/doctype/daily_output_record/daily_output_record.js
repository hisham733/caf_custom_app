// Copyright (c) 2026, hisham and contributors
// For license information, please see license.txt

frappe.ui.form.on("Daily Output Record", {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.items && frm.doc.items.length > 0) {
            // Set indicator colors for status in child table grid
            var items_grid = frm.fields_dict.items;
            if (items_grid && items_grid.grid) {
                items_grid.grid.get_field("status").get_indicator = function(value) {
                    if (value === "Done") return [__("Done"), "blue"];
                    if (value === "Failed") return [__("Failed"), "red"];
                    if (value === "Pending") return [__("Pending"), "orange"];
                    return [value, "orange"];
                };
            }

            var in_progress = frm.doc.processing_status === "In Progress";

            var btn = frm.add_custom_button(
                in_progress ? __("Processing...") : __("Process All"),
                function() {
                    if (in_progress) return;
                    frm.call({
                        method: "enqueue_process_all",
                        doc: frm.doc,
                        callback: function(r) {
                            if (r.message && r.message.queued) {
                                frappe.show_alert({
                                    message: __("Processing started in background"),
                                    indicator: "blue"
                                }, 5);
                                frm.reload_doc();
                                start_status_polling(frm);
                            }
                        }
                    });
                }
            ).addClass("btn-primary");

            if (in_progress) {
                btn.prop("disabled", true).removeClass("btn-primary").addClass("btn-default");
                start_status_polling(frm);
            }
        }
    },

    date_of_output: function(frm) {
        var date = frm.doc.date_of_output;
        if (!date) return;

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Work Order",
                filters: [
                    ["planned_start_date", "Between", [date, date]],
                    ["docstatus", "!=", 2],
                    ["custom_item_type", "=", "Cook"]
                ],
                fields: ["name", "custom_link_id", "custom_round", "qty", "custom_batch_size"],
                limit_page_length: 200
            },
            callback: function(r) {
                var cook_wos = r.message || [];
                if (cook_wos.length === 0) {
                    frm.clear_table("items");
                    frm.refresh_field("items");
                    frappe.msgprint(__("No Cook WOs found for " + date));
                    return;
                }

                var link_ids = cook_wos.map(function(wo) { return wo.custom_link_id; });
                var wo_names = cook_wos.map(function(wo) { return wo.name; });
                var workstations = {};
                var pack_data = {};
                var pack_workstations = {};
                var pack_names = [];
                var loaded = 0;
                var total = wo_names.length;

                function check_done() {
                    loaded++;
                    if (loaded >= total) build_table();
                }

                wo_names.forEach(function(wname) {
                    frappe.call({
                        method: "frappe.client.get",
                        args: {
                            doctype: "Work Order",
                            name: wname
                        },
                        callback: function(r2) {
                            var wo = r2.message || {};
                            if (wo.operations && wo.operations.length > 0) {
                                workstations[wname] = wo.operations[0].workstation || "";
                            }
                            check_done();
                        }
                    });
                });

                frappe.call({
                    method: "frappe.client.get_list",
                    args: {
                        doctype: "Work Order",
                        filters: [
                            ["custom_link_id", "in", link_ids],
                            ["docstatus", "!=", 2],
                            ["custom_item_type", "=", "Pack"]
                        ],
                        fields: ["custom_link_id", "production_item", "name", "docstatus"],
                        limit_page_length: 200
                    },
                    callback: function(r3) {
                        (r3.message || []).forEach(function(pwo) {
                            if (!pack_data[pwo.custom_link_id]) {
                                pack_data[pwo.custom_link_id] = [];
                                pack_names.push(pwo.name);
                            }
                            pack_data[pwo.custom_link_id].push({
                                name: pwo.name,
                                production_item: pwo.production_item,
                                docstatus: pwo.docstatus
                            });
                        });
                        if (pack_names.length === 0) {
                            total++;
                            check_done();
                            return;
                        }
                        total += pack_names.length;
                        pack_names.forEach(function(pname) {
                            frappe.call({
                                method: "frappe.client.get",
                                args: {
                                    doctype: "Work Order",
                                    name: pname
                                },
                                callback: function(r4) {
                                    var pwo = r4.message || {};
                                    if (pwo.operations && pwo.operations.length > 0) {
                                        pack_workstations[pname] = pwo.operations[0].workstation || "";
                                    }
                                    check_done();
                                }
                            });
                        });
                    }
                });

                function build_table() {
                    frm.clear_table("items");

                    // Filter out workstation containing fryer
                    cook_wos = cook_wos.filter(function(wo) {
                        var ws = workstations[wo.name] || "";
                        return ws.toLowerCase().indexOf("fryer") === -1;
                    });

                    function wsType(ws) {
                        var name = (ws || "").toLowerCase();
                        if (name.indexOf("cooker") !== -1) return 0;
                        if (name.indexOf("kettle") !== -1) return 1;
                        if (name.indexOf("fryer") !== -1) return 2;
                        return 9;
                    }
                    function wsNum(ws) {
                        return parseInt((ws || "").replace(/\D/g, "")) || 0;
                    }
                    if (cook_wos.length === 0) {
                        frm.refresh_field("items");
                        frappe.msgprint(__("Only fryer workstations found, nothing to load"));
                        return;
                    }

                    cook_wos.sort(function(a, b) {
                        var wa = workstations[a.name] || "";
                        var wb = workstations[b.name] || "";
                        var ta = wsType(wa), tb = wsType(wb);
                        if (ta !== tb) return ta - tb;
                        var ra = parseInt(a.custom_round) || 0;
                        var rb = parseInt(b.custom_round) || 0;
                        if (ra !== rb) return ra - rb;
                        return wsNum(wa) - wsNum(wb);
                    });

                    cook_wos.forEach(function(wo) {
                        var row = frm.add_child("items");
                        row.link_id = wo.custom_link_id;
                        row.work_order = wo.name;
                        row.workstation = workstations[wo.name] || "";
                        row.round = wo.custom_round;
                        row.size = wo.custom_batch_size || wo.qty;

                        var packs = pack_data[wo.custom_link_id] || [];
                        row.number_of_pack = packs.length;
                        packs.forEach(function(pack, idx) {
                            var suffix = idx === 0 ? "" : "_" + (idx + 1);
                            frappe.model.set_value(row.doctype, row.name, "pack_name" + suffix, pack.production_item);
                            frappe.model.set_value(row.doctype, row.name, "pack_workstation" + suffix, pack_workstations[pack.name] || "");
                        });
                        var all_submitted = packs.every(function(p) { return p.docstatus === 1; });
                        if (all_submitted) row.status = "Done";
                    });

                    frm.refresh_field("items");
                    frappe.show_alert({
                        message: __("Loaded " + cook_wos.length + " rows"),
                        indicator: "green"
                    }, 3);
                }
            }
        });
    }
});

frappe.ui.form.on("Daily Output Item", {
    number_of_pack: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        var count = parseInt(row.number_of_pack || 0);
        for (var i = 2; i <= 7; i++) {
            if (i > count) {
                frappe.model.set_value(cdt, cdn, "pack_name_" + i, null);
                frappe.model.set_value(cdt, cdn, "actual_qty_" + i, 0);
                frappe.model.set_value(cdt, cdn, "pack_workstation_" + i, null);
            }
        }
    }
});

function start_status_polling(frm) {
    var poll = setInterval(function() {
        frappe.db.get_value("Daily Output Record", frm.doc.name,
            ["processing_status", "processing_error"])
            .then(function(r) {
                if (!r || !r.message) return;
                var status = r.message.processing_status;
                if (status === "Completed") {
                    clearInterval(poll);
                    frappe.msgprint(__("All rows processed successfully"));
                    frm.reload_doc();
                } else if (status === "Failed") {
                    clearInterval(poll);
                    frappe.msgprint(__("Processing failed: {0}")
                        .format(r.message.processing_error || "Unknown error"));
                    frm.reload_doc();
                }
            });
    }, 3000);
}
