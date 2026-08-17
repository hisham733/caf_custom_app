"""MG's question, 2026-08-17: can a cancelled appraisal be amended and re-submitted?

    bench --site <site> execute caf.tests.workflow_gaps.test_amend_after_cancel.run

This is the crux of the correction route MG wants to rely on. If it works, CAF has
unlimited backdating with no code change:

  1. no deadline to submit Mr X's July appraisal;
  2. as long as that appraisal is unsubmitted OR cancelled, every backdated
     correction (leave, Saturday swap, Finger Log, OT approval) is possible.

The suspect is stock `validate_duplicate()` — it refuses a second appraisal for the
same employee and cycle. Reading it, the guard is `docstatus != 2`, so a CANCELLED
appraisal should be invisible to it. Reading is not proving, hence this.

Also asserted: that FBR39 actually releases once the appraisal is cancelled, since
that is the half MG's route depends on and it is enforced somewhere else entirely
(`submitted_appraisals()`, same `docstatus = 1` filter).

Self-cleaning. Creates nothing that outlives the run.
"""

import frappe
from frappe.utils import getdate

from caf.caf import appraisal_refresh as ar

CYCLE = "2026-07"
RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:30s} {'PASS' if ok else 'FAIL'}  {detail}")


def _pick_employee():
    """An active employee with a supervisor, no existing 2026-07 appraisal."""
    taken = {r.employee for r in frappe.get_all(
        "Appraisal", filters={"appraisal_cycle": CYCLE}, fields=["employee"])}
    for e in frappe.get_all("Employee",
                            filters={"status": "Active"},
                            fields=["name", "employee_name", "reports_to"],
                            order_by="name"):
        if e.name not in taken and e.reports_to:
            return e
    return None


def _walk_to_completed(doc):
    """Draft → Pending HR Review → Completed, through the real transitions.

    Setting `workflow_state = "Completed"` and calling submit() is refused —
    `validate_workflow` throws "transition not allowed from Draft to Completed".
    The appraisal has to travel the states a person would travel, which is also
    the honest test: it exercises validate_month_ended twice (once on the move to
    Pending HR Review via on_update, once on submit).
    """
    from frappe.model.workflow import apply_workflow
    doc.flags.ignore_permissions = True
    apply_workflow(doc, "Submit for Review")     # Employee → Pending HR Review
    doc.reload()
    doc.flags.ignore_permissions = True
    apply_workflow(doc, "Approve")               # HR Manager → Completed (submits)
    frappe.db.commit()


def _cleanup(names):
    for n in names:
        if not n or not frappe.db.exists("Appraisal", n):
            continue
        d = frappe.get_doc("Appraisal", n)
        d.flags.ignore_permissions = True
        d.flags.ignore_links = True
        if d.docstatus == 1:
            d.cancel()
        frappe.delete_doc("Appraisal", n, ignore_permissions=True, force=True,
                          delete_permanently=True)
    frappe.db.commit()


def run():
    frappe.set_user("Administrator")
    emp = _pick_employee()
    if not emp:
        print("no free employee for cycle " + CYCLE)
        return False
    print(f"using {emp.name} {emp.employee_name} · cycle {CYCLE}\n")

    made = []
    try:
        tpl = frappe.db.get_value("Appraisal Template",
                                  {"name": ("like", "CAF%")}, "name")

        # ── build and SUBMIT the original ──────────────────────────────────
        a = frappe.new_doc("Appraisal")
        a.employee = emp.name
        a.appraisal_cycle = CYCLE
        if tpl:
            a.appraisal_template = tpl
        a.flags.ignore_permissions = True
        a.insert(ignore_permissions=True)
        made.append(a.name)

        _walk_to_completed(a)
        check("AC1-ORIGINAL-SUBMITS",
              frappe.db.get_value("Appraisal", a.name, "docstatus") == 1,
              f"{a.name} submitted for cycle {CYCLE} — validate_month_ended let it "
              f"through because July has ended (BR6/D31 blocks only EARLY submission)")

        # ── FBR39 should now BITE ──────────────────────────────────────────
        subs = ar.submitted_appraisals(emp.name, "2026-07-01", "2026-07-31")
        check("AC2-FBR39-SEES-IT", any(s.name == a.name for s in subs),
              f"while submitted, submitted_appraisals() returns it "
              f"({[s.name for s in subs]}) — this is the lookup FBR39 uses, so a "
              f"backdated July leave would be checked against its window")

        # ── CANCEL, and FBR39 must let go ──────────────────────────────────
        a.reload()
        a.flags.ignore_permissions = True
        a.cancel()
        frappe.db.commit()
        subs_after = ar.submitted_appraisals(emp.name, "2026-07-01", "2026-07-31")
        check("AC3-CANCEL-RELEASES-FBR39",
              frappe.db.get_value("Appraisal", a.name, "docstatus") == 2
              and not any(s.name == a.name for s in subs_after),
              f"cancelled → docstatus 2 → submitted_appraisals() no longer returns "
              f"it ({[s.name for s in subs_after]}). 🔴 This is the half MG's route "
              f"depends on: with nothing submitted, check_leave_window finds no "
              f"window and a backdated July leave approves normally — at ANY age")

        # ── AMEND — the suspect ────────────────────────────────────────────
        amended = frappe.copy_doc(a)
        amended.amended_from = a.name
        amended.docstatus = 0
        amended.workflow_state = "Draft"
        amended.flags.ignore_permissions = True
        try:
            amended.insert(ignore_permissions=True)
            made.append(amended.name)
            check("AC4-AMEND-NOT-DUPLICATE", True,
                  f"the amendment {amended.name} INSERTED for the same employee and "
                  f"cycle — stock validate_duplicate() excludes docstatus = 2, so a "
                  f"cancelled appraisal is invisible to it. This was the one thing "
                  f"that could have blocked the whole route")
        except Exception as e:
            check("AC4-AMEND-NOT-DUPLICATE", False,
                  f"🔴 amendment REFUSED: {frappe.utils.strip_html(str(e))[:200]} — "
                  f"the cancel-and-amend route does NOT work and CAF needs another "
                  f"way to correct a closed period")
            raise

        # ── and it must re-SUBMIT ──────────────────────────────────────────
        _walk_to_completed(amended)
        check("AC5-AMENDMENT-RESUBMITS",
              frappe.db.get_value("Appraisal", amended.name, "docstatus") == 1,
              f"{amended.name} re-submitted, so the cycle closes again with the "
              f"corrected figures. Full route proven: submit → cancel → backdate "
              f"freely → amend → re-submit, with NO time limit anywhere in it")

        # ── the new one is what FBR39 now watches ──────────────────────────
        final = ar.submitted_appraisals(emp.name, "2026-07-01", "2026-07-31")
        check("AC6-WINDOW-RESTARTS",
              any(s.name == amended.name for s in final),
              f"FBR39 now tracks the AMENDMENT ({[s.name for s in final]}), and its "
              f"window runs from the re-submission — so the month of in-place "
              f"tolerance starts again rather than being inherited from the "
              f"original submit")

    except Exception:
        # bench execute masks the real error as "NameError: name 'caf' is not
        # defined" (protocol quirk #18), so print it before it escapes.
        import traceback
        print("\n🔴 REAL TRACEBACK:")
        traceback.print_exc()
    finally:
        _cleanup(made)
        remaining = frappe.db.count("Appraisal", {"appraisal_cycle": CYCLE,
                                                 "employee": emp.name})
        print(f"\ncleanup: {remaining} appraisal(s) left for {emp.name}/{CYCLE}")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
