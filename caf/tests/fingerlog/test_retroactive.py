"""T-39 — what happens AFTER the data underneath a decision changes.

    bench --site <site> execute caf.tests.fingerlog.test_retroactive.run

MG, 2026-09-10, listing what the suite should cover:

    MC          a BACKDATED medical approval
    UPL         submitted before the apply date
    Sat swap    a backdated submission by HR Manager
    holiday     a late public holiday
    "Refresh"   run at different states, when Attendance is AMENDED

⭐ They are one question — *what reaches a decision that was already made?* -
and they split into two halves that are in very different states:

  ① THE LEAVE HALF is built and tested. `appraisal_refresh` carries the whole
     mechanism (OD-44/FBR39) and `test_chunk5_appraisal` already walks A1-A5 and
     B3. A backdated MC and an early-filed UPL both arrive through
     `on_leave_application_submit`, which is the path chunk 5 exercises. **This
     file does not re-test it.**

  ② THE OTHER HALF IS NOT WIRED, and RT3 is here to say so out loud rather than
     let it be rediscovered. See its docstring.

And one thing that is neither: the **T-40 regression**. `allow_self_approval = 0`
went onto `CAF Leave Approval`'s final transition on 2026-09-10, after MG watched
fiza@ walk her own leave application from Draft to Approved unaided. Nothing
asserted it, so it could come back on the next `leave_workflow.apply` and nobody
would know. RT1/RT2 are that assertion.

RE-RUNNABLE: artifacts are removed FIRST, not last.
"""

import frappe
from frappe.model.workflow import get_transitions

# Two HR Managers. The whole point of allow_self_approval is that these are
# different people, so a fixture with one of them proves nothing.
OWNER = "fiza@caffood.com"
OTHER = "natalie@caffood.com"

# HR-EMP-00171 Siti Noratikah - a fixture employee since the T-37 re-point.
EMP = "HR-EMP-00171"

# ⚠️ June, not July: 2026-07 holds imported Finger Logs and a fixture on those
# dates has deleted real rows before. ⚠️ And NOT 2026-06-17 (Awal Muharram) -
# stock refuses a leave application whose every day is a holiday, and the refusal
# arrives long before any CAF logic.
FROM_DATE = "2026-06-08"
TO_DATE = "2026-06-09"

# `is_lwp = 1` skips the balance check entirely (FBR79), so this needs no Leave
# Allocation - which is what makes the fixture cheap and independent.
LEAVE_TYPE = "Leave Without Pay"

MARKER = "T-39 RETROACTIVE PROBE"

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def cleanup():
    for name in frappe.get_all("Leave Application",
                               filters={"description": ["like", f"%{MARKER}%"]},
                               pluck="name"):
        doc = frappe.get_doc("Leave Application", name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Leave Application", name,
                          force=True, ignore_permissions=True)


def _make_pending_final():
    """A leave application sitting at the LAST approval step, owned by OWNER.

    ⚠️ `workflow_state` is set directly rather than by walking the six earlier
    transitions. That is a FIXTURE shortcut and it is safe here for one reason:
    `Pending Final Approval` carries `doc_status = 0` (see
    `caf.scripts.leave_workflow.STATES`), so nothing about docstatus is being
    faked - the document really is a draft in that state. Walking the workflow
    would test the earlier transitions, which is not what RT1/RT2 are about.
    """
    frappe.set_user(OWNER)
    doc = frappe.get_doc({
        "doctype": "Leave Application",
        "employee": EMP,
        "leave_type": LEAVE_TYPE,
        "from_date": FROM_DATE,
        "to_date": TO_DATE,
        "description": MARKER,
        "status": "Open",
    })
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    frappe.db.set_value("Leave Application", doc.name,
                        "workflow_state", "Pending Final Approval",
                        update_modified=False)
    frappe.set_user("Administrator")
    return frappe.get_doc("Leave Application", doc.name)


def _actions_for(doc, user):
    """What the DESK would OFFER this user - the buttons, not the outcome."""
    frappe.set_user(user)
    try:
        return sorted({t.action for t in get_transitions(doc)})
    finally:
        frappe.set_user("Administrator")


def _try_action(doc_name, user, action):
    """What actually HAPPENS when the button is pressed. Returns None on success,
    else the exception class name.

    🔴 THIS, NOT `get_transitions`, IS WHERE allow_self_approval LIVES. Measured
    2026-09-10 in `frappe/model/workflow.py`: `get_transitions` filters on the
    state and the ROLE only (line ~64); the self-approval rule is in
    `has_approval_access` (line 221) -

        return user == "Administrator" or transition.get("allow_self_approval") \\
            or user != doc.get("owner")

    - which only `apply_workflow` calls. The first version of RT1 probed
    `get_transitions`, saw 'Approve' in the list and reported the fix as broken.
    It was the probe that was broken.
    """
    from frappe.model.workflow import apply_workflow
    frappe.set_user(user)
    try:
        apply_workflow(frappe.get_doc("Leave Application", doc_name), action)
        return None
    except Exception as exc:
        return type(exc).__name__
    finally:
        frappe.set_user("Administrator")


