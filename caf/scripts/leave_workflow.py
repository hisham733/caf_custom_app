"""Chunk 6b — the Leave Application approval workflow. MG, 2026-08-13.

Run   : bench --site <site> execute caf.scripts.leave_workflow.plan
        bench --site <site> execute caf.scripts.leave_workflow.apply
Refs  : framework §6.16 (the settled design) · spec §4 · OD-27 · OD-82

THE CHAIN
---------
    1 Draft                    0  Open       employee, or their LA filing for them
    2 Pending Supervisor       0  Open       that employee's OWN leave_approver
    3 Pending HR Manager       0  Open       any HR Manager
    4 Pending Final Approval   0  Open       any HR Manager
    5 Approved                 1  Approved   <- the ledger moves HERE and nowhere else
    6 Rejected by Supervisor   0  Rejected   -> Revise -> Draft
    7 Rejected by HR Manager   0  Rejected   -> Revise -> Draft
    8 Rejected at Final        0  Rejected   -> Revise -> Draft
    9 Cancelled                2  Cancelled

🔴 WHY EACH STATE CARRIES `Update Field: status` — spec §4
Production leaves it blank on all 7 states, so **nothing ever sets `status`** —
yet `leave_application.py` refuses to submit unless status is Approved/Rejected,
and `create_leave_ledger_entry()` returns early unless it is `Approved`. So today
an approver must change the workflow action AND the Status field by hand, and
forgetting the second fails with a message that does not say why.

⚠️ `status` is **permlevel 1**. A workflow Update Field on it writes NOTHING,
silently, for a role without permlevel-1 access. Measured: HR Manager, HR User
and Leave Approver all hold it, so this works — but that is the trap production
fell into and it is why it was checked before building.

🔴 "PENDING FINAL APPROVAL", NOT "PENDING DIRECTOR" — MG, 2026-08-13
`Director` is a **designation**, not a role, and **0 employees hold it**. The
workflow never reads `designation`; states 3 and 4 are both gated on HR Manager,
because in practice the director gives the decision by phone and HR enters it.
Naming the state after a person who does not exist would be a fiction. **No
Director designation is required for any of this to run.**

🔴 REJECTIONS STAY AT docstatus 0, SO "REVISE" IS NOT AN AMEND
A rejected application is a **draft**, not a cancelled document — so Frappe's
cancel-and-amend does not apply at all. The Revise transitions send the SAME
document back to Draft with its history intact (FBR22). Production sets rejected
states to docstatus 1, which locks them and forces a new document.

⚠️ THE ROLE IS THE DOOR, THE HOOK IS THE LOCK
State 2 says "Leave Approver", which is a ROLE — any of the 19. Restricting it to
*that employee's* approver is `caf.caf.overrides.leave_application.has_permission`
(OD-82). Neither half works alone.

Changelog
---------
1.0  2026-08-13  Chunk 6b
"""

import frappe

DOCTYPE = "Leave Application"
NAME = "CAF Leave Approval"
LA, HRM = "Leave Approver", "HR Manager"

# (state, docstatus, status, allow-edit role)
STATES = [
    ("Draft", 0, "Open", LA),
    ("Pending Supervisor", 0, "Open", LA),
    ("Pending HR Manager", 0, "Open", HRM),
    ("Pending Final Approval", 0, "Open", HRM),
    ("Approved", 1, "Approved", HRM),
    ("Rejected by Supervisor", 0, "Rejected", LA),
    ("Rejected by HR Manager", 0, "Rejected", HRM),
    ("Rejected at Final", 0, "Rejected", HRM),
    ("Cancelled", 2, "Cancelled", HRM),
]

# (from, action, to, allowed role)
#
# 🔴 A Workflow Transition row carries exactly ONE role. So an edge that two
# roles may take needs TWO rows. Found by test: the first walk failed with
# `WorkflowTransitionError: Not a valid Workflow Action` because HR Manager does
# not hold `Leave Approver` and therefore could not even START the chain —
# against MG's own practice note, *"in practice HR manager will do all the
# paper work."* Every Leave-Approver edge below is mirrored for HR Manager.
_LA_EDGES = [
    ("Draft", "Submit for Approval", "Pending Supervisor"),
    # state 2 — the role is the door; has_permission is the lock (OD-82)
    ("Pending Supervisor", "Approve", "Pending HR Manager"),
    ("Pending Supervisor", "Reject", "Rejected by Supervisor"),
    # 🔴 Revise — the SAME document goes back to Draft. Not an amend: a rejected
    # application is docstatus 0, so there is nothing to cancel and copy.
    ("Rejected by Supervisor", "Revise", "Draft"),
    ("Rejected by HR Manager", "Revise", "Draft"),
    ("Rejected at Final", "Revise", "Draft"),
]

