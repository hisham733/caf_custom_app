// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// frm is pointing to local instance of OT Approval
frappe.ui.form.on("OT Approval Table", {
	// this code will be triggered only when the OT Approval Table.emp_id, which is the child table of OT Approval Table, is changed
	emp_id: function(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		// test if emp_id is empty
		if(row.emp_id) {
			// verify that work_date has been filled
			// if (frm.doc.work_date) {
			// 	var row = locals[cdt][cdn];
			// 	// copy the value of work_date from parent table to child table
			// 	frappe.model.set_value(cdt, cdn, "work_date", frm.doc.work_date);
			// } else {
			// 	frappe.msgprint({
			// 		title: __('Error'),
			// 		message: __('Please fill in the Work Date, first'),
			// 		indicator: 'red'
			// 	});
			// }

			//console.log("emp_id", row.emp_id);

			// set OT Approval Table.emp_id = Employee.name
			frappe.db.get_value('Employee', { 'name': row.emp_id }, 'employee_name')
			.then(r => {
				// r is the response from the query, which is an object with employee_name from Employee doctype
				// console.log("r", r);
				let temp = r.message.employee_name;
				frappe.model.set_value(cdt, cdn, "emp_name", temp);
			});
		}
	},

	// this code will be triggered only when the OT Approval Table.ot_duration, which is the child table of OT Approval Table, is changed
	ot_duration: function(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		console.log("row.ot_duration", row.ot_duration);
		// test if ot_duration is not empty
		if(row.ot_duration) {
			console.log("ot_duration - ran");
			// verify that ot_duration is a float number, where value can only be multiple of 0.5
			let otDuration = parseFloat(row.ot_duration);
			// if otDuration is not a multiple of 0.5, then throw an error
			if (otDuration % 0.5 !== 0) {
				frappe.msgprint({
					title: __('Error'),
					message: __('OT Duration must be multiple of 0.5'),
					indicator: 'red'
				});
				// exit this frappe function
				return;
			}
		}
	}
});

// Add the employee filtering logic for emp_id in OT Approval Table
// This is to ensure all fetch employee's status = Active
frappe.ui.form.on('OT Approval', {
// This event runs when the user clicks "Save"
    validate: function(frm) {
        // 1. Mandatory Check: Parent work_date MUST exist
        if (!frm.doc.work_date) {
            frappe.throw({
                title: __("Missing Information"),
                message: __("Please fill in the <b>Work Date</b> before saving."),
                indicator: 'red'
            });
        }
        // 2. Date Validation: Block future dates
        if (frm.doc.work_date > frappe.datetime.get_today()) {
            frappe.throw({
                title: __("Invalid Date"),
                message: __("OT approval date is greater than today"),
                indicator: 'red'
            });
        }
        // 3. Batch Sync: Force child table dates to match parent
        if (frm.doc.emp_list && frm.doc.emp_list.length > 0) {
            frm.doc.emp_list.forEach(row => {
                // Now we are safe: frm.doc.work_date is guaranteed to have a value here
                frappe.model.set_value(row.doctype, row.name, "work_date", frm.doc.work_date);
            });
            // Refresh field so the DB receives the correct hidden values
            frm.refresh_field("emp_list");
        }
    },
    onload: function(frm) {
        // Ensure child table has at least one row
        if (!frm.doc.emp_list || frm.doc.emp_list.length === 0) {
            let new_row = frappe.model.add_child(frm.doc, "OT Approval Table", "emp_list");
            frm.refresh_field("emp_list");
        }
		console.log("OT Approval onload");
        // Apply filter to Employee field inside the child table
        frm.fields_dict["emp_list"].grid.get_field("emp_id").get_query = function(doc, cdt, cdn) {
            return {
                filters: {
                    status: "Active"  // Only fetch employees with status = Active
                }
            };
        };
    }
});

