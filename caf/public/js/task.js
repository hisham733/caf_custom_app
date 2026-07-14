frappe.ui.form.on("Task", {
    refresh: function (frm) {
        if (frm.doc.docstatus === 0 && frm.doc.custom_macequiitem) {
            frm.add_custom_button(__('Part Log'), function () {
                fetch_maintenance_items(frm);
            }).addClass("btn-primary-dark");
        }
    },
});

function fetch_maintenance_items(frm) {
    let workstation = frm.doc.custom_macequiitem;

    frappe.call({
        method: "caf.caf.overrides.task.get_maintenance_items",
        args: {
            workstation: workstation,
        },
        callback: function (r) {
            if (r.message && r.message.length > 0) {
                show_item_selection_dialog(frm, r.message, workstation);
            } else {
                frappe.msgprint(__("No items found for workstation: {0}", [workstation]));
            }
        },
    });
}

function show_item_selection_dialog(frm, items, workstation) {
    let selected_items = [];

    let dialog = new frappe.ui.Dialog({
        title: __("Select Maintenance Items"),
        size: "extra-large",
        fields: [
            {
                fieldname: "items_section",
                fieldtype: "HTML",
            },
        ],
        primary_action_label: __("Create Stock Entry"),
        primary_action: function () {
            if (selected_items.length === 0) {
                frappe.msgprint(__("Please select at least one item"));
                return;
            }

            let has_error = false;
            selected_items.forEach(function (item) {
                let qty_input = dialog.$wrapper.find(`.item-qty[data-item="${item.name}"]`);
                let qty = parseInt(qty_input.val(), 10);
                if (!qty || qty <= 0 || !Number.isInteger(qty)) {
                    frappe.msgprint(__("Quantity must be a whole number for {0}", [item.name]));
                    qty_input.css("border-color", "red");
                    has_error = true;
                } else {
                    qty_input.css("border-color", "#d1d8dd");
                }
            });

            if (!has_error) {
                create_stock_entry(frm, dialog, selected_items);
            }
        },
    });

    dialog.show();

    let $wrapper = dialog.fields_dict.items_section.$wrapper;
    $wrapper.empty();

    let $container = $(`
        <div class="maintenance-items-container" style="display: flex; flex-wrap: wrap; gap: 15px; padding: 10px 0;">
        </div>
    `);
    $wrapper.append($container);

    items.forEach(function (item) {
        let image_html = item.image
            ? `<img src="${item.image}" style="width: 80px; height: 80px; object-fit: cover; border-radius: 8px; border: 1px solid #d1d8dd;" />`
            : `<div style="width: 80px; height: 80px; border-radius: 8px; border: 1px solid #d1d8dd; display: flex; align-items: center; justify-content: center; color: #8d99a6; font-size: 24px;">${item.item_name ? item.item_name.charAt(0).toUpperCase() : "I"}</div>`;

        let $card = $(`
            <div class="item-card" data-item="${item.name}" style="
                border: 1px solid #d1d8dd;
                border-radius: 8px;
                padding: 15px;
                width: calc(33.333% - 10px);
                min-width: 280px;
                background: #fff;
                transition: border-color 0.2s, box-shadow 0.2s;
                cursor: pointer;
            ">
                <div style="display: flex; align-items: flex-start; gap: 12px;">
                    <input type="checkbox" class="item-checkbox" data-item="${item.name}" style="margin-top: 4px; width: 18px; height: 18px; cursor: pointer;" />
                    <div style="flex: 1;">
                        <div style="display: flex; gap: 12px; align-items: flex-start;">
                            ${image_html}
                            <div style="flex: 1;">
                                <div style="font-weight: 600; font-size: 14px; color: #1e293b; margin-bottom: 4px;">${item.name}</div>
                                <div style="color: #64748b; font-size: 12px; margin-bottom: 8px;">${item.item_name || ""}</div>
                            </div>
                        </div>
                        <div style="margin-top: 10px; display: flex; gap: 10px; flex-wrap: wrap;">
                            <div style="flex: 1; min-width: 100px;">
                                <label style="font-size: 11px; color: #64748b; font-weight: 500; margin-bottom: 3px; display: block;">Qty *</label>
                                <input type="number" class="item-qty form-control" data-item="${item.name}" min="1" step="1" style="width: 100%; padding: 6px 8px; border: 1px solid #d1d8dd; border-radius: 4px; font-size: 13px;" />
                            </div>
                            <div style="flex: 2; min-width: 150px;">
                                <label style="font-size: 11px; color: #64748b; font-weight: 500; margin-bottom: 3px; display: block;">Description</label>
                                <input type="text" class="item-desc form-control" data-item="${item.name}" style="width: 100%; padding: 6px 8px; border: 1px solid #d1d8dd; border-radius: 4px; font-size: 13px;" />
                            </div>
                            <div style="flex: 1; min-width: 120px;">
                                <label style="font-size: 11px; color: #64748b; font-weight: 500; margin-bottom: 3px; display: block;">Disposal Location</label>
                                <select class="item-location form-control" data-item="${item.name}" style="width: 100%; padding: 6px 8px; border: 1px solid #d1d8dd; border-radius: 4px; font-size: 13px;">
                                    <option value="">Select...</option>
                                    <option value="Maintenance bin">Maintenance bin</option>
                                    <option value="Main trash room">Main trash room</option>
                                    <option value="Roof storage">Roof storage</option>
                                    <option value="Maintenance room">Maintenance room</option>
                                </select>
                            </div>
                            <div style="flex: 1; min-width: 100px;">
                                <label style="font-size: 11px; color: #64748b; font-weight: 500; margin-bottom: 3px; display: block;">Image</label>
                                <input type="file" class="item-image" data-item="${item.name}" accept="image/*" style="width: 100%; font-size: 12px;" />
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `);

        $container.append($card);

        $card.on("click", function (e) {
            if ($(e.target).is("input, select")) return;
            let checkbox = $card.find(".item-checkbox");
            checkbox.prop("checked", !checkbox.prop("checked")).trigger("change");
        });

        $card.find(".item-checkbox").on("change", function () {
            let is_checked = $(this).prop("checked");
            let item_name = $(this).data("item");

            if (is_checked) {
                $card.css({ border: "2px solid #2490ef", "box-shadow": "0 2px 8px rgba(36,144,239,0.15)" });
                if (!selected_items.find((i) => i.name === item_name)) {
                    selected_items.push(items.find((i) => i.name === item_name));
                }
            } else {
                $card.css({ border: "1px solid #d1d8dd", "box-shadow": "none" });
                selected_items = selected_items.filter((i) => i.name !== item_name);
            }
        });

        $card.find(".item-qty").on("change", function () {
            let val = parseInt($(this).val(), 10);
            if (val && val > 0) {
                let checkbox = $card.find(".item-checkbox");
                if (!checkbox.prop("checked")) {
                    checkbox.prop("checked", true).trigger("change");
                }
            }
        });
    });
}

