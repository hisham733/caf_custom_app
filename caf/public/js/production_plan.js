// frappe.ui.form.on("Production Plan", {
//       refresh: function(frm) {
//           frm.set_query("material_request", "material_requests", function () {
//               return {
//                   filters: {
//                       material_request_type: "Manufacture",
//                   //     docstatus: 1,
//                       status: ["!=", "Stopped"],
//                   },
//               };
//           });
//       }
//   });
  

// ==========================================
// PART 1: The Button Triggers
// ==========================================
frappe.ui.form.on('Production Plan', {
    // Trigger when 'Keep Only Recipe' button is clicked
    custom_keep_only_recipe: function(frm) {
        filter_sub_assembly_table(frm, 'Recipe');
    },

    // Trigger when 'Keep Only TIM' button is clicked
    custom_keep_only_tim: function(frm) {
        filter_sub_assembly_table(frm, 'WIP TIM');
    }
});

// ==========================================
// PART 2: The Logic (Fixed Version)
// ==========================================
function filter_sub_assembly_table(frm, keep_group) {
    // 1. Check if table has data
    if (!frm.doc.sub_assembly_items || frm.doc.sub_assembly_items.length === 0) {
        frappe.msgprint(__('Sub Assembly table is empty.'));
        return;
    }

    // 2. Get list of Item Codes
    let item_codes = frm.doc.sub_assembly_items.map(d => d.production_item);

    // 3. Fetch Item Groups using POST (frappe.call) to avoid URL limit errors
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'Item',
            filters: {
                name: ['in', item_codes]
            },
            fields: ['name', 'item_group'],
            limit_page_length: 5000 // High limit to ensure we get everything
        },
        callback: function(r) {
            if (!r.message) {
                console.log("Server returned no data.");
                return;
            }

            let items_data = r.message;
            let item_group_map = {};

            // Normalize data (Trim spaces to avoid mismatch)
            items_data.forEach(i => {
                item_group_map[i.name.trim()] = i.item_group;
            });

            console.log("--- DEBUG MAP START ---");
            console.log("Map size:", Object.keys(item_group_map).length);

            // --- CHECK FOR MATCHES ---
            let has_target_items = false;

            frm.doc.sub_assembly_items.forEach(row => {
                let p_item = row.production_item.trim();
                let actual_group = item_group_map[p_item];

                // Debug specific items to see what's happening
                if(row.idx <= 5) { 
                    console.log(`Item: ${p_item} | DB Group: '${actual_group}' | Keeping: '${keep_group}'`);
                }

                if (actual_group === keep_group) {
                    has_target_items = true;
                }
            });

            if (!has_target_items) {
                frappe.msgprint({
                    title: __('No Items Found'),
                    message: __('No items found with Item Group <b>' + keep_group + '</b>.<br>Please check that your Item Group spelling matches exactly.'),
                    indicator: 'red'
                });
                return;
            }

            // 4. Filter the rows
            let original_length = frm.doc.sub_assembly_items.length;
            
            let filtered_rows = frm.doc.sub_assembly_items.filter(row => {
                let p_item = row.production_item.trim();
                let group = item_group_map[p_item];
                return group === keep_group;
            });

            // 5. Update and Refresh
            frm.doc.sub_assembly_items = filtered_rows;
            frm.refresh_field('sub_assembly_items');

            let removed_count = original_length - filtered_rows.length;
            if (removed_count > 0) {
                frappe.show_alert({
                    message: __(`Removed ${removed_count} items. Kept only '${keep_group}'.`),
                    indicator: 'green'
                });
            }
        }
    });
}

frappe.ui.form.on("Production Plan", {
    refresh(frm) {
        // show only if NOT new AND already submitted
        if (!frm.is_new() && frm.doc.docstatus === 1) {
            frm.add_custom_button("Duplicate Plan", () => {
                frappe.call({
                    method: "caf.caf.overrides.production_plan.duplicate_production_plan",
                    args: {
                        docname: frm.doc.name
                    },
                    callback(r) {
                        if (r.message) {
                            frappe.msgprint("Production Plan duplicated successfully");
                            frappe.set_route("Form", "Production Plan", r.message);
                        }
                    }
                });
            });
        }
    }
});