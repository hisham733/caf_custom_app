// Shift Assignment list — hosts "Trade a Saturday". Chunk 7.3, OD-65.
// ====================================================================
// A trade is TWO Shift Assignments, one per employee. Filed by hand, one gets
// forgotten and Mr A works the Saturday while Mr B is still rostered for it,
// silently. The dialog files both, or neither.
//
// ⚠️ The dialog itself now lives in `public/js/shift_trade.js` — Chunk 7.5's
// roster page opens the same one from a grid cell, and two copies of a dialog
// that files documents drift apart silently.
//
// Changelog
// ---------
// 1.1  2026-08-12  Dialog extracted to caf.shift_trade (7.5)
// 1.0  2026-08-12  Initial — Chunk 7.3

frappe.listview_settings["Shift Assignment"] = {
	onload(listview) {
		// Tidiness, not a lock: `frappe.only_for` in shift_swap.py is the gate.
		if (!caf.shift_trade.may_file()) {
			return;
		}

		listview.page.add_inner_button(__("Trade a Saturday"), () => caf.shift_trade.open());
	},
};
