// Shift Assignment form — warn before half-cancelling a trade. Chunk 7.3, OD-65.
// =============================================================================
// MG's decision: neither auto-cancel nor refuse. Auto-cancelling would change
// another employee's roster from a form that looks ordinary; refusing would block
// a legitimate cancel until HR hunts for the other row. So: NAME the partner and
// let HR choose.
//
// ⚠️ The database can no longer refuse this on its own. `caf_swap_partner` is a
// real Link and Frappe's link check fires on cancel, so a half-cancel used to
// raise LinkExistsError naming two document IDs and explaining nothing. The
// `unlink_pair` hook clears the pairing so the cancel CAN proceed — which is
// exactly why this warning has to exist. Without it the half-cancel became
// possible and silent at the same moment.
//
// Changelog
// ---------
// 1.0  2026-08-12  Initial — Chunk 7.3

frappe.ui.form.on("Shift Assignment", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frm.doc.caf_swap_with) return;

		frm.dashboard.add_comment(
			frm.doc.caf_swap_kind === "Cover"
				? __("This is a one-way cover traded with {0}.", [frm.doc.caf_swap_with])
				: __("This is one half of a swap with {0}.", [frm.doc.caf_swap_with]),
			frm.doc.caf_swap_partner ? "blue" : "orange",
			true
		);

		// Intercept the cancel while the pair is still live. Once the partner is
		// gone there is nothing left to warn about.
		if (!frm.doc.caf_swap_partner) return;

		const original = frm.page.btn_secondary;
		frm.page.clear_menu();
		frm.add_custom_button(__("Cancel this trade"), () => caf_confirm_cancel(frm));
	},
});

function caf_confirm_cancel(frm) {
	frappe.call({
		method: "caf.caf.shift_swap.partner_of",
		args: { assignment: frm.doc.name },
	}).then((r) => {
		const info = (r && r.message) || {};
		if (!info.paired || !info.partner) {
			frm.savecancel();
			return;
		}

		const esc = frappe.utils.escape_html;
		const d = new frappe.ui.Dialog({
			title: __("This is half of a swap"),
			fields: [
				{
					fieldtype: "HTML",
					options: `
						<p>${__("On {0}, this was traded with {1}.", [
							esc(info.work_date), esc(info.traded_with_name),
						])}</p>
						<table class="table table-sm">
							<tr><td>${esc(frm.doc.employee)}</td><td>${esc(frm.doc.shift_type)}</td>
								<td>${__("this document")}</td></tr>
							<tr><td>${esc(info.partner.employee_name)}</td><td>${esc(info.partner.shift_type)}</td>
								<td><a href="/app/shift-assignment/${encodeURIComponent(info.partner.name)}">${esc(info.partner.name)}</a></td></tr>
						</table>
						<p class="text-muted">${__("Cancelling only this one leaves the other person on the traded shift. That is sometimes what you want — it just should not happen by accident.")}</p>`,
				},
			],
			primary_action_label: __("Cancel both"),
			primary_action() {
				d.hide();
				frappe.call({
					method: "caf.caf.shift_swap.cancel_both",
					args: { assignment: frm.doc.name },
					freeze: true,
				}).then(() => frm.reload_doc());
			},
			secondary_action_label: __("Cancel only this one"),
			secondary_action() {
				d.hide();
				frm.savecancel();
			},
		});
		d.show();
	});
}
