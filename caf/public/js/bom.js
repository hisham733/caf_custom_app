// Highlight the row based on custom_ig checkbox
frappe.ui.form.on('BOM Item', {
    custom_ig: function(frm, cdt, cdn) {
        let row = frappe.get_doc(cdt, cdn);
        if (row) {
            let grid_row = cur_frm.fields_dict['items'].grid.grid_rows_by_docname[row.name];
            if (grid_row) {
                if (row.custom_ig) {
                    $(grid_row.wrapper).css('background-color', 'burlywood');
                } else {
                    $(grid_row.wrapper).css('background-color', '');
                }
            }
        }
    }
});

frappe.ui.form.on('BOM', {
    refresh: function(frm) {
        console.log('refresh event triggered');

        // 1. Apply background color to rows based on custom_ig flag
        if (frm.fields_dict && frm.fields_dict['items'] && frm.fields_dict['items'].grid) {
            let gridRows = frm.fields_dict['items'].grid.grid_rows;
            if (gridRows && gridRows.length > 0) {
                gridRows.forEach(function(gridRow) {
                    if (gridRow.doc) {
                        if (gridRow.doc.custom_ig) {
                            $(gridRow.wrapper).css('background-color', 'burlywood');
                        } else {
                            $(gridRow.wrapper).css('background-color', '');
                        }
                    }
                });
            }
        }

        // --- FIX STARTS HERE ---
        // 2. Only call the server-side method if the document is NOT NEW
        if (!frm.is_new()) {
            frappe.call({
                method: 'caf.caf.overrides.bom.check_qty',
                args: {
                    doc: frm.doc
                },
                callback: function(response) {
                    if (response.exc) {
                        frappe.msgprint(response.exc, 'Error');
                    } else {
                        console.log('check_qty function executed successfully.');
                    }
                }
            });
        }
        // --- FIX ENDS HERE ---

        // 3. Manually trigger custom_ig logic for each item
        if (frm.doc && frm.doc.items) {
            console.log('Triggering custom_ig for each item');
            frm.doc.items.forEach(item => {
                frm.trigger("custom_ig", {
                    cdt: "BOM Item",
                    cdn: item.name
                });
            });
        }

        // 4. Trigger recalculation (Moved from your second 'refresh' block)
        frm.trigger('recalculate_raw_materials');
    },

    items_add(frm) {
        frm.trigger('recalculate_raw_materials');
    },

    items_remove(frm) {
        setTimeout(() => {
            frm.trigger('recalculate_raw_materials');
        }, 50);
    },

    recalculate_raw_materials(frm) {
        update_total_input_and_percentage(frm);
    }
});

frappe.ui.form.on('BOM Item', {
    qty(frm) {
        frm.trigger('recalculate_raw_materials');
    },
    uom(frm) {
        frm.trigger('recalculate_raw_materials');
    }
});

function update_total_input_and_percentage(frm) {
    let total_input = 0;

    frm.doc.items.forEach(item => {
        if (item.stock_uom && item.stock_uom !== item.uom) {
            frappe.msgprint(
                `⚠️ UOM mismatch for item <b>${item.item_code}</b>:
                <br>Stock UOM = <b>${item.stock_uom}</b>
                <br>Row UOM = <b>${item.uom}</b>`
            );
            return;
        }

        if (item.uom === "Gram") {
            total_input += (item.qty || 0) / 1000;
        } else if (item.uom === "Kg") {
            total_input += (item.qty || 0);
        }
    });

    if (total_input === 0) {
        return;
    }

    frm.doc.items.forEach(item => {
        if (item.stock_uom && item.stock_uom !== item.uom) return;

        if (item.uom === "Gram" || item.uom === "Kg") {
            let item_qty_kg = item.uom === "Gram" ? item.qty / 1000 : item.qty;
            let percentage = Math.round((item_qty_kg / total_input) * 100 * 100) / 100;

            frappe.model.set_value(item.doctype, item.name, 'custom_qty_percentage', percentage);
        }
    });

    frm.set_value('custom_raw_materails', total_input);
    frm.refresh_field('items');
    frm.refresh_field('custom_raw_materails');
}