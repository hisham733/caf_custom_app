"""Only the AUTHOR may retract their own feedback — MG's rule, tested.

    bench --site <site> execute caf.tests.workflow_gaps.test_epf_ownership.run

MG found in the desk (2026-08-22) that `too@` could cancel an Employee Performance
Feedback SOMEBODY ELSE wrote (HR-PF-2026-00052). MG's reading, which is the right
one: not really a role problem — a missing OWNERSHIP test.

The rule set:
  · any employee may WRITE feedback (it is a complaint-or-compliment form);
  · the AUTHOR may retract their own — a complaint you regret should be
    withdrawable;
  · HR Manager may cancel anyone's;
  · nobody else.

Safe precisely because EPF carries no weight in the appraisal score, so retracting
one changes no number.

Implemented as two `Custom DocPerm` rows for the Employee role — `if_owner=0`
granting read+create, `if_owner=1` granting write+submit+cancel — because Frappe's
`if_owner` is a ROW-level flag, not a per-action one. That shape is easy to undo by
accident, which is why it is asserted here rather than trusted.
"""

import frappe

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:26s} {'PASS' if ok else 'FAIL'}  {detail}")


def _new_epf(author, about_employee):
    """⚠️ `reviewer` is a Link to EMPLOYEE, not the user's email.

    CAF validates it — *"Reviewer x@y is not an Employee. Feedback must be
    attributed to an employee record, not a user or an email"* — so resolve the
    author's Employee id first. Passing the login here fails in a way that reads
    like a permission problem and is not.
    """
    reviewer = frappe.db.get_value("Employee", {"user_id": author}, "name")
    frappe.set_user(author)
    d = frappe.new_doc("Employee Performance Feedback")
    d.employee = about_employee
    d.feedback = "test feedback — ownership suite"
    if d.meta.has_field("reviewer") and reviewer:
        d.reviewer = reviewer
    d.insert()
    return d.name


def run():
    frappe.set_user("Administrator")
    AUTHOR, OTHER, HRM = ("too@caffood.com", "wawa@caffood.com",
                          "hr.manager.test@caffood.com")
    ABOUT = "HR-EMP-00009"          # Seow Zi Ying
    made = []

    try:
        # ── E1 — an ordinary employee can still WRITE feedback ──────────────
        try:
            name = _new_epf(AUTHOR, ABOUT)
            made.append(name)
            ok, why = True, f"{AUTHOR} created {name}"
        except Exception as e:
            ok, why = False, f"🔴 {frappe.utils.strip_html(str(e))[:120]}"
        check("E1-ANYONE-CAN-WRITE", ok,
              f"{why}. EPF is a complaint-or-compliment form — narrowing cancel "
              f"must not narrow WRITING one, which is the whole point of it")

        if not made:
            raise RuntimeError("cannot continue without a document")
        target = made[0]

        # ── E2 — a DIFFERENT employee cannot cancel it ──────────────────────
        frappe.set_user(OTHER)
        can_other = frappe.has_permission("Employee Performance Feedback",
                                          "cancel", doc=target)
        check("E2-OTHERS-CANNOT-CANCEL", can_other is False,
              f"{OTHER} may cancel {target}? {can_other} — must be False. This is "
              f"exactly what MG hit: `too@` retracting feedback she did not write")

        # ── E3 — the AUTHOR can retract their own ───────────────────────────
        frappe.set_user(AUTHOR)
        can_author = frappe.has_permission("Employee Performance Feedback",
                                           "cancel", doc=target)
        check("E3-AUTHOR-CAN-RETRACT", can_author is True,
              f"{AUTHOR} may cancel their own {target}? {can_author} — a complaint "
              f"you regret has to be withdrawable, and EPF carries no appraisal "
              f"score, so retracting changes no number")

        # ── E4 — HR Manager can cancel anyone's ─────────────────────────────
        frappe.set_user(HRM)
        can_hrm = frappe.has_permission("Employee Performance Feedback",
                                        "cancel", doc=target)
        check("E4-HRM-CANCELS-ANY", can_hrm is True,
              f"HR Manager may cancel {target}? {can_hrm} — somebody must be able "
              f"to remove a feedback whose author has left")

        # ── E5 — the retraction is AUDITED ──────────────────────────────────
        frappe.set_user("Administrator")
        tracked = frappe.db.get_value("DocType", "Employee Performance Feedback",
                                      "track_changes")
        check("E5-RETRACTION-IS-AUDITED", tracked == 1,
              f"track_changes={tracked} on EPF. It was OFF until 2026-08-22 — so a "
              f"retraction left NO record of who withdrew what. An ownership rule "
              f"with no audit trail is half a rule")

    finally:
        frappe.set_user("Administrator")
        for n in made:
            if frappe.db.exists("Employee Performance Feedback", n):
                d = frappe.get_doc("Employee Performance Feedback", n)
                d.flags.ignore_permissions = True
                if d.docstatus == 1:
                    d.cancel()
                frappe.delete_doc("Employee Performance Feedback", n,
                                  ignore_permissions=True, force=True,
                                  delete_permanently=True)
        frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