def run():
    frappe.set_user("Administrator")
    cleanup()
    frappe.db.commit()

    # ------------------------------------------------------------- RT1 / RT2
    doc = _make_pending_final()
    try:
        check("RT0", doc.owner == OWNER,
              f"fixture sanity: the application's owner is '{doc.owner}' and must "
              f"be {OWNER} - allow_self_approval compares against doc.owner, so a "
              f"fixture owned by Administrator would prove nothing")

        # RT1 - the block itself, at the point Frappe actually enforces it.
        blocked = _try_action(doc.name, OWNER, "Approve")
        state_after = frappe.db.get_value("Leave Application", doc.name,
                                          "workflow_state")
        check("RT1", blocked is not None and state_after == "Pending Final Approval",
              f"the OWNER ({OWNER}) presses Approve at the FINAL step: "
              f"{blocked or 'IT SUCCEEDED'}; state afterwards='{state_after}' (must "
              f"stay Pending Final Approval). FBR94/T-40 - MG watched fiza@ walk her "
              f"own leave to Approved unaided because every transition allowed "
              f"self-approval")

        # RT1b - ⚠️ the BUTTON is still offered. `get_transitions` filters on state
        # and role only, so the desk shows Approve to the owner and refuses when
        # pressed. Asserted so nobody "fixes" this by hiding the button and
        # quietly removes the enforcement with it.
        owner_actions = _actions_for(doc, OWNER)
        check("RT1b", "Approve" in owner_actions,
              f"the desk still OFFERS {owner_actions} to the owner - the refusal is "
              f"on the press, not on the button (get_transitions checks state+role "
              f"only; allow_self_approval lives in has_approval_access). ⚠️ A "
              f"usability wrinkle, deliberately recorded rather than hidden")

        # RT2 - the control. If the block went too far, no leave could ever be
        # approved at all, and RT1 alone could not tell the difference.
        ok = _try_action(doc.name, OTHER, "Approve")
        state_other = frappe.db.get_value("Leave Application", doc.name,
                                          "workflow_state")
        check("RT2", ok is None and state_other == "Approved",
              f"a DIFFERENT HR Manager ({OTHER}) presses Approve: "
              f"{ok or 'succeeded'}; state='{state_other}' (must be Approved) - "
              f"without this, RT1 would pass just as well against a workflow that "
              f"blocks everybody")
    finally:
        cleanup()
        frappe.db.commit()

    # RT2b - the block is on the LAST step ONLY. HR files leave FOR other people
    # (MG watched fiza@ key one in for Tham), so blocking doc.owner everywhere
    # would freeze routine data entry - which is typing, not a signature.
    doc2 = _make_pending_final()
    try:
        frappe.db.set_value("Leave Application", doc2.name, "workflow_state",
                            "Pending Supervisor", update_modified=False)
        mid = _try_action(doc2.name, OWNER, "Approve")
        mid_state = frappe.db.get_value("Leave Application", doc2.name,
                                        "workflow_state")
        check("RT2b", mid is None and mid_state == "Pending HR Manager",
              f"the SAME owner at an EARLIER step presses Approve: "
              f"{mid or 'succeeded'}; state='{mid_state}' (must advance to Pending "
              f"HR Manager) - FBR94 is deliberately the final transition only")
    finally:
        cleanup()
        frappe.db.commit()

    # ------------------------------------------------------------------- RT3
    # 🔴 THE HALF THAT IS NOT WIRED. Two of MG's five scenarios have no route to
    # a submitted appraisal at all, and this asserts the INVENTORY so that a
    # trigger which is silently removed is caught, and the two that were never
    # built stay visible instead of being rediscovered.
    #
    # Measured 2026-09-10 from hooks.py and from every caller of `refresh_for`:
    #
    #   Leave Application  ✅ on_leave_application_submit / _cancel   (OD-44)
    #   Shift Assignment   ✅ on_shift_assignment_refresh             (OD-44)
    #   Finger Log         ✅ finger_log_scope.refresh_appraisal_*    (D-15)
    #   OT Approval        ✅ calls refresh_for directly
    #   Holiday List       ⚠️ on_public_holidays_changed - regenerates the
    #                         alternate-Saturday calendars and WARNS the human
    #                         ("Any Finger Log, Attendance, Leave Application or
    #                         Shift Assignment already filed against them needs
    #                         checking"), but does NOT refresh any appraisal
    #   Attendance         🔴 before_cancel only, and that is a GUARD, not a
    #                         refresh. An amended Attendance reaches nothing
    from caf.caf import appraisal_refresh as ar

    wired = {
        "Leave Application": hasattr(ar, "on_leave_application_submit"),
        "Shift Assignment": hasattr(ar, "on_shift_assignment_refresh"),
    }
    check("RT3", all(wired.values()),
          f"the refresh entry points OD-44 names still exist: {wired} - if one "
          f"disappears, a late leave or a backdated Saturday swap stops reaching "
          f"submitted appraisals and nothing else would notice")

    hooks = frappe.get_hooks("doc_events") or {}
    holiday_events = list((hooks.get("Holiday List") or {}).keys())
    attendance_events = list((hooks.get("Attendance") or {}).keys())
    refreshes_appraisal = any(
        "appraisal" in str(v).lower()
        for v in (hooks.get("Attendance") or {}).values())

    check("RT3b", not refreshes_appraisal,
          f"⚠️ RECORDING A GAP, NOT A PASS. Attendance carries {attendance_events} "
          f"and Holiday List carries {holiday_events} - NEITHER refreshes an "
          f"appraisal. So MG's scenarios 4 (a late public holiday) and 5 (an "
          f"AMENDED Attendance) have no automatic route to a submitted appraisal; "
          f"the holiday path warns a human and stops. 🔴 Whether they SHOULD is "
          f"MG's decision - see GO_LIVE_TODO T-39. This assertion flips the day "
          f"one is wired, which is the reminder to update it")

    frappe.set_user("Administrator")
    print("\n=== T-39 — retroactive change: does it reach the decision? ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:6s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
