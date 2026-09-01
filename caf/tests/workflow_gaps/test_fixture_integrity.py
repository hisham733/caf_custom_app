"""S8 — fixture-integrity gates for the workflow-gaps suites (read-only).

    bench --site development.localhost execute caf.tests.workflow_gaps.test_fixture_integrity.run

Asserts the environment the other workflow-gaps suites rely on. New file only —
nothing existing is touched. Never changes data.

Fixture truths discovered 2026-08-14 (S8 run 1):
- hr.manager.test@ holds only HR Manager (Employee role gone after the prod
  role import) — the appraisal workflow's "Submit for Review" needs an Employee
  role, so S1 uses the SUPERVISOR (mursyid@) for that transition.
- HR-EMP-00013 (mohd@) reports to HR-EMP-00011 (mursyid@) whose leave_approver
  is ALSO mursyid@ — one pure Leave Approver for both roles.
"""

import frappe

from caf.caf.overrides import leave_application
from caf.scripts import leave_workflow
from caf.scripts.naming_series_audit import _gaps

EMP_USER = "mohd@caffood.com"               # HR-EMP-00013, Employee role
EMP_NAME = "HR-EMP-00013"
HRM = "hr.manager.test@caffood.com"         # HR Manager

# 🔴 APPROVER and STRANGER are DERIVED, not typed. Both hardcoded values went
# stale — measured 2026-09-01:
#
#   mursyid@ (HR-EMP-00011)    approves for 0 people and holds only `Employee`.
#                              EMP_NAME's real approver is **too@** (Too Poh Chin,
#                              HR-EMP-00003), who is also who he reports to.
#   production.c.caf@gmail.com is Rohit Kamat (HR-EMP-00023) and holds no
#                              `Leave Approver` role at all, so it could not play
#                              "a pure Leave Approver who is the WRONG one".
#
# ✅ MG confirmed the same day that the DATA is the authority — *"I have already
# imported and corrected all emp.reports_to and emp.leave_approver in this test
# server"* — and the whole active population satisfies
# `leave_approver == reports_to.user_id` with zero exceptions (FBR56).
#
# So the suite reads the org chart instead of remembering a snapshot of it. The
# four assertions this file was failing were all this one cause, and none of them
# was a product defect.
APPROVER = None      # EMP_NAME's own leave approver
STRANGER = None      # a real Leave Approver who is NOT EMP_NAME's


def resolve_fixture_users():
    """Read the two approver identities out of the live org chart."""
    global APPROVER, STRANGER
    APPROVER = frappe.db.get_value("Employee", EMP_NAME, "leave_approver")
    if not APPROVER:
        frappe.throw(f"{EMP_NAME} has no leave_approver — only the two org roots "
                     f"may be blank (FBR50)")

    # Somebody who really does hold the role, really does approve for people, and
    # really is not this employee's approver. Deriving it means the assertion keeps
    # meaning "the wrong approver is refused" however HR reorganises.
    others = {e.leave_approver for e in frappe.get_all(
        "Employee", filters={"status": "Active", "leave_approver": ("!=", "")},
        fields=["leave_approver"]) if e.leave_approver != APPROVER}
    STRANGER = next((u for u in sorted(others)
                     if "Leave Approver" in frappe.get_roles(u)
                     and not {"HR Manager", "HR User"} & set(frappe.get_roles(u))), None)
    if not STRANGER:
        frappe.throw("no second Leave Approver without HR roles — I3-STRANGER "
                     "cannot distinguish 'wrong approver' from 'HR bypass'")
    print(f"fixture users read from the org chart: approver of {EMP_NAME} = "
          f"{APPROVER}; unrelated Leave Approver = {STRANGER}")

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


class _Doc:
    """Minimal stub - has_permission only reads .employee."""

    def __init__(self, employee):
        self.employee = employee
        self.doctype = "Leave Application"


def run():
    resolve_fixture_users()

    # I4 - workflow record matches the builder script
    wf = frappe.db.exists("Workflow", "CAF Leave Approval")
    check("I4-WF", bool(wf), f"workflow exists: {wf}")
    if wf:
        doc = frappe.get_doc("Workflow", wf)
        check("I4-ACTIVE", doc.is_active == 1, f"active={doc.is_active}")
        check("I4-STATES", len(doc.states) == len(leave_workflow.STATES),
              f"states {len(doc.states)} vs {len(leave_workflow.STATES)}")
        check("I4-TRANS", len(doc.transitions) == len(leave_workflow.TRANSITIONS),
              f"transitions {len(doc.transitions)} vs {len(leave_workflow.TRANSITIONS)}")
        check("I4-DOCTYPE", doc.document_type == "Leave Application",
              f"document_type={doc.document_type}")
        acts = {t.action for t in doc.transitions}
        check("I4-ACTIONS", acts >= {"Submit for Approval", "Approve", "Reject",
                                     "Revise", "Cancel"},
              f"actions={sorted(acts)}")

    # I1 - roles of the fixture users
    role_names = ("Employee", "Leave Approver", "HR Manager", "HR User",
                  "System Manager")
    exp = {
        EMP_USER: ["Employee"],
        APPROVER: ["Leave Approver", "Employee"],
        HRM: ["HR Manager"],
        STRANGER: ["Leave Approver", "Employee"],
    }
    for u, want in exp.items():
        got = sorted(r for r in frappe.get_roles(u) if r in role_names)
        check("I1-" + u.split("@")[0], all(w in got for w in want),
              f"{u}: {got}")
    hr_roles_in_la = any(r in ("HR Manager", "HR User")
                         for r in frappe.get_roles(APPROVER) if r in role_names)
    check("I1-APPROVER-PURE", not hr_roles_in_la,
          f"{APPROVER} must NOT hold HR roles (the hook test needs a pure LA)")

    # I2 - naming counters zero-gap
    gaps = _gaps()
    check("I2-GAPS", not gaps, f"naming gaps: {gaps[:3]}")

    # I3 - OD-82 routing: owner / approver / HRM / stranger
    emp = frappe.db.get_value("Employee", {"user_id": EMP_USER}, "name")
    la_value = frappe.db.get_value("Employee", emp, "leave_approver")
    check("I3-EMP", emp == EMP_NAME, f"employee for {EMP_USER}: {emp}")
    check("I3-LA-LINK", la_value == APPROVER,
          f"leave_approver of {emp} = {la_value} (want {APPROVER})")

    own = leave_application.has_permission(_Doc(emp), ptype="write",
                                           user=EMP_USER)
    ok_appr = leave_application.has_permission(_Doc(emp), ptype="write",
                                               user=APPROVER)
    hrm_any = leave_application.has_permission(_Doc(emp), ptype="write",
                                               user=HRM)
    stranger = leave_application.has_permission(_Doc(emp), ptype="write",
                                                user=STRANGER)
    check("I3-OWN", own is True, f"owner may handle own leave: {own}")
    check("I3-APPROVER", ok_appr is True,
          f"{APPROVER} may handle {emp}: {ok_appr}")
    check("I3-HRM", hrm_any is True, f"HR Manager bypasses: {hrm_any}")
    check("I3-STRANGER", stranger is False,
          f"{STRANGER} (pure LA, wrong employee) refused: {stranger}")

    print()
    failed = 0
    for tid, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL':4s} {tid:18s} {detail}")
        failed += 0 if ok else 1
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} passed")
    return {"passed": len(RESULTS) - failed, "total": len(RESULTS)}
