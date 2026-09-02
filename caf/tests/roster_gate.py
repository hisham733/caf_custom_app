"""Suspend the Finger Log roster gate for the length of a suite.

    from caf.tests.roster_gate import suspended
    with suspended():
        ...create and submit Finger Logs dated after the gate...

WHY THIS EXISTS
---------------
`HR Settings.caf_roster_gate_from` was set to **2026-09-01** on 2026-09-02 (T-26),
and `require_confirmed_month` then refuses to submit any Finger Log whose work
date falls in a month with no submitted `Monthly Roster Confirmation`. That is
the point of the gate — and it immediately broke two suites that had done nothing
wrong:

    test_amend              fixtures on 2026-09-22..24, chosen because those
                            dates were measured EMPTY
    test_chunk3_decisions   fixtures in 2026-10, chosen to sit past the seeded
                            OT Approvals

Moving them to June would collide with the suites that already live there and
would throw away the reason each month was picked. So the gate is suspended
around them instead — the pattern `test_monthly_roster` and `test_chunk_t`
already use, lifted into one place so the next suite does not re-derive it.

🔴 RESTORE BY MEANING, NOT BY VALUE
-----------------------------------
Clearing a `Date` on a **Single** does not reliably store NULL: it leaves a
sentinel that `getdate()` reads back as **`0001-01-01`** — truthy, in the past,
and therefore a gate that refuses every Finger Log ever recorded. `gate_from()`
normalises that to `None` (anything before 1900 is nobody's go-live date), so the
snapshot taken and compared here is what `gate_from()` returns, never the raw
field. Reading it raw once made `test_monthly_roster` non-re-runnable: pass, then
fail, then pass.

⚠️ A suite using this must still ASSERT that the gate came back — a helper that
restores silently is one failed restore away from disabling a production guard on
someone's site. `restored()` returns the comparison for that assertion.
"""

from contextlib import contextmanager

import frappe

from caf.caf.doctype.monthly_roster_confirmation import monthly_roster_confirmation as mrc


def _set(value):
    frappe.db.set_single_value("HR Settings", mrc.GATE_FIELD, value or "")
    frappe.db.commit()
    frappe.clear_document_cache("HR Settings", "HR Settings")
    frappe.clear_cache(doctype="HR Settings")
    return mrc.gate_from()


@contextmanager
def suspended():
    """Turn the gate off, and put back exactly the MEANING that was there."""
    before = mrc.gate_from()
    try:
        _set("")
        yield before
    finally:
        _set(before)


def restored(before):
    """(ok, detail) — for the suite's own RESTORE assertion."""
    now = mrc.gate_from()
    return now == before, (
        f"caf_roster_gate_from is back to {now!r} (was {before!r}). Compared "
        f"through gate_from(), not the raw Single: clearing a Date there stores a "
        f"sentinel that reads back as 0001-01-01, and restoring the raw value "
        f"would leave a gate that refuses every Finger Log ever recorded")
