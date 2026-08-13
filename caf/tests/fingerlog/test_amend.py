"""AM-* — amendment, per doctype, AS A ROLE. The largest hole in the matrix.

    bench --site <site> execute caf.tests.fingerlog.test_amend.run

Raised by MG 2026-08-13: *"role based testing on workflow by doctype
(finger_log / appraisal / swap) with late submission / amendment / hook on
change — this test written?"* The honest answer was **no, for three of five**.

WHY AMENDMENT SPECIFICALLY
--------------------------
Amend is how HR corrects a record that is already submitted — the sanctioned
route **OD-48 chose over editing in place**. The `before_update_after_submit`
guards (OD-61, OD-62) sit exactly on that path. And **§C1: a suite running as
Administrator passes identically against a broken permission model.** So the one
route HR is meant to use for corrections was the one route never exercised by
the person who would use it.

🔴 TWO DEFECTS FOUND BEFORE A SINGLE TEST WAS WRITTEN, by reading the permission
tables instead of assuming them:

    Finger Log   HR Manager  amend = 0     System Manager  amend = 0
    Appraisal    HR Manager  cancel = 0, amend = 0

**Nobody can amend a Finger Log** — yet OD-48's "Path 2: cancel + amend" is the
documented correction route, and spec §7 repeats it. E5 has always passed
because it sets `flags.ignore_permissions = True`, which is precisely the blind
spot §C1 describes. And an **HR Manager cannot amend an Appraisal**; only HR
User and System Manager can.

⚠️ **These tests assert what IS TRUE TODAY, and say loudly where that
contradicts the design.** Asserting the desired behaviour would paint the matrix
red for a decision nobody has made yet, and a matrix that is red on purpose is
one nobody reads (the same call made for E7, which was then held out until the
fix landed). See **OD-81**. When MG grants amend, AM1 flips to asserting success
and this note comes out.

FIXTURES — 2026-09-22 .. 09-24, measured empty before use
----------------------------------------------------------
September, not June. June is crowded: Chunk R owns 06-16/18, the swap guard owns
06-08..12, the dashboard owns 06-12 and the alt-Saturday suites own the June
Saturdays. **Employee HR-EMP-00075 is shared with Chunk R deliberately** — it is
the one active employee with a user carrying the plain `Employee` role, which
AM6 needs — and the collision is avoided by DATE, which is §F4d's rule.
"""

import frappe
from frappe.utils import getdate

EMP = "HR-EMP-00075"                          # Seriramulu — Active, 8am Schedule
EMP_USER = "seriramulu@caffood.com"           # role: Employee only
HRM = "hr.manager.test@caffood.com"           # role: HR Manager
HRU = "hr.user.test@caffood.com"              # role: HR User

D_LOG = "2026-09-22"                          # Tue
D_LEAVE = "2026-09-23"                        # Wed
D_SHIFT = "2026-09-24"                        # Thu
# ⚠️ 2026-07, not 2026-09. CAF refuses to submit an appraisal for a cycle that
# has not ENDED — *"the attendance and overtime data would be incomplete"* — and
# September has not. July has, and it is not Chunk 5's cycle (2026-06), so the
# two suites cannot collide on the same document (§F6).
CYCLE = "2026-07"
TEMPLATE = "CAF Monthly Appraisal"
LEAVE_TYPE = "Emergency"

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def as_user(user, fn, *a, **kw):
    """Run `fn` as `user` and ALWAYS come back. Returns (result, refusal).

    🔴 `refusal` is the EXCEPTION TYPE NAME, never `str(e)` — and that is not a
    style choice. `str(frappe.PermissionError)` is frequently the **empty
    string**: the human text goes through `frappe.throw`'s message/title rather
    than the exception args. The first version of this helper returned
    `str(e)`, so four assertions of the form `bool(err)` read False against
    operations that HAD been correctly refused, and the suite reported that a
    plain Employee could cancel a Finger Log. That is PROTOCOL §E5's shape —
    *the message is the part that silently evaluates false* — reproduced inside
    the test helper written to avoid it.

    §C1b — the restore is in a `finally`: a suite that exits still switched
    leaves every later suite in the process running as somebody else.
    """
    before = frappe.session.user
    try:
        frappe.set_user(user)
        return fn(*a, **kw), None
    except Exception as e:
        msg = frappe.utils.strip_html(str(e) or "").strip()
        return None, f"{type(e).__name__}{': ' + msg[:70] if msg else ''}"
    finally:
        frappe.set_user(before)


