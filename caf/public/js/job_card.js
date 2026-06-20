
frappe.ui.form.on('Job Card', {
	refresh: function(frm) {
		console.log("Job Card Custom Script Loaded from override");

	    // Add a custom button to the Job Card form
	    frm.add_custom_button(__('Create QI from Job Card'), function() {
		  // Trigger the Python function to create the QI from the Job Card
		  create_qi_from_job_card(frm);
	    });
	}
  });
  
  // Function to create QI from Job Card
  function create_qi_from_job_card(frm) {
	const job_card = frm.doc;
  
	// Validate if work order is provided
	if (!job_card.work_order) {
	    frappe.msgprint(__('Work Order is missing from this Job Card.'));
	    return;
	}
  
	// Call the Python function to create the QI document
	frappe.call({
	    method: 'caf.caf.overrides.job_card.create_qi_from_job_card',
	    args: {
		  job_card_name: job_card.name
	    },
	    callback: function(response) {
		  const qi_doc_name = response.message;
		  if (qi_doc_name) {
			// If QI creation is successful, show a message and open the QI form
			// frappe.msgprint(__('Quality Inspection (QI) created successfully.'));
			frappe.set_route('Form', 'Quality Inspection', qi_doc_name);
		  }
	    }
	});
  }

  