TRANSITIONS = (
    [(f, a, t, LA) for f, a, t in _LA_EDGES]
    + [(f, a, t, HRM) for f, a, t in _LA_EDGES]     # HR does the paperwork
    + [
        ("Pending HR Manager", "Approve", "Pending Final Approval", HRM),
        ("Pending HR Manager", "Reject", "Rejected by HR Manager", HRM),
        ("Pending Final Approval", "Approve", "Approved", HRM),
        ("Pending Final Approval", "Reject", "Rejected at Final", HRM),
        ("Approved", "Cancel", "Cancelled", HRM),
    ]
)


def ensure_states():
    """`Workflow State` is a master doctype — the rows must exist first."""
    made = []
    for s, _d, _st, _r in STATES:
        if not frappe.db.exists("Workflow State", s):
            doc = frappe.new_doc("Workflow State")
            doc.workflow_state_name = s
            doc.flags.ignore_permissions = True
            doc.insert()
            made.append(s)
    for a in sorted({t[1] for t in TRANSITIONS}):
        if not frappe.db.exists("Workflow Action Master", a):
            doc = frappe.new_doc("Workflow Action Master")
            doc.workflow_action_name = a
            doc.flags.ignore_permissions = True
            doc.insert()
            made.append(a)
    frappe.db.commit()
    return made


def plan():
    """🔴 DRY RUN."""
    exists = frappe.db.exists("Workflow", NAME)
    other = frappe.get_all("Workflow", filters={"document_type": DOCTYPE},
                           fields=["name", "is_active"])
    print(f"CHUNK 6b — {NAME}    🔴 DRY RUN, NOTHING WRITTEN")
    print("=" * 76)
    print(f"   workflow already exists : {bool(exists)}")
    print(f"   other workflows on {DOCTYPE}: {other or 'none'}")
    print(f"\n   {'state':26s} {'ds':>2s} {'status':10s} allow-edit")
    for s, d, st, r in STATES:
        print(f"   {s:26s} {d:>2} {st:10s} {r}")
    print(f"\n   {'from':26s} {'action':20s} {'to':26s} role")
    for f, a, t, r in TRANSITIONS:
        print(f"   {f:26s} {a:20s} {t:26s} {r}")

    missing = [s for s, _d, _st, _r in STATES
               if not frappe.db.exists("Workflow State", s)]
    print(f"\n   Workflow State masters to create : {missing or 'none'}")
    lvl1 = frappe.get_all("Custom DocPerm",
                          filters={"parent": DOCTYPE, "permlevel": 1, "write": 1},
                          pluck="role")
    print(f"   roles with permlevel-1 write on `status` : {lvl1}")
    print(f"      (empty here would mean Update Field writes NOTHING, silently)")
    print(f"\n🔴 Nothing was written.")
    return {"exists": bool(exists), "states": len(STATES),
            "transitions": len(TRANSITIONS)}


def apply():
    made = ensure_states()
    if frappe.db.exists("Workflow", NAME):
        doc = frappe.get_doc("Workflow", NAME)
        doc.set("states", [])
        doc.set("transitions", [])
    else:
        doc = frappe.new_doc("Workflow")
        doc.workflow_name = NAME
    doc.document_type = DOCTYPE
    doc.workflow_state_field = "workflow_state"
    doc.is_active = 1
    doc.send_email_alert = 0
    for s, d, st, r in STATES:
        doc.append("states", {"state": s, "doc_status": d, "allow_edit": r,
                              "update_field": "status", "update_value": st})
    for f, a, t, r in TRANSITIONS:
        doc.append("transitions", {"state": f, "action": a, "next_state": t,
                                   "allowed": r, "allow_self_approval": 1})
    doc.flags.ignore_permissions = True
    doc.save()
    frappe.db.commit()
    print(f"masters created : {made or 'none'}")
    print(f"workflow        : {doc.name}  active={doc.is_active}  "
          f"states={len(doc.states)} transitions={len(doc.transitions)}")
    print(f"⚠️ State 2 is gated on the ROLE `{LA}`. Restricting it to THAT "
          f"employee's approver is the has_permission hook (OD-82) — the "
          f"workflow cannot express it.")
    return {"workflow": doc.name, "states": len(doc.states),
            "transitions": len(doc.transitions)}
