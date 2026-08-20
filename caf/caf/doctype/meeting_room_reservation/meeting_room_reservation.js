frappe.ui.form.on("Meeting Room Reservation", {
	refresh: function (frm) {
		frm.set_query("employee", function () {
			return { filters: { status: "Active" } };
		});
	},
});
