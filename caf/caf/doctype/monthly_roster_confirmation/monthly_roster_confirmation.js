// Monthly Roster Confirmation — OD-71 (a) + (b).
// ==============================================
// Purpose : the desk form for the monthly confirmation — the quick "nothing new"
//           action, and the pre-filled Saturday rows HR ticks rather than types.
// Doctype : Monthly Roster Confirmation
// Server  : caf/caf/doctype/monthly_roster_confirmation/monthly_roster_confirmation.py
// Refs    : framework §6.12 (OD-71) · §6.13a · OD-74 · test plan ROSTER-*
//
// Changelog
// ---------
// 1.0  2026-08-13  Initial — OD-71 (a) + (b)
//
// The quick answer is the DEFAULT one: eleven months out of twelve there is no
// new holiday, so "Nothing new this month" is the primary action and filling the
// table is the exception.
//
// The Saturday rows are pre-filled from the generated calendar and HR ticks
// them. They are not a second rendering of the roster screen — MG: "but don't
// you already have a dashboard that shows this?" — so the form LINKS to it
// rather than redrawing it.

frappe.ui.form.on("Monthly Roster Confirmation", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.doc.no_new_holidays
			&& !(frm.doc.holidays || []).length) {
			frm.page.set_primary_action(__("Nothing new this month"), () => {
				frm.set_value("no_new_holidays", 1);
				frm.save();
			});
		}

		if (frm.doc.month_start) {
			frm.add_custom_button(__("Open the roster screen"), () => {
				frappe.set_route("shift-roster");
			});
		}

		if (frm.doc.docstatus === 1) {
			const added = (frm.doc.holidays || []).filter((r) => r.added_to_list);
			if (added.length) {
				frm.dashboard.add_comment(
					__("{0} holiday(s) were appended to the Holiday List, which regenerated the alternate-Saturday calendars. Anything already filed on a Saturday that moved needs checking.", [added.length]),
					"orange", true);
			}
		}
	},

	no_new_holidays(frm) {
		if (frm.doc.no_new_holidays && (frm.doc.holidays || []).length) {
			frappe.msgprint(__("Clear the holiday table first — 'nothing new' and a list of new things cannot both be true."));
			frm.set_value("no_new_holidays", 0);
		}
	},
});

frappe.ui.form.on("Monthly Roster Holiday", {
	// Fill the day from the date as a CONVENIENCE, never as the check. The
	// server compares the two independently on save (MG's checksum): if HR
	// overtypes the day, or pastes a date, the disagreement is what catches it.
	holiday_date(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.holiday_date || row.day_of_week) return;
		const names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
			"Friday", "Saturday"];
		frappe.model.set_value(cdt, cdn, "day_of_week",
			names[frappe.datetime.str_to_obj(row.holiday_date).getDay()]);
	},
});
