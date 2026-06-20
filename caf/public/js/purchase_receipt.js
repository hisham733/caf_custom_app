frappe.ui.form.on('Purchase Receipt', {
	refresh: function(frm) {
	    if (!frm.doc.__islocal && frm.doc.items && frm.doc.items.length > 0) {
		  frm.add_custom_button(__('Weight Records'), function () {
			frappe.call({
			    method: "frappe.client.insert",
			    args: {
				  doc: {
					doctype: "Weight Record",
					purchase_receipt_no: frm.doc.name,
					def_supplier: frm.doc.supplier,
					item: frm.doc.items[0].item_code  // ✅ Assuming first item
				  }
			    },
			    callback: function(r) {
				  if (r.message) {
					frappe.msgprint("✅ Weight Record created: " + r.message.name);
					frappe.set_route("Form", "Weight Record", r.message.name);
				  }
			    }
			});
		  }, __('Create'));
	    }
	}
  });
  
  