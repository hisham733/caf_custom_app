"""Monthly Roster Holiday — a child row of Monthly Roster Confirmation.

Purpose : one new public or company holiday HR is declaring for the month.
Parent  : Monthly Roster Confirmation
Refs    : framework §6.12 (OD-71) · OD-74 · test plan ROSTER-*

⚠️ **All the logic lives in the PARENT.** The day-of-week checksum (MG,
2026-08-13 — name, date and day entered independently so a typo has something to
disagree with) is enforced in `MonthlyRosterConfirmation.check_day_matches_date`,
because a child row cannot refuse its own save and validating per row would let
the parent submit with a bad row in it.

Changelog
---------
1.0  2026-08-13  Initial — OD-71 (a)
"""

from frappe.model.document import Document


class MonthlyRosterHoliday(Document):
    pass
