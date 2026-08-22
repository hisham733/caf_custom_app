"""A cancelled appraisal must not still read "Completed".

    bench --site <site> execute caf.tests.workflow_gaps.test_appraisal_cancel_state.run

MG, manual test Pass C5: after cancelling `HR-APR-2026-00309` the form still read
*Completed*, and the list showed it in green beside its own amendment — *"if status
= Completed (green text) may be confusing"*.

Worse than confusing. `workflow_state` is what the list view, the appraisal
dashboard and the supervisor page all read; `docstatus` appears on none of them. So
a cancelled document was telling every surface the opposite of the truth, and
nothing on screen could correct it.

Three cancel routes exist and they do NOT share a code path — the workflow Action
menu, the standard Cancel button, and `doc.cancel()` from code. The workflow
transition only covers the first, which is why `on_cancel` exists and why this
suite cancels the way CODE does: that is the path a transition can never catch.
"""

import frappe

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:30s} {'PASS' if ok else 'FAIL'}  {detail}")


def run():
    frappe.set_user("Administrator")
    made = []
    try:
        # ── AC1 — the workflow can express a cancelled appraisal at all ─────
        wf = frappe.get_doc("Workflow", "CAF Appraisal Workflow")
        by_status = {s.state: str(s.doc_status) for s in wf.states}
        check("AC1-WORKFLOW-HAS-CANCELLED",
              by_status.get("Cancelled") == "2",
              f"the workflow carries a Cancelled state at doc_status 2 "
              f"({by_status}). Without one, cancel has nowhere to land and the "
              f"old state simply stays — which is the whole bug")

        # ── AC2 — and the fixture carries it, so a fresh install gets it ────
        import json
        import os
        base = frappe.get_app_path("caf", "fixtures")
        states = json.load(open(os.path.join(base, "workflow_state.json")))
        actions = json.load(open(os.path.join(base, "workflow_action_master.json")))
        names = {s.get("name") for s in states}
        acts = {a.get("name") for a in actions}
        check("AC2-FIXTURE-SHIPS-IT",
              "Cancelled" in names and "Cancel" in acts,
              f"the Workflow State and Action Master fixtures carry Cancelled/Cancel "
              f"({sorted(names)} · {sorted(acts)}). ⚠️ Those filter lists in hooks.py "
              f"are HAND-MAINTAINED and the export does not check them against the "
              f"workflow — the first export missed both, which would have shipped a "
              f"workflow referencing states that do not travel (the D71 trap)")

        # ── AC3 — cancelling FROM CODE still fixes the state ────────────────
        emp = frappe.db.get_value("Employee", {"status": "Active",
                                               "reports_to": ("!=", "")}, "name")
        cycle = frappe.db.get_value("Appraisal Cycle", {"name": "2026-06"}, "name")
        a = frappe.new_doc("Appraisal")
        a.employee = emp
        a.appraisal_cycle = cycle
        a.flags.ignore_permissions = True
        a.insert(ignore_permissions=True)
        made.append(a.name)

        from frappe.model.workflow import apply_workflow
        a.flags.ignore_permissions = True
        apply_workflow(a, "Submit for Review")
        a.reload()
        a.flags.ignore_permissions = True
        apply_workflow(a, "Approve")
        a.reload()
        submitted_state = a.workflow_state

        a.flags.ignore_permissions = True
        a.cancel()                       # ← the CODE path, not the Actions menu
        a.reload()

        check("AC3-CODE-CANCEL-SETS-STATE",
              a.docstatus == 2 and a.workflow_state == "Cancelled",
              f"cancelled from code: docstatus={a.docstatus} "
              f"workflow_state={a.workflow_state!r} (was {submitted_state!r}). "
              f"🔴 This is the path the workflow TRANSITION cannot catch — Frappe's "
              f"cancel sets docstatus directly and only apply_workflow moves the "
              f"state, so on_cancel is what makes all three routes agree")

        # ── AC4 — nothing anywhere is cancelled-but-claiming-otherwise ──────
        stale = frappe.get_all("Appraisal",
                               filters={"docstatus": 2,
                                        "workflow_state": ("!=", "Cancelled")},
                               fields=["name", "workflow_state"])
        check("AC4-NO-LYING-DOCUMENTS", not stale,
              f"no cancelled appraisal claims another state ({len(stale)} found). "
              f"Three did before this — including MG's HR-APR-2026-00309, showing "
              f"Completed in green next to its own live amendment"
              if not stale else f"🔴 still lying: {stale}")

    finally:
        frappe.set_user("Administrator")
        for n in made:
            if frappe.db.exists("Appraisal", n):
                d = frappe.get_doc("Appraisal", n)
                d.flags.ignore_permissions = True
                if d.docstatus == 1:
                    d.cancel()
                frappe.delete_doc("Appraisal", n, ignore_permissions=True,
                                  force=True, delete_permanently=True)
        frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
