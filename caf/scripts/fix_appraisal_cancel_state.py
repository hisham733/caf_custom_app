"""A cancelled appraisal must not still read "Completed".

    bench --site <site> execute caf.scripts.fix_appraisal_cancel_state.run
    bench --site <site> execute caf.scripts.fix_appraisal_cancel_state.run --kwargs "{'apply':1}"

MG spotted it in the manual test (Pass C5): after cancelling `HR-APR-2026-00309`,
*"AP.doc.status = still completed"*, and in the list view alongside its own
amendment — *"if status = Completed (green text) may be confusing"*.

It is worse than confusing. `workflow_state` is what the list view, the appraisal
dashboard and the supervisor page all read. A cancelled appraisal showing
**Completed in green** is a document telling you the opposite of the truth, and the
one place that would correct you — `docstatus` — is not on screen.

WHY IT HAPPENS
--------------
The CAF Appraisal Workflow has no state for `doc_status = 2`:

    Draft              0
    Pending HR Review  0
    Completed          1
    (nothing)          2   ← cancel has nowhere to land

Frappe's Cancel sets `docstatus = 2` directly; only `apply_workflow` moves
`workflow_state`. With no cancelled state to move to, the old value simply stays.

**The Leave workflow already gets this right** — `CAF Leave Approval` carries a
`Cancelled` state at doc_status 2, reached by an explicit `Cancel` transition. The
appraisal workflow is the odd one out, which is the strongest argument that this is
an omission and not a decision.

WHAT THIS DOES
--------------
1. adds a `Cancelled` state (doc_status 2) to the workflow **fixture**, so it
   travels with the code rather than being site-only;
2. adds `Completed → Cancel → Cancelled`, allowed to HR Manager, so the route is
   discoverable in the Actions menu the way Leave's is;
3. backfills documents already cancelled — 3 of them at time of writing.

The belt to that brace is `on_cancel` in `overrides/appraisal.py`, which sets the
state whichever way the document was cancelled — the Actions menu, the standard
Cancel button, or code. A transition alone would only cover the first.
"""

import frappe

WORKFLOW = "CAF Appraisal Workflow"
CANCELLED = "Cancelled"


def _ensure_state_doc():
    if not frappe.db.exists("Workflow State", CANCELLED):
        doc = frappe.new_doc("Workflow State")
        doc.workflow_state_name = CANCELLED
        doc.style = "Danger"
        doc.insert(ignore_permissions=True)
        return f"created Workflow State {CANCELLED}"
    return None


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")
    acted = []

    wf = frappe.get_doc("Workflow", WORKFLOW)
    states = [s.state for s in wf.states]
    transitions = [(t.state, t.action, t.next_state) for t in wf.transitions]

    print(f"\n{WORKFLOW}")
    print(f"  states now      : {[(s.state, s.doc_status) for s in wf.states]}")
    print(f"  has '{CANCELLED}' state? {CANCELLED in states}")
    print(f"  has Cancel transition? "
          f"{any(t[1] == 'Cancel' for t in transitions)}")

    stale = frappe.get_all("Appraisal",
                           filters={"docstatus": 2,
                                    "workflow_state": ("!=", CANCELLED)},
                           fields=["name", "workflow_state", "owner"])
    print(f"\n  cancelled documents still showing another state: {len(stale)}")
    for s in stale:
        print(f"    {s.name:24s} shows {s.workflow_state!r}  (owner {s.owner})")

    if not apply:
        print("\n(report only — pass apply=1 to fix)")
        return {"stale": len(stale)}

    msg = _ensure_state_doc()
    if msg:
        acted.append(msg)

    if CANCELLED not in states:
        wf.append("states", {
            "state": CANCELLED, "doc_status": "2", "allow_edit": "HR Manager",
            "is_optional_state": 0, "avoid_status_override": 0, "send_email": 0,
        })
        acted.append(f"added state {CANCELLED}")

    if not any(t[1] == "Cancel" for t in transitions):
        wf.append("transitions", {
            "state": "Completed", "action": "Cancel", "next_state": CANCELLED,
            "allowed": "HR Manager", "allow_self_approval": 1,
        })
        acted.append("added transition Completed → Cancel → Cancelled")

    if acted:
        wf.flags.ignore_permissions = True
        wf.save(ignore_permissions=True)

    for s in stale:
        # db_set, not save(): the document is cancelled, so an ordinary save is
        # refused, and this is a display correction rather than a change of fact.
        frappe.db.set_value("Appraisal", s.name, "workflow_state", CANCELLED,
                            update_modified=False)
    if stale:
        acted.append(f"backfilled {len(stale)} cancelled document(s)")

    frappe.db.commit()
    frappe.clear_cache()
    print(f"\nDONE — {acted}")
    return {"changed": acted}