def can(user, doctype, ptype):
    """What the permission tables actually grant. Read, never assumed."""
    roles = {r.role for r in frappe.get_all(
        "Has Role", filters={"parent": user, "parenttype": "User"},
        fields=["role"])}
    rows = frappe.get_all("Custom DocPerm", filters={"parent": doctype},
                          fields=["role", ptype])
    if not rows:
        rows = frappe.get_all("DocPerm", filters={"parent": doctype},
                              fields=["role", ptype])
    return any(r.get(ptype) for r in rows if r.role in roles)


def amend(doctype, name):
    """The real amend flow: cancel, copy, point at the original, insert."""
    doc = frappe.get_doc(doctype, name)
    if doc.docstatus == 1:
        doc.reload()
        doc.cancel()
    new = frappe.copy_doc(doc)
    new.amended_from = doc.name
    new.insert()
    return new


def cleanup():
    """Scoped to this suite's dates and employee. Runs FIRST (§F4)."""
    for dt, filt in (
            ("Attendance", {"employee": EMP, "attendance_date":
                            ("in", [D_LOG, D_LEAVE, D_SHIFT])}),
            ("Finger Log", {"employee": EMP, "work_date": ("in", [D_LOG])}),
            ("Leave Application", {"employee": EMP, "from_date": D_LEAVE}),
            ("Shift Assignment", {"employee": EMP, "start_date": D_SHIFT}),
            ("Appraisal", {"employee": EMP, "appraisal_cycle": CYCLE})):
        for r in frappe.get_all(dt, filters=filt, fields=["name", "docstatus"]):
            doc = frappe.get_doc(dt, r.name)
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            if doc.docstatus == 1:
                doc.reload()
                doc.cancel()
            frappe.delete_doc(dt, r.name, ignore_permissions=True, force=True)
    frappe.db.commit()