function create_stock_entry(frm, dialog, selected_items) {
    let items_data = [];
    let file_inputs = [];
    selected_items.forEach(function (item) {
        let qty = parseInt(dialog.$wrapper.find(`.item-qty[data-item="${item.name}"]`).val(), 10) || 0;
        let description = dialog.$wrapper.find(`.item-desc[data-item="${item.name}"]`).val() || "";
        let location = dialog.$wrapper.find(`.item-location[data-item="${item.name}"]`).val() || "";
        let warehouse = item.default_warehouse || "";
        items_data.push({
            item_code: item.name,
            qty: qty,
            description: description,
            location: location,
            warehouse: warehouse,
            file_url: "",
        });
        let file_input = dialog.$wrapper.find(`.item-image[data-item="${item.name}"]`)[0];
        if (file_input && file_input.files && file_input.files.length > 0) {
            file_inputs.push({
                item_code: item.name,
                file_obj: file_input.files[0],
            });
        }
    });

    let missing_warehouse = items_data.filter(function (item) {
        return !item.warehouse;
    });

    if (missing_warehouse.length > 0) {
        let names = missing_warehouse.map(function (i) { return i.item_code; }).join(", ");
        frappe.msgprint(__("No default warehouse found for: {0}. Please set a default warehouse in Item > Item Defaults.", [names]));
        return;
    }

    frappe.dom.freeze(__("Creating Stock Entry..."));

    if (file_inputs.length > 0) {
        upload_files_first(file_inputs, 0, {}, function (file_urls) {
            items_data.forEach(function (item) {
                if (file_urls[item.item_code]) {
                    item.file_url = file_urls[item.item_code];
                }
            });
            submit_stock_entry(frm, dialog, items_data);
        });
    } else {
        submit_stock_entry(frm, dialog, items_data);
    }
}

function upload_files_first(file_inputs, index, file_urls, callback) {
    if (index >= file_inputs.length) {
        callback(file_urls);
        return;
    }

    let file_info = file_inputs[index];
    let form_data = new FormData();
    form_data.append("file", file_info.file_obj);
    form_data.append("is_private", 0);

    $.ajax({
        url: "/api/method/upload_file",
        type: "POST",
        data: form_data,
        processData: false,
        contentType: false,
        headers: {
            "X-Frappe-CSRF-Token": frappe.csrf_token,
        },
        success: function (r) {
            if (r && r.message && r.message.file_url) {
                file_urls[file_info.item_code] = r.message.file_url;
            }
            upload_files_first(file_inputs, index + 1, file_urls, callback);
        },
        error: function () {
            upload_files_first(file_inputs, index + 1, file_urls, callback);
        },
    });
}

function submit_stock_entry(frm, dialog, items_data) {
    frappe.call({
        method: "caf.caf.overrides.task.create_material_issue_stock_entry",
        args: {
            task_name: frm.doc.name,
            items: items_data.map(function (item) {
                return {
                    item_code: item.item_code,
                    qty: item.qty,
                    warehouse: item.warehouse,
                    description: item.description,
                    location: item.location,
                    file_url: item.file_url,
                };
            }),
        },
        callback: function (r) {
            frappe.dom.unfreeze();
            if (r.message) {
                dialog.hide();
                frappe.msgprint({
                    title: __("Success"),
                    indicator: "green",
                    message: __("Stock Entry {0} created successfully (Draft)", [
                        `<a href="/app/stock-entry/${r.message.name}" target="_blank">${r.message.name}</a>`,
                    ]),
                });
            } else {
                frappe.msgprint({ title: __("Error"), indicator: "red", message: __("Failed to create Stock Entry") });
            }
        },
        error: function (err) {
            frappe.dom.unfreeze();
            frappe.msgprint({ title: __("Error"), indicator: "red", message: err.message || __("Failed to create Stock Entry") });
        },
    });
}
