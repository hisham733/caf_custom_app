// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Finger Log", {
	refresh(frm) {
		if (frm.doc.__islocal) return;
		if (!frappe.user.has_role("HR Manager") && !frappe.user.has_role("System Manager")) return;

		// 🔴 The button exists for ONE scenario: the punches in ERPNext are
		// wrong. Amend cannot fix that — every punch field is read_only, so
		// nobody can type a correction, and copy_doc carries the wrong values
		// straight into the amendment. The machine is the single source of
		// punch facts (FDR10), so the only honest repair is to read it again.
		//
		// When the punches are RIGHT and something around them was wrong — the
		// OT approval, the shift — Amend is the route, and the dialog says so
		// rather than letting someone pick the wrong tool quietly.
		frm.add_custom_button(__("Re-import from Ingress"), () => {
			const human_owned = frm.doc.docstatus !== 2;
			frappe.confirm(
				__("Re-read {0} for {1} from the Ingress machine.<br><br><b>Use this only when the PUNCHES are wrong.</b> If the punches are right and the OT approval or the shift was wrong, cancel and <b>amend</b> instead — amending keeps the punches and re-reads the approval.<br><br>If the machine itself is wrong, correct it in the Ingress app first: ERPNext will not let anyone type a punch.",
				   [frappe.format(frm.doc.work_date, { fieldtype: "Date" }), frm.doc.employee]) +
				(human_owned
					? "<br><br><b>" + __("This log is not cancelled — cancel it first.") + "</b>"
					: ""),
				() => {
					frappe.call({
						method: "caf.caf.ingress.sync.reimport_day",
						args: { finger_log: frm.doc.name, submit: 0 },
						freeze: true,
						freeze_message: __("Reading the Ingress machine…"),
						callback(r) {
							if (!r.message) return;
							const c = r.message.counts;
							frappe.msgprint({
								title: __("Batch {0}", [r.message.batch]),
								indicator: c.created ? "green" : "orange",
								message: __("Created {0} · updated {1} · human-owned {2} · failed {3}",
									[c.created, c.updated, c.skipped_locked, c.failed]),
							});
							frappe.set_route("List", "Finger Log", {
								employee: frm.doc.employee,
								work_date: frm.doc.work_date,
							});
						},
					});
				});
		}, __("Actions"));

		if (frm.doc.caf_import_batch) {
			frm.add_custom_button(__("Import batch"), () => {
				frappe.set_route("Form", "Ingress Import Batch", frm.doc.caf_import_batch);
			}, __("Actions"));
		}
	},
});
