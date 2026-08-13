"""Monthly Roster Saturday — a child row of Monthly Roster Confirmation.

Purpose : one alternate-Saturday group on one Saturday, PRE-FILLED from the
          generated calendar for HR to confirm.
Parent  : Monthly Roster Confirmation
Refs    : framework §6.12 (OD-71 b) · §6.13a · roadmap §9d.5

🔴 **Confirmation, not entry, and that is the whole point.** MG asked for a
monthly to-do to *set* workday/restday by hand, "same as the policy at Ingress".
The evidence says the manual step is where the errors came from — February's
unrecorded holiday and its four mislabelled day types were both hand-entry — and
the generated calendar already matches practice 17/18 and 16/18 from the anchor.
So every field here is read-only except the tick.

Changelog
---------
1.0  2026-08-13  Initial — OD-71 (b)
"""

from frappe.model.document import Document


class MonthlyRosterSaturday(Document):
    pass
