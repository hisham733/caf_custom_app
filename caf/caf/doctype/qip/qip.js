frappe.ui.form.on("QIP", {
      qc_name: function(frm) {
          console.log("QIP form loaded");
          if (frm.doc.qc_name === "INCOMING MATERIAL INSPECTION CHECKLIST") {
              console.log("Form is new, fetching latest QIP Goal data...");
              fetch_latest_qip_data(frm);
          }
      },
      
      refresh: function(frm) {
            console.log("QIP form loaded");
            if (frm.doc.qc_name === "INCOMING MATERIAL INSPECTION CHECKLIST") {
                  console.log("Form is new, fetching latest QIP Goal data...");
                  fetch_latest_qip_data(frm);
            }
      }
});

  
  function fetch_latest_qip_data(frm) {
      frappe.call({
          method: "frappe.client.get_list",
          args: {
              doctype: "QIP Goal",
              fields: ["name"],
              order_by: "creation desc",
              limit_page_length: 1
          },
          callback: function(r) {
              console.log("get_list response:", r);
              if (r.message && r.message.length > 0) {
                  let latest_name = r.message[0].name;
                  console.log("Latest QIP Goal name:", latest_name);
  
                  frappe.call({
                      method: "frappe.client.get",
                      args: {
                          doctype: "QIP Goal",
                          name: latest_name
                      },
                      callback: function(res) {
                          console.log("get response:", res);
                          if (res.message) {
                              let goal = res.message;
  
                              // Clear both child tables
                              frm.clear_table("qc_table");
                              frm.clear_table("qc_table1");
                              console.log("Cleared qc_table and qc_table1");
  
                              // Populate qc_table from section_a (vehicle_inspection only)
                              (goal.section_a || []).forEach(row => {
                                  console.log("Adding qc_table row with vehicle_inspection:", row.vehicle_inspection);
                                  let child = frm.add_child("qc_table");
                                  child.vehicle_inspection = row.vehicle_inspection || "";
                              });
  
                              // Populate qc_table1 from section_b (copy vehicle_inspection or change as needed)
                              (goal.section_b || []).forEach(row => {
                                  console.log("Adding qc_table1 row with material_physical_inspection:", row.material_physical_inspection);
                                  let child = frm.add_child("qc_table1");
                                  child.material_physical_inspection = row.material_physical_inspection || "";
                              });
  
                              frm.refresh_field("qc_table");
                              frm.refresh_field("qc_table1");
                              frappe.msgprint("QC Table and QIP Table 1 filled from latest QIP Goal.");
                              console.log("qc_table and qc_table1 refreshed and message shown");
                          }
                      }
                  });
              } else {
                  console.log("No QIP Goal records found.");
              }
          }
      });
  }
  