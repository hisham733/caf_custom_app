"""Reach the Attendance a Finger Log produced — MG's manual-test finding.

Hooked as `override_doctype_dashboards["Finger Log"]`.

🔴 THE ASYMMETRY THIS CLOSES
----------------------------
The link between the two documents has existed since Chunk 3, and it points one
way in the UI:

    Finger Log  ──── on_submit creates ───►  Attendance
         ▲                                        │
         └──────  Attendance.caf_finger_log  ◄────┘

From an Attendance record you can open its Finger Log — the field is right there.
From a **Finger Log** there was no way back: HR had to open the Attendance list
and search by employee and date, for a document this one created.

⚠️ **A connections panel adds NO constraint** — MG asked precisely this before
approving it. It is a **read-only query** (`Attendance` where
`caf_finger_log = <this name>`), not a stored reference:

  · it creates no new link, so it changes nothing about deleting or cancelling
    either document — the guard that already exists is
    `Attendance.caf_finger_log` itself, and that is unchanged;
  · cancelling either side leaves the panel working; it simply shows a cancelled
    document, which is the honest answer and is what §6.6 wants — Attendance is
    **cancelled, never deleted**, so the trail must stay reachable;
  · it re-reads on every form load, so nothing can go stale.

Measured 2026-09-02: 1,334 Attendance rows are cancelled and 3,970 submitted, so
the cancelled case is not hypothetical — it is a quarter of the table, and each
one is somebody's day that was reclassified.

⚠️ **Attendance ONLY, deliberately.** Leave Application was the obvious second
candidate — the leave clash is the most confusing refusal in the system — but it
carries **no field pointing at a Finger Log**: the two are joined by employee and
date. A connections panel needs a real link field, so listing it would either
show nothing or need a fabricated one. The leave is instead made reachable where
it actually matters: `assert_no_clash` now puts a **hyperlink to the Leave
Application** in the refusal itself, which is the moment somebody needs it.
"""

import frappe
from frappe import _


def get_data(data=None):
    return {
        # The link is Attendance's own field, which has existed since Chunk 3 —
        # this only makes it navigable in the other direction.
        "fieldname": "caf_finger_log",
        "transactions": [
            {
                "label": _("The verdict this log produced"),
                "items": ["Attendance"],
            },
        ],
    }
