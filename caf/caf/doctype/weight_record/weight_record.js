// Copyright (c) 2025, hisham and contributors
// For license information, please see license.txt

frappe.ui.form.on("Weight Record", {
      onload_post_render(frm) {
          // Set default values only if empty
          const full_name = frappe.user_info(frappe.session.user).fullname;
          const date = frappe.datetime.now_date();
          const time = frappe.datetime.now_time();
  
          if (!frm.doc.employee_name) {
              frm.set_value("employee_name", full_name);
          }
  
          if (!frm.doc.work_date) {
              frm.set_value("work_date", date);
          }
  
          if (!frm.doc.work_time) {
              frm.set_value("work_time", time);
          }
      },
  
      refresh(frm) {
          // Update totals every time form is refreshed
          update_totals(frm);
      }
  });
  
  // Event for child table field change
  frappe.ui.form.on("Raw Chicken Table", {  // <-- Replace with your actual child table doctype name
      user_qty: function (frm, cdt, cdn) {
          update_totals(frm);
      }
  });
  
  // Core function to count and sum values
  function update_totals(frm) {
      const rows = frm.doc.user_qty_in || [];
      const total_count = rows.length;
      const total_qty = rows.reduce((sum, row) => sum + flt(row.user_qty || 0), 0);
  
      frm.set_value('total_count', total_count);
      frm.set_value('total_qty', total_qty);
  }
  