def make_log(day):
    doc = frappe.new_doc("Finger Log")
    doc.employee = EMP
    # ⚠️ Mandatory, and NOT fetched on a server-side insert — the desk form's
    # fetch_from populates it in the browser only (§E11).
    doc.employee_name = frappe.db.get_value("Employee", EMP, "employee_name")
    doc.work_date = day
    doc.time_in, doc.out = "08:00:00", "16:30:00"
    doc.set("break", "12:00:00")
    doc.resume = "13:00:00"
    doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def run():
    frappe.set_user("Administrator")
    cleanup()

    try:
        # ═══════════════════════════════════════════════ AM1 — Finger Log
        log = make_log(D_LOG)
        amend_perm = can(HRM, "Finger Log", "amend")
        cancel_perm = can(HRM, "Finger Log", "cancel")

        _r, err_cancel = as_user(HRM, lambda: (
            frappe.get_doc("Finger Log", log.name).cancel()))
        state = frappe.db.get_value("Finger Log", log.name, "docstatus")

        _r2, err_amend = as_user(HRM, amend, "Finger Log", log.name)

        check("AM1-CANCEL", cancel_perm and state == 2 and not err_cancel,
              f"HR Manager CAN cancel a submitted Finger Log without "
              f"`ignore_permissions` — docstatus is now {state}. This half of "
              f"OD-48's Path 2 works")

        # 🔴 The interesting one, and NOT what the permission table predicts.
        has_perm = frappe.has_permission("Finger Log", "amend", user=HRM)
        amended_ok = _r2 is not None and not err_amend
        check("AM1-AMEND", not amend_perm and not has_perm and amended_ok,
              f"🔴 **`amend` IS NOT ENFORCED SERVER-SIDE.** `amend = 0` for HR "
              f"Manager and System Manager, and `has_permission(..., 'amend')` "
              f"returns {has_perm} — yet the amend SUCCEEDED and stored "
              f"`amended_from`. `insert()` checks **create**, not amend. So "
              f"`amend` is a DISPLAY property: the desk hides the button, a "
              f"server-side insert walks straight through. Third of the family "
              f"after `read_only` (§C4b) and workflow `allow_edit` (§C4). "
              f"⚠️ OD-48's Path 2 therefore works — but not because it is "
              f"permitted, and anyone holding `create` + `cancel` can do it. "
              f"OD-81")

        # ── AM1-CASCADE 🔴 MG's question, and the one that matters most ──────
        # *"After finger_log.doc is amended, does save or submission after the
        # amendment trigger hooks or verification so that other linked doctypes
        # act accordingly?"*
        #
        # An amend is THREE lifecycle events, not one, and each fires its own
        # hooks:
        #     original.cancel()   -> on_cancel  -> cancels the Attendance
        #     amended.insert()    -> validate   -> (draft; nothing downstream)
        #     amended.submit()    -> before_submit (the roster gate)
        #                         -> on_submit  -> create_attendance()
        #
        # So the day must end up with exactly ONE live Attendance again — the
        # cancelled one plus a fresh one. If `create_attendance` collided with
        # the cancelled row instead, the day would end up with NO live verdict,
        # which is OD-60's failure shape on a different path.
        cleanup()
        log_c = make_log(D_LOG)
        att_before = frappe.get_all("Attendance",
                                    filters={"employee": EMP,
                                             "attendance_date": D_LOG},
                                    fields=["name", "docstatus", "status"])
        amended, err_c = as_user(HRM, amend, "Finger Log", log_c.name)
        att_mid = frappe.get_all("Attendance",
                                 filters={"employee": EMP,
                                          "attendance_date": D_LOG, "docstatus": 1},
                                 fields=["name"])
        sub_err = None
        if amended:
            amended.reload()
            _s, sub_err = as_user(HRM, lambda: amended.submit())
        att_after = frappe.get_all("Attendance",
                                   filters={"employee": EMP,
                                            "attendance_date": D_LOG, "docstatus": 1},
                                   fields=["name", "status"])
        live_before = [a for a in att_before if a.docstatus == 1]

        check("AM1-CASCADE",
              len(live_before) == 1 and len(att_mid) == 0
              and len(att_after) == 1 and not sub_err
              and att_after[0].name != live_before[0].name,
              f"the amend cascades end to end, and it is THREE lifecycle events: "
              f"cancelling the original ran `on_cancel` and took the Attendance "
              f"down ({len(live_before)} live ➜ {len(att_mid)}); submitting the "
              f"amended copy ran `on_submit` ➜ `create_attendance()` and put a "
              f"NEW one up ({len(att_after)}, {att_after[0].status if att_after else '—'}). "
              f"The day is never left without a verdict, and the row is a "
              f"different document — not the cancelled one revived"
              if att_after else
              f"🔴 the day has NO live Attendance after the amend "
              f"({len(live_before)} ➜ {len(att_mid)} ➜ {len(att_after)}). "
              f"submit error: {sub_err}. That is OD-60's failure shape on the "
              f"amend path")

        cleanup()

        # ═══════════════════════════════════════════════ AM2 — Leave Application
        la = frappe.new_doc("Leave Application")
        la.employee = EMP
        la.leave_type = LEAVE_TYPE
        la.from_date = la.to_date = D_LEAVE
        la.status = "Approved"
        la.flags.ignore_permissions = True
        la.insert()
        la.submit()
        days_before = la.total_leave_days

        # ⚠️ AM4-WORKFLOW's finding GENERALISES, and Chunk 6b proved it the hard
        # way: the moment a workflow was attached to Leave Application, this
        # assertion went red with `WorkflowPermissionError: Draft to Approved`.
        # `copy_doc` carries `workflow_state` into the new draft on EVERY
        # workflow-driven doctype, not just Appraisal. Reset it, exactly as the
        # desk's own Amend button does.
        def amend_la():
            d = frappe.get_doc("Leave Application", la.name)
            if d.docstatus == 1:
                d.reload()
                d.cancel()
            n = frappe.copy_doc(d)
            n.amended_from = d.name
            n.workflow_state = "Draft"
            n.insert()
            return n

        new_la, err = as_user(HRM, amend_la)
        ledger = 0
        if new_la:
            # 🔴 The amended copy must be WALKED through the workflow, not jumped.
            # Setting `workflow_state = "Approved"` and submitting is refused —
            # `WorkflowPermissionError: transition not allowed from Draft to
            # Approved`, because Frappe validates the EDGE, and Draft's only edge
            # is "Submit for Approval". This is the first test to walk the whole
            # Chunk 6b chain, and it is also how `status` gets set: each state's
            # Update Field writes it, which is the thing production never
            # configured (spec §4).
            from frappe.model.workflow import apply_workflow

            def walk():
                d = frappe.get_doc("Leave Application", new_la.name)
                for action in ("Submit for Approval", "Approve", "Approve",
                               "Approve"):
                    d = apply_workflow(d, action)
                return d

            walked, serr = as_user(HRM, walk)
            err = err or serr
            if walked:
                new_la = frappe.get_doc("Leave Application", new_la.name)
            ledger = sum(float(r.leaves or 0) for r in frappe.get_all(
                "Leave Ledger Entry",
                filters={"transaction_name": new_la.name, "docstatus": 1},
                fields=["leaves"]))

        check("AM2", bool(new_la) and not err
              and float(new_la.total_leave_days) == float(days_before)
              and abs(ledger + float(days_before)) < 0.01,
              f"HR Manager amended a submitted Leave Application and walked the "
              f"WHOLE Chunk 6b chain as themselves — Draft ➜ Supervisor ➜ HR "
              f"Manager ➜ Final ➜ Approved. {days_before} day(s) carried across "
              f"and the ledger followed ({ledger}). ✅ And `status` reads "
              f"{frappe.db.get_value('Leave Application', new_la.name, 'status')!r} "
              f"— **set by the workflow's Update Field, not by hand**, which is "
              f"the thing production never configured (spec §4) and the reason "
              f"the ledger moved at all"
              if new_la else f"🔴 amend failed: {err}")

        cleanup()

        # ═══════════════════════════════════════════════ AM3 — Shift Assignment
        sa = frappe.new_doc("Shift Assignment")
        sa.employee = EMP
        sa.shift_type = "8am no OT no Sat"
        sa.start_date = sa.end_date = D_SHIFT
        sa.docstatus = 0
        sa.flags.ignore_permissions = True
        sa.insert()
        sa.submit()

        from caf.caf.shift_resolution import resolve_day_type
        before_type, _s = resolve_day_type(EMP, D_SHIFT)

        new_sa, err3 = as_user(HRM, amend, "Shift Assignment", sa.name)
        after_type = None
        partner = None
        if new_sa:
            new_sa.reload()
            _s, serr = as_user(HRM, lambda: new_sa.submit())
            err3 = err3 or serr
            after_type, _s = resolve_day_type(EMP, D_SHIFT)
            partner = new_sa.get("caf_swap_partner")

        check("AM3", bool(new_sa) and not err3 and after_type == before_type
              and not partner,
              f"HR Manager amended a submitted Shift Assignment: the day still "
              f"resolves to {after_type} (was {before_type}), and the amended "
              f"copy carries NO `caf_swap_partner` — a copied pairing would "
              f"point at a cancelled row and manufacture the half-done state "
              f"`half_done_swaps()` exists to find"
              if new_sa else f"🔴 amend failed: {err3}")

        cleanup()

        # ═══════════════════════════════════════════════ AM4 — Appraisal
        ap = frappe.new_doc("Appraisal")
        ap.employee = EMP
        ap.appraisal_cycle = CYCLE
        ap.appraisal_template = TEMPLATE
        ap.flags.caf_skip_supervisor_check = True
        ap.flags.ignore_permissions = True
        ap.insert()
        ap.flags.caf_skip_supervisor_check = True
        ap.submit()

        # ✅ FIXED 2026-08-13 (OD-81b, MG chose B1): HR Manager was granted
        # `cancel` + `amend`. That alone is sufficient, because CAF's own
        # `has_permission` hook already returns True for `is_hr_manager` — the
        # DocPerm row was the only thing in the way.
        # ⚠️ Applied through `update_permission_property`, NOT by hand: a Custom
        # DocPerm REPLACES DocPerm for the whole doctype (§C-bis), so a hand-made
        # row would have deleted Employee, HR User and System Manager along with
        # it. `scripts/appraisal_amend_perm.py` asserts nobody lost anything.
        hrm_amend = can(HRM, "Appraisal", "amend")
        hrm_doc = frappe.has_permission("Appraisal", "amend", doc=ap.name,
                                        user=HRM)
        naive, err_hrm = as_user(HRM, amend, "Appraisal", ap.name)

        check("AM4-PERM",
              hrm_amend and hrm_doc and not naive
              and not str(err_hrm).startswith("PermissionError"),
              f"✅ OD-81b worked: `amend` is now True at doctype level "
              f"({hrm_amend}) AND at document level ({hrm_doc}), and the "
              f"refusal is **no longer a PermissionError** — it is "
              f"{err_hrm}. Both permission gates are open")

        # ── AM4-WORKFLOW 🔴 the THIRD gate, revealed only once the first two opened
        # `frappe.copy_doc` carries `workflow_state = "Completed"` from the
        # original into the new DRAFT, and Frappe then refuses the implied
        # Draft ➜ Completed transition. The desk's own Amend button resets the
        # state; a server-side amend must do it too, or every appraisal
        # correction dies here.
        wf_field = frappe.get_meta("Appraisal").get_field("workflow_state")
        wf = frappe.db.get_value("Workflow", {"document_type": "Appraisal",
                                              "is_active": 1}, "name")
        first_state = frappe.db.get_value(
            "Workflow Document State", {"parent": wf}, "state",
            order_by="idx asc") if wf else None

        def amend_reset():
            d = frappe.get_doc("Appraisal", ap.name)
            if d.docstatus == 1:
                d.reload()
                d.cancel()
            n = frappe.copy_doc(d)
            n.amended_from = d.name
            n.workflow_state = first_state          # <- the missing step
            n.flags.caf_skip_supervisor_check = True
            n.insert()
            return n

        new_ap, err4 = as_user(HRM, amend_reset)
        check("AM4-WORKFLOW",
              bool(err_hrm) and "Workflow" in str(err_hrm)
              and bool(new_ap) and not err4,
              f"🔴 a THIRD gate, and it only became visible once the permission "
              f"gates opened: `copy_doc` copies `workflow_state = 'Completed'` "
              f"into a DRAFT (`no_copy` on that field is "
              f"{getattr(wf_field, 'no_copy', '?')}), so Frappe refuses the "
              f"implied transition — {err_hrm}. Resetting it to the workflow's "
              f"first state ({first_state!r}) lets the amend through: "
              f"{new_ap.name if new_ap else '— ' + str(err4)}. **A server-side "
              f"amend of any workflow-driven doctype must reset the state**, or "
              f"every correction dies here")

        guard_err = ""
        if new_ap:
            # ⚠️ The value written AFTER submit must DIFFER from the stored one.
            # The first version wrote "TAMPERED" both before and after, so the
            # post-submit write was a no-op: `before_update_after_submit`
            # compares old against new, saw no change, and refused nothing. The
            # test then read that silence as "the guard held". Submit clean,
            # then change it — the difference is the whole test.
            def tamper():
                d = frappe.get_doc("Appraisal", new_ap.name)
                d.flags.caf_skip_supervisor_check = True
                d.submit()
                d.reload()
                for row in d.appraisal_kra:
                    row.caf_date_cell = "TAMPERED"
                    break
                d.save()
            _t, guard_err = as_user(HRM, tamper)

        # 🔴 HR User HOLDS `amend` on Appraisal (DocPerm r1 w1 c1 s1 x1 a1, and
        # has_permission returns True for all six). The refusal therefore does
        # NOT come from Frappe — it comes from CAF's own controller. That is the
        # finding: amend is blocked by the supervisor check, and HR correcting a
        # submitted appraisal is exactly what amend exists for.
        hru_all = all(frappe.has_permission("Appraisal", p, user=HRU)
                      for p in ("read", "write", "create", "submit", "cancel",
                                "amend"))
        # 🔴 TWO DIFFERENT GATES BLOCK TWO DIFFERENT ROLES, and that is the point.
        #   HR Manager  passes CAF's has_permission hook (is_hr_manager -> True)
        #               and is stopped by DocPerm  (cancel = 0, amend = 0)
        #   HR User     passes DocPerm (cancel = 1, amend = 1)
        #               and is stopped by CAF's hook (may_appraise: not the
        #               employee's supervisor)
        # ⚠️ `has_permission(dt, ptype)` WITHOUT a doc checks only the doctype
        # level, which is why HR User reads True on all six and still fails —
        # the hook only runs when a document is passed.
        doc_lvl = frappe.has_permission("Appraisal", "amend", doc=ap.name,
                                        user=HRU)
        # 🔴 §F1 / §E2 — the tamper above CANNOT have proved anything, and saying
        # so is the point. An API-created Appraisal has **zero KRA rows**: stock's
        # `set_kras_and_rating_criteria()` is whitelisted and form-called, so it
        # never runs on a server-side insert. The tamper loop therefore iterates
        # nothing and `save()` succeeds trivially — a green light for a guard that
        # was never touched, which is the W3 trap exactly. The KRA count is
        # asserted so the vacuum is visible instead of silent.
        kra_rows = len(frappe.get_all("Appraisal KRA",
                                      filters={"parent": new_ap.name}) or []) \
            if new_ap else 0
        check("AM4-GUARD",
              hru_all and not doc_lvl and kra_rows > 0 and bool(guard_err),
              f"⚠️ HR User still reads True on all six at DOCTYPE level "
              f"({hru_all}) and False at DOCUMENT level ({doc_lvl}) — CAF's "
              f"`has_permission` hook still refuses anyone who is not that "
              f"employee's supervisor, correct and deliberately unchanged by "
              f"OD-81b. ✅ And **OD-61's guard SURVIVES the amend**: the amended "
              f"copy carries {kra_rows} KRA rows (copy_doc brings them across), "
              f"and a typed change to an auto-filled cell on it is still "
              f"refused — {guard_err}. The guard follows the document, not the "
              f"original. ⚠️ The row count is asserted because a copy with zero "
              f"rows would make this pass vacuously — the W3 trap")

        cleanup()

        # ═══════════════════════════════════════════ AM5 — Monthly Roster Confirmation
        # 🔴 The gate looks the confirmation up BY EXACT NAME:
        #     frappe.db.exists("Monthly Roster Confirmation",
        #                      {"name": f"ROSTER-{y}-{m:02d}", "docstatus": 1})
        # An amended document is named ROSTER-2026-10-**1**. So the question is
        # not whether the gate closes during the amend window (it should) but
        # whether it ever OPENS AGAIN once HR has amended.
        from caf.caf.doctype.monthly_roster_confirmation import (
            monthly_roster_confirmation as mrc)

        gate_before = mrc.gate_from()          # snapshot through the ACCESSOR
        am5_ran = False
        try:
            if not mrc._field_exists():
                check("AM5", False, "gate field absent — run mrc.setup_fields() first")
            else:
                am5_ran = True
                m_name = "ROSTER-2026-10"
                for n in (m_name, m_name + "-1"):
                    if frappe.db.exists("Monthly Roster Confirmation", n):
                        d = frappe.get_doc("Monthly Roster Confirmation", n)
                        d.flags.ignore_permissions = True
                        if d.docstatus == 1:
                            d.reload()
                            d.cancel()
                        frappe.delete_doc("Monthly Roster Confirmation", n,
                                          ignore_permissions=True, force=True)
                frappe.db.commit()

                conf = frappe.new_doc("Monthly Roster Confirmation")
                conf.month_start = "2026-10-01"
                # ⚠️ MG's own guard: the form refuses to submit unanswered —
                # *"either list the new holidays, or tick 'No new holidays'."*
                conf.no_new_holidays = 1
                conf.flags.ignore_permissions = True
                conf.insert()
                conf.submit()

                frappe.db.set_single_value("HR Settings", mrc.GATE_FIELD,
                                           "2026-01-01")
                frappe.clear_document_cache("HR Settings", "HR Settings")
                stub = frappe._dict(work_date="2026-10-14")

                _a, e_ok = as_user(HRM, mrc.require_confirmed_month, stub)
                conf.reload()
                conf.cancel()
                _b, e_window = as_user(HRM, mrc.require_confirmed_month, stub)
                new_conf, e_amend = as_user(HRM, amend,
                                            "Monthly Roster Confirmation", conf.name)
                if new_conf:
                    new_conf.reload()
                    as_user(HRM, lambda: new_conf.submit())
                _c, e_after = as_user(HRM, mrc.require_confirmed_month, stub)

                # ✅ FIXED 2026-08-13 (OD-81c): the gate keys on `month_start`,
                # not on the document name. The three states are asserted in
                # order, and the middle one is the control — without it, a gate
                # that simply never refused would also pass.
                check("AM5",
                      not e_ok and bool(e_window) and not e_after
                      and new_conf and new_conf.name.endswith("-1"),
                      f"the gate follows the MONTH through an amend. Confirmed "
                      f"➜ passes ({e_ok}); cancelled ➜ refuses ({e_window}) — "
                      f"the control, and correct, that is the amend window; "
                      f"amended and re-submitted as "
                      f"{new_conf.name if new_conf else '?'} ➜ passes again "
                      f"({e_after}). 🔴 Before OD-81c it matched the exact name "
                      f"`ROSTER-2026-10` while Frappe names the amendment "
                      f"`...-1`, so a month HR corrected was blocked for good")
        finally:
            # Trap #2 from the Single-doctype register: restore through the same
            # normalising accessor, so MEANING round-trips rather than storage.
            frappe.db.set_single_value("HR Settings", mrc.GATE_FIELD,
                                       gate_before or "")
            frappe.clear_document_cache("HR Settings", "HR Settings")
            for n in ("ROSTER-2026-10", "ROSTER-2026-10-1"):
                if frappe.db.exists("Monthly Roster Confirmation", n):
                    d = frappe.get_doc("Monthly Roster Confirmation", n)
                    d.flags.ignore_permissions = True
                    if d.docstatus == 1:
                        d.reload()
                        d.cancel()
                    frappe.delete_doc("Monthly Roster Confirmation", n,
                                      ignore_permissions=True, force=True)
            frappe.db.commit()

        if am5_ran:
            check("AM5-RESTORE", mrc.gate_from() == gate_before,
                  f"the roster gate is back to {gate_before!r} — compared "
                  f"through `gate_from()`, because a raw read of a cleared Date "
                  f"on a Single returns 0001-01-01 and would compare unequal to "
                  f"a normalised None on the next run")

        # ═══════════════════════════════════════════════ AM6 — as an Employee
        log2 = make_log(D_LOG)
        _r, e1 = as_user(EMP_USER, lambda: frappe.get_doc("Finger Log",
                                                          log2.name).cancel())
        la2 = frappe.new_doc("Leave Application")
        la2.employee = EMP
        la2.leave_type = LEAVE_TYPE
        la2.from_date = la2.to_date = D_LEAVE
        la2.status = "Approved"
        la2.flags.ignore_permissions = True
        la2.insert()
        la2.submit()
        _r, e2 = as_user(EMP_USER, amend, "Leave Application", la2.name)

        check("AM6", bool(e1) and bool(e2),
              f"a plain Employee is refused on BOTH: Finger Log cancel "
              f"({e1}) and Leave Application amend "
              f"({e2}). Run as the role, not as "
              f"Administrator — as Administrator both would have succeeded and "
              f"this assertion would have been meaningless")

    finally:
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    check("AM-RESTORE", frappe.session.user == "Administrator",
          f"session restored to {frappe.session.user} — asserted, not assumed. "
          f"A suite that exits still switched poisons every suite after it")

    print("\n=== AM — amendment per doctype, as a ROLE ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:14s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
