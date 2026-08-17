"""I-* — the Ingress import feature, end to end.

    bench --site <site> execute caf.tests.ingress.test_ingress_import.run

Standalone and self-cleaning, the `workflow_gaps` pattern. NOT in `run_all()`.

WHAT THIS SUITE IS ACTUALLY FOR
-------------------------------
The importer's hard part is not reading a machine — it is refusing to. Ingress
rewrites whole months whenever it likes, while ERPNext carries correction routes
a human chose on purpose (D-9 cancel, OD-48 amend, D-13's OT cascade). Most of
the assertions below are therefore about what the importer must NOT do.

🔴 The one that matters most is I7. Chunk 3's importer filtered `docstatus < 2`,
so a Finger Log HR deliberately cancelled came back as a fresh Draft on the very
next run — the cancel silently undone, on a schedule.

FIXTURES — 2026-08-03 / 08-04 / 08-06, employees 00004 / 00005 / 00007
----------------------------------------------------------------------
Chosen by measurement, not by habit. Every other suite's dates were grepped
first: August 5, 11, 12, 13, 14, 15 and 17 are taken, and so are employees
00001/2/3, 9, 10, 11, 13, 16, 17, 20, 22, 24 and 75. §F4d's rule is that
collisions are avoided by DATE, and these three are free.

⚠️ **2026-08-06 carries a real absence**: Ingress has userid 457 rostered that
day with no punch at all. That is not a gap in the fixture — it is the Absent
case, measured on the live machine, and I3 asserts it.

SYNTHETIC ROWS
--------------
Drift and draft-update cannot be tested against a live machine whose values we
cannot change. Those assertions build normalised rows by hand and call
`sync._import` directly — white-box, deliberately, because the alternative is a
test hook in production code.
"""

import frappe
from frappe.utils import getdate

from caf.caf.ingress import source as isrc
from caf.caf.ingress import sync

# ── fixtures ────────────────────────────────────────────────────────────────
EMP_A, TAG_A = "HR-EMP-00004", "224"
EMP_B, TAG_B = "HR-EMP-00005", "339"
EMP_C, TAG_C = "HR-EMP-00007", "457"        # no punch on D3 — the Absent case
EMPS = [EMP_A, EMP_B, EMP_C]                # the range-import set: 3 x 4 dates = 12

# 🔴 I11 needs an OT-ELIGIBLE shift and nothing else will do. OT is a per-shift
# flag (FBR36/FDR7), and on this site 3 of the 4 shifts carry
# `caf_allow_ot = 0` — including all three fixtures above. On those,
# `apply_ot_rules` returns 0, `check_ot_approval` never runs, and a log with two
# and a half hours of clocked overtime submits perfectly cleanly. The first
# version of I11 used EMP_A and read that clean submit as a LOST observation.
# ⚠️ AND the day must carry no real OT Approval. HR-EMP-00023 was the first
# pick and holds a genuine submitted approval for 3.0 h on 2026-08-04, so its
# 2.5 h clocked OT was approved and submitted exactly as designed — the code was
# right and the fixture was wrong. HR-EMP-00052 has none on any of these dates,
# asserted at run time below rather than trusted.
EMP_OT, TAG_OT = "HR-EMP-00052", "998"      # 8am Schedule — caf_allow_ot = 1
ALL_EMPS = EMPS + [EMP_OT]                  # what teardown covers

D1 = "2026-08-03"
D2 = "2026-08-04"
D3 = "2026-08-06"                            # EMP_C is absent here
# ⚠️ 08-05 is not asserted on, but it sits INSIDE D1..D3 and every range import
# therefore creates it. Leaving it out of the teardown list made the full-cycle
# count read 9 where 12 were created — a suite that does not clean the whole
# range it imports is a suite whose next run starts dirty.
DATES = [D1, D2, "2026-08-05", D3]

HRM = "hr.manager.test@caffood.com"
EMP_USER = "mohd@caffood.com"

RESULTS = []
SKIPPED = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def skip(tid, why):
    """A third state, and it has to exist.

    🔴 Some assertions genuinely need the Ingress machine — source parity cannot
    be checked against one source, and the August fixtures are not in the July
    snapshot. When Natalie is off (it went off mid-session on 2026-08-17, right
    after HR made the test edits) those rows must SKIP, not fail: a red gate that
    is red for a reason nobody can fix from here is a gate people learn to
    ignore. They are printed loudly and counted separately, never silently
    dropped and never counted as passes.
    """
    SKIPPED.append((tid, why))


def live_available():
    """Is the machine reachable right now? Asked once, cheaply."""
    try:
        isrc.get_source("Live MySQL").describe()
        return True
    except Exception:
        return False


def as_user(user, fn, *a, **kw):
    """Run `fn` as `user` and ALWAYS come back.

    🔴 `refusal` is the EXCEPTION TYPE NAME, never `str(e)` —
    `str(frappe.PermissionError)` is frequently the empty string, so `bool(err)`
    reads False against operations that WERE correctly refused (§E5).
    """
    before = frappe.session.user
    try:
        frappe.set_user(user)
        return fn(*a, **kw), None
    except Exception as e:
        msg = frappe.utils.strip_html(str(e) or "").strip()
        return None, f"{type(e).__name__}{': ' + msg[:90] if msg else ''}"
    finally:
        frappe.set_user(before)


def machine_row(ftag, day, time_in="08:00:00", brk="12:00:00",
                resume="13:00:00", out="17:30:00", overtime=0.0, edited=None):
    """A normalised row, exactly as `source.normalise` would emit it."""
    return {"ftag_id": ftag, "work_date": getdate(day), "time_in": time_in,
            "break": brk, "resume": resume, "out": out, "overtime": overtime,
            "hasmisspunch": 0, "lastupdate": None, "edited": edited or []}


def run_rows(rows, submit=False, allow_recreate=False, purpose="Test"):
    """Import synthetic rows through the real pipeline. Returns the batch doc."""
    batch = sync._Batch("Manual", purpose, D1, D3, EMPS, "synthetic")
    frappe.flags.in_import = True
    try:
        sync._import(batch, rows, sync.active_by_device(), submit, allow_recreate)
        doc = batch.finish("Completed")
    finally:
        frappe.flags.in_import = False
    frappe.db.commit()
    return doc


def seed(live):
    """Put the 12 fixture rows in place — from the machine, or equivalently.

    Everything after I4 depends on this data existing, so when the machine is
    unreachable the suite must still be ABLE to seed it, or two thirds of the
    ownership rule goes untested for a reason that has nothing to do with the
    code. The synthetic path mirrors what the machine actually holds for these
    employees, including EMP_C's genuine all-zero day on D3.
    """
    if live:
        return sync.manual_import(D1, D3, employees=EMPS, submit=True,
                                  purpose="Test", source_mode="Live MySQL")

    rows = []
    for emp, tag in ((EMP_A, TAG_A), (EMP_B, TAG_B), (EMP_C, TAG_C)):
        for day in DATES:
            if emp == EMP_C and day == D3:
                # the measured absence — rostered, never punched
                rows.append(machine_row(tag, day, "00:00:00", "00:00:00",
                                        "00:00:00", "00:00:00"))
            else:
                rows.append(machine_row(tag, day))
    doc = run_rows(rows, submit=True)
    return {"batch": doc.name,
            "counts": {"created": doc.created, "submitted": doc.submitted,
                       "failed": doc.failed, "held": doc.held,
                       "already_present": doc.already_present,
                       "drift": doc.drift}}


def cleanup():
    """Scoped to this suite's employees and dates. Runs FIRST (§F4).

    Order: Attendance before Finger Log — a live Attendance links back to its
    log, and stock refuses to delete a document another one points at.
    """
    for att in frappe.get_all("Attendance",
                              filters={"employee": ("in", ALL_EMPS),
                                       "attendance_date": ("in", DATES)},
                              fields=["name", "docstatus"]):
        doc = frappe.get_doc("Attendance", att.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        doc.flags.caf_skip_leave_guard = True
        if doc.docstatus == 1:
            doc.reload()
            doc.cancel()
        frappe.delete_doc("Attendance", att.name, ignore_permissions=True,
                          force=True, delete_permanently=True)

    for fl in frappe.get_all("Finger Log",
                             filters={"employee": ("in", ALL_EMPS),
                                      "work_date": ("in", DATES)},
                             fields=["name", "docstatus"]):
        doc = frappe.get_doc("Finger Log", fl.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.reload()
            doc.cancel()
        frappe.delete_doc("Finger Log", fl.name, ignore_permissions=True,
                          force=True, delete_permanently=True)

    # Batches last, and ALL of them in this suite's window — synthetic runs and
    # real ones alike. A pass leaves ~17 batch documents behind otherwise: the
    # DATA was clean but the records were not, which is the same fixture creep
    # this feature exists to end.
    # `on_trash` refuses while any Finger Log still points at a batch; that is
    # the guard working, and the loops above have already removed them.
    for b in frappe.get_all("Ingress Import Batch",
                            filters={"from_date": (">=", D1),
                                     "to_date": ("<=", D3)},
                            fields=["name"]):
        frappe.delete_doc("Ingress Import Batch", b.name,
                          ignore_permissions=True, force=True)
    frappe.db.commit()


def drop_day(emp, day):
    """Erase one (employee, work_date) completely — Attendance first."""
    for att in frappe.get_all("Attendance",
                              filters={"employee": emp, "attendance_date": day},
                              fields=["name", "docstatus"]):
        doc = frappe.get_doc("Attendance", att.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        doc.flags.caf_skip_leave_guard = True
        if doc.docstatus == 1:
            doc.reload()
            doc.cancel()
        frappe.delete_doc("Attendance", att.name, ignore_permissions=True,
                          force=True, delete_permanently=True)
    for fl in frappe.get_all("Finger Log",
                             filters={"employee": emp, "work_date": day},
                             fields=["name", "docstatus"]):
        doc = frappe.get_doc("Finger Log", fl.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.reload()
            doc.cancel()
        frappe.delete_doc("Finger Log", fl.name, ignore_permissions=True,
                          force=True, delete_permanently=True)
    frappe.db.commit()


def fl_for(emp, day, docstatus=None):
    filters = {"employee": emp, "work_date": day}
    if docstatus is not None:
        filters["docstatus"] = docstatus
    return frappe.get_all("Finger Log", filters=filters,
                          fields=["name", "docstatus", "caf_import_batch",
                                  "time_in", "shift_type", "day_type",
                                  "caf_work_hours", "short", "caf_not_full_day"],
                          order_by="creation desc")


# ═══════════════════════════════════════════════════════════════════════════
def run():
    frappe.set_user("Administrator")
    cleanup()
    LIVE = live_available()
    if not LIVE:
        print("\n⚠️  Ingress machine UNREACHABLE — the live-source rows will be "
              "SKIPPED. Everything driven by synthetic rows still runs, which is "
              "most of the ownership rule.\n")

    try:
        # ══════════════════════════════════ I1 — the two sources agree
        # The snapshot holds July; live holds everything, so July is the overlap.
        if LIVE:
            live_rows, snap_rows, i1_err = {}, {}, None
            try:
                live = isrc.get_source("Live MySQL")
                snap = isrc.get_source("Snapshot CSV")
                for r in live.read("2026-07-15", "2026-07-15", [TAG_A, TAG_B]):
                    live_rows[(r["ftag_id"], str(r["work_date"]))] = r
                for r in snap.read("2026-07-15", "2026-07-15", [TAG_A, TAG_B]):
                    snap_rows[(r["ftag_id"], str(r["work_date"]))] = r
            except Exception as e:
                i1_err = frappe.utils.strip_html(str(e))[:120]

            same = live_rows and live_rows.keys() == snap_rows.keys() and all(
                all(live_rows[k][f] == snap_rows[k][f]
                    for f in ("time_in", "break", "resume", "out", "overtime"))
                for k in live_rows)
            check("I1-SOURCE-PARITY", same and not i1_err,
                  f"LiveSource and SnapshotSource produced identical punches for "
                  f"{len(live_rows)} row(s) on 2026-07-15 — the two readers agree, "
                  f"so a result from one is a result from the other"
                  if same else
                  f"🔴 sources disagree: live={len(live_rows)} "
                  f"snapshot={len(snap_rows)} err={i1_err}")
        else:
            skip("I1-SOURCE-PARITY", "needs BOTH sources; machine unreachable")

        # ══════════════════════════════════ I2/I3 — the fixture import
        out = seed(LIVE)
        batch_name = out["batch"]
        counts = out["counts"]

        rows_a = fl_for(EMP_A, D1)
        shift_from_erp = frappe.db.get_value("Employee", EMP_A, "default_shift")
        check("I2-NEVER-IMPORT",
              bool(rows_a) and rows_a[0].shift_type == shift_from_erp
              and rows_a[0].day_type in ("Workday", "Restday", "Holiday")
              and rows_a[0].caf_work_hours is not None,
              f"the machine's `daytype`/`sche1` were NOT imported (OD-45): "
              f"shift_type reads {rows_a[0].shift_type!r} — resolved from "
              f"ERPNext's Shift Assignment / default_shift, which is "
              f"{shift_from_erp!r} — and day_type {rows_a[0].day_type!r} plus "
              f"work hours {rows_a[0].caf_work_hours} were DERIVED by validate(), "
              f"not read (OD-59)"
              if rows_a else "🔴 no Finger Log created for EMP_A on D1")

        # 🔴 The absence is measured, not manufactured: Ingress rosters userid
        # 457 on 2026-08-06 and records no punch. `is_all_zero` -> Absent.
        rows_c = fl_for(EMP_C, D3)
        att_c = frappe.get_all("Attendance",
                               filters={"employee": EMP_C, "attendance_date": D3,
                                        "docstatus": 1},
                               fields=["name", "status", "leave_type"])
        check("I3-ABSENCE",
              bool(rows_c) and bool(att_c) and att_c[0].status == "Absent"
              and not att_c[0].leave_type and float(rows_c[0].short or 0) > 0,
              f"the all-zero row became a verdict: {EMP_C} on {D3} has no punches "
              f"on the machine, so the Finger Log carries short="
              f"{rows_c[0].short if rows_c else '—'} (the whole scheduled net) and "
              f"the Attendance reads "
              f"{att_c[0].status if att_c else '—'} with leave_type "
              f"{att_c[0].leave_type if att_c else '—'!r} — empty, which is what "
              f"FBR37 counts as unexplained absence (FDR4)"
              if att_c else
              f"🔴 no submitted Attendance for {EMP_C} on {D3}: fl={len(rows_c)}")

        check("I2b-COUNTS",
              counts["created"] == 12 and counts["submitted"] == 12
              and counts["failed"] == 0,
              f"12 machine rows -> 12 created, {counts['submitted']} submitted, "
              f"{counts['failed']} failed, {counts['held']} held")

        # ══════════════════════════════════ I4 — idempotency
        again = seed(LIVE)
        check("I4-IDEMPOTENT",
              again["counts"]["already_present"] == 12
              and again["counts"]["created"] == 0
              and again["counts"]["drift"] == 0,
              f"a second identical run created {again['counts']['created']} and "
              f"recognised {again['counts']['already_present']} as already "
              f"present, with {again['counts']['drift']} drift. ⚠️ The drift count "
              f"is asserted deliberately: a Frappe Time round-trips from the DB "
              f"as a timedelta whose str() is '8:23:00', so an unnormalised "
              f"comparison reported drift on EVERY row of a run that changed "
              f"nothing")
        frappe.delete_doc("Ingress Import Batch", again["batch"],
                          ignore_permissions=True, force=True)

        # ══════════════════════════════════ I9/I10 — drift on a submitted log
        drifted = run_rows([machine_row(TAG_A, D1, time_in="09:15:00")])
        fl_a = fl_for(EMP_A, D1)[0]
        drift_rows = [r for r in frappe.get_doc(
            "Ingress Import Batch", drifted.name).rows if r.action == "Drift"]
        check("I9-DRIFT-REPORTED",
              drifted.drift == 1 and bool(drift_rows)
              and sync._as_time_str(fl_a.time_in) != "09:15:00",
              f"the machine now says 09:15 for a day ERPNext already submitted. "
              f"The importer REPORTED it ({drifted.drift} drift row: "
              f"{drift_rows[0].reason if drift_rows else '—'}) and left the "
              f"document alone — it still reads "
              f"{sync._as_time_str(fl_a.time_in)}. FBR8: report, never "
              f"auto-correct")

        # 🔴 MG's question, 2026-08-17: "where does the drift report live?" — a
        # drift recorded only in a batch document is one nobody meets. It has to
        # reach the document in dispute.
        flagged = frappe.db.get_value("Finger Log", fl_a.name,
                                      ["caf_hr_review", "caf_hr_review_note"],
                                      as_dict=True)
        check("I9b-DRIFT-REACHES-THE-LOG",
              flagged.caf_hr_review == 1 and "Ingress revised" in (
                  flagged.caf_hr_review_note or ""),
              f"the drift is flagged ON THE FINGER LOG "
              f"(caf_hr_review={flagged.caf_hr_review}), not only in the batch — "
              f"note reads {(flagged.caf_hr_review_note or '')[:90]!r}. That field "
              f"already drives the HR appraisal dashboard's review panel, so the "
              f"day surfaces where HR is already looking")

        # D-13's OT cascade rewrites final_ot / ot_approval_id on a SUBMITTED
        # log. Those are ERP-owned and have no machine counterpart, so they must
        # not count as drift or every cascade raises a false alarm.
        doc_a = frappe.get_doc("Finger Log", fl_a.name)
        doc_a.flags.caf_system_write = True
        doc_a.flags.ignore_permissions = True
        doc_a.final_ot = 2.0
        doc_a.ot_approval_id = ""
        doc_a.caf_hr_review = 1
        doc_a.save(ignore_permissions=True)
        frappe.db.commit()
        clean = run_rows([machine_row(
            TAG_A, D1, time_in=sync._as_time_str(fl_a.time_in),
            brk=sync._as_time_str(frappe.db.get_value("Finger Log", fl_a.name, "break")),
            resume=sync._as_time_str(frappe.db.get_value("Finger Log", fl_a.name, "resume")),
            out=sync._as_time_str(frappe.db.get_value("Finger Log", fl_a.name, "out")))])
        check("I10-CASCADE-NO-FALSE-DRIFT",
              clean.drift == 0 and clean.already_present == 1,
              f"a submitted log carrying the D-13 cascade's marks "
              f"(final_ot=2.0, ot_approval_id cleared, caf_hr_review=1) raised "
              f"{clean.drift} drift against unchanged punches. Drift compares "
              f"PUNCHES only — including the OT fields would make every "
              f"legitimate OT cancellation look like the machine disagreeing")

        # ══════════════════════════════════ I7 — 🔴 the cancelled day
        fl_b = fl_for(EMP_B, D2)[0]
        doc_b = frappe.get_doc("Finger Log", fl_b.name)
        doc_b.flags.ignore_permissions = True
        doc_b.cancel()
        frappe.db.commit()
        state, existing, detail = sync.day_state(EMP_B, D2)

        after_cancel = run_rows([machine_row(TAG_B, D2)])
        live_after = fl_for(EMP_B, D2, docstatus=0)
        check("I7-CANCELLED-NOT-RESURRECTED",
              state == sync.CANCELLED and after_cancel.created == 0
              and after_cancel.skipped_locked == 1 and not live_after,
              f"HR cancelled {EMP_B}'s log for {D2}; the next import created "
              f"{after_cancel.created} and skipped it as human-owned "
              f"({after_cancel.skipped_locked}), leaving {len(live_after)} live "
              f"drafts. 🔴 Chunk 3 filtered `docstatus < 2` and would have "
              f"re-created the day here, undoing the cancel silently on every "
              f"scheduled run")

        # …and the ONE route back: a human asking, by name and date.
        recreated = run_rows([machine_row(TAG_B, D2)], allow_recreate=True)
        live_now = fl_for(EMP_B, D2, docstatus=0)
        check("I7b-HUMAN-MAY-RECREATE",
              recreated.created == 1 and len(live_now) == 1,
              f"the same day re-imported with `allow_recreate` produced "
              f"{recreated.created} draft — the scheduled pass never sets that "
              f"flag, so the only way a cancelled day comes back is a person "
              f"asking for this employee on this date (the Re-import button)")

        # ══════════════════════════════════ I5/I6 — the draft, and who owns it
        draft = fl_for(EMP_B, D2, docstatus=0)[0]
        updated = run_rows([machine_row(TAG_B, D2, out="19:45:00")])
        after = frappe.db.get_value("Finger Log", draft.name, "out")
        check("I5-DRAFT-UPDATED",
              updated.updated == 1 and sync._as_time_str(after) == "19:45:00",
              f"the machine changed the out punch and the importer's OWN draft "
              f"was updated in place -> {sync._as_time_str(after)}. This is what "
              f"makes the 04:00 / 12:00 / 20:00 fetch split work: an incomplete "
              f"early draft is completed later, and nothing was ever submitted "
              f"in between")

        # A human touches it. From here the machine may only report.
        as_user(HRM, lambda: frappe.db.set_value(
            "Finger Log", draft.name, "caf_hr_review_note", "HR looked at this"))
        frappe.db.commit()
        state_h, _n, detail_h = sync.day_state(EMP_B, D2)
        touched = run_rows([machine_row(TAG_B, D2, out="21:00:00")])
        still = frappe.db.get_value("Finger Log", draft.name, "out")
        check("I6-HUMAN-DRAFT-UNTOUCHED",
              state_h == sync.DRAFT_HUMAN and touched.updated == 0
              and touched.skipped_locked == 1
              and sync._as_time_str(still) == "19:45:00",
              f"once {HRM} edited the draft it reads {detail_h!r}, and the next "
              f"import updated {touched.updated} rows — the out punch is still "
              f"{sync._as_time_str(still)}, not the machine's 21:00. A re-fetch "
              f"must never silently undo an HR correction")

        # ══════════════════════════════════ I8 — an amendment is human-owned
        fl_c = fl_for(EMP_C, D1)[0]
        amend_doc = frappe.get_doc("Finger Log", fl_c.name)
        amend_doc.flags.ignore_permissions = True
        amend_doc.cancel()
        amended = frappe.copy_doc(amend_doc)
        amended.amended_from = amend_doc.name
        amended.flags.ignore_permissions = True
        amended.insert()
        frappe.db.commit()
        state_am, _n2, detail_am = sync.day_state(EMP_C, D1)
        am_run = run_rows([machine_row(TAG_C, D1, out="22:00:00")])
        check("I8-AMENDMENT-UNTOUCHED",
              state_am == sync.DRAFT_HUMAN and am_run.updated == 0
              and am_run.skipped_locked == 1,
              f"an amended draft reads {detail_am!r} and the importer skipped it "
              f"({am_run.skipped_locked}). OD-48 Path 2 is HR's correction route; "
              f"a machine that overwrote the amendment would be undoing the "
              f"correction it was told about")

        # ══════════════════════════════════ I11 — OT with no approval is HELD
        # ⚠️ The day must be EMPTY first: a submitted day is human-owned, so an
        # import over one creates nothing and `held == 0` would mean "nothing was
        # imported", not "the observation was lost".
        drop_day(EMP_OT, D2)
        ot_shift = frappe.db.get_value("Employee", EMP_OT, "default_shift")
        allows_ot = frappe.db.get_value("Shift Type", ot_shift, "caf_allow_ot")
        # The other half of the premise, asserted rather than assumed: a real
        # approval on this day would make the submit succeed and the test pass
        # for the wrong reason.
        prior_ot = frappe.db.count("OT Approval Table",
                                   {"emp_id": EMP_OT, "work_date": D2,
                                    "docstatus": 1})
        # 2.30 is FBR2 hour.minute = 2 h 30 min = 150 min; past the 30 min gate,
        # rounds to 150 -> ot_in_hour 2.5, which is what FBR11 demands approval for.
        held = run_rows([machine_row(TAG_OT, D2, out="20:30:00", overtime=2.30)],
                        submit=True)
        held_fl = fl_for(EMP_OT, D2, docstatus=0)
        held_rows = [r for r in frappe.get_doc(
            "Ingress Import Batch", held.name).rows if r.action == "Held"]
        check("I11-OT-HELD-NOT-LOST",
              allows_ot == 1 and prior_ot == 0 and held.held == 1
              and held.submitted == 0 and bool(held_fl),
              f"on {ot_shift!r} (caf_allow_ot={allows_ot}, {prior_ot} existing "
              f"approvals) a log carrying 2 h 30 "
              f"of OT with no approval was refused at submit (FBR11) and SURVIVED "
              f"as a draft — {len(held_fl)} row, reason "
              f"{(held_rows[0].reason[:80] if held_rows else '—')!r}. ⚠️ The second "
              f"savepoint is what makes this true: rolling back to the outer one "
              f"would have deleted the imported row along with the failed submit, "
              f"losing what the clock saw. The draft IS the HR worklist. "
              f"⚠️ The shift flag is asserted because 3 of this site's 4 shifts "
              f"set caf_allow_ot=0 — on those this test passes vacuously"
              if held_fl else
              f"🔴 the observation was LOST: shift {ot_shift!r} allows_ot="
              f"{allows_ot}, prior approvals={prior_ot}, held={held.held}, "
              f"submitted={held.submitted}, no draft remains")

        # ══════════════════════════════════ I18 — who is not imported
        ghost = run_rows([machine_row("999999", D1)])
        check("I18-NO-EMPLOYEE-SKIPPED",
              ghost.skipped_no_employee == 1 and ghost.created == 0,
              f"a machine userid mapping to no active employee was skipped and "
              f"counted ({ghost.skipped_no_employee}) — Ingress keeps emitting "
              f"rostered days for people who left years ago (OD-24)")

        # ══════════════════════════════════ I21 — the adjustment flag is carried
        # ⚠️ The day must be empty, or an identical row reads as already-present
        # and the importer writes no manifest line to assert against. That is
        # correct behaviour and a vacuous test — the same trap as I11.
        drop_day(EMP_A, D3)
        edited_run = run_rows([machine_row(TAG_A, D3, edited=["time_in"])])
        er = [r for r in frappe.get_doc("Ingress Import Batch", edited_run.name).rows
              if r.employee == EMP_A]
        check("I21-ADJUSTED-FLAG",
              bool(er) and er[0].adjusted_in_ingress == 1,
              f"a punch the Ingress application wrote (rather than a device tap) "
              f"is marked on the manifest "
              f"(adjusted_in_ingress={er[0].adjusted_in_ingress if er else '—'}). "
              f"🔴 The source flag is **`_c`, not `_x`** — established by a "
              f"controlled HR edit on 2026-08-17: `att_out` 17:58→19:45, `out_o` "
              f"KEPT 17:58, `out_c` 0→1, and `out_x` never moved. Watching `_x`, "
              f"as this code originally did, would never have seen an edit at all")

        # ══════════════════════════════════ I20 — in_import is honoured
        calls = []
        import caf.caf.appraisal_refresh as ar
        real_refresh = ar.refresh_for
        try:
            ar.refresh_for = lambda *a, **kw: calls.append(a)
            batch_flag = run_rows([machine_row(TAG_C, D2)], submit=True)
        finally:
            ar.refresh_for = real_refresh
        check("I20-NO-REFRESH-STORM",
              not calls and frappe.flags.in_import is False,
              f"{len(calls)} appraisal refreshes fired during a submitting batch, "
              f"and the flag is back to {frappe.flags.in_import}. D-15: a run of "
              f"thousands of rows must not refresh per row, and an exception "
              f"escaping mid-batch must not leave the flag set for whoever runs "
              f"next")

        # ══════════════════════════════════ I19 — permissions
        # ⚠️ `frappe.get_doc(...).as_dict()` does NOT check read permission —
        # the first version of this test called exactly that, got None for every
        # refusal, and reported a permission model that had never been exercised.
        # `check_permission` is the call that actually raises.
        _r, e_read = as_user(EMP_USER, lambda: frappe.get_doc(
            "Ingress Import Batch", batch_name).check_permission("read"))
        _r2, e_set = as_user(EMP_USER, lambda: frappe.get_single(
            "Ingress Sync Settings").check_permission("read"))
        _r3, e_hrm = as_user(HRM, lambda: frappe.get_doc(
            "Ingress Import Batch", batch_name).check_permission("read"))
        emp_batch = frappe.has_permission("Ingress Import Batch", "read",
                                          user=EMP_USER)
        hrm_batch = frappe.has_permission("Ingress Import Batch", "read", user=HRM)
        check("I19-PERMISSIONS",
              bool(e_read) and bool(e_set) and not e_hrm
              and not emp_batch and hrm_batch,
              f"a plain Employee is refused on both new doctypes — batch "
              f"({e_read}), settings ({e_set}), has_permission={emp_batch} — and "
              f"HR Manager reads the batch (has_permission={hrm_batch}). Run as "
              f"the ROLE: as Administrator every one of these would have "
              f"succeeded and the assertion would mean nothing (§C1)")

        # ══════════════════════════════════ I16 — revert refuses Production
        prod = run_rows([machine_row(TAG_A, D3)], purpose="Production")
        _r4, e_prod = as_user(HRM, sync.revert_batch, prod.name)
        check("I16-PRODUCTION-REFUSED",
              bool(e_prod) and "Validation" in str(e_prod) or bool(e_prod),
              f"reverting a Production batch without force was refused — "
              f"{e_prod}. The undo button exists for test fixtures, not for last "
              f"week's payroll input")

        # ══════════════════════════════════ I15 — revert refuses a touched row
        drop_day(EMP_B, D3)                  # same emptiness requirement as I21
        test_batch = run_rows([machine_row(TAG_B, D3)])
        made = [r.finger_log for r in frappe.get_doc(
            "Ingress Import Batch", test_batch.name).rows if r.finger_log]
        as_user(HRM, lambda: frappe.db.set_value(
            "Finger Log", made[0], "caf_hr_review_note", "mine now"))
        frappe.db.commit()
        res_refuse = sync.revert_batch(test_batch.name)
        check("I15-REVERT-REFUSES-TOUCHED",
              res_refuse["removed"] == 0 and len(res_refuse["refused"]) == 1
              and frappe.db.exists("Finger Log", made[0]),
              f"revert refused the one row a human had modified and NAMED it — "
              f"{res_refuse['refused']}. A revert that destroys somebody's "
              f"in-flight work is worse than one that stops and says why")

        # ══════════════════════════════════ I14 — the whole point: clean teardown
        final = ({"batch": run_rows([machine_row(TAG_A, D1)], submit=True,
                                    allow_recreate=True).name}
                 if not LIVE else
                 sync.manual_import(D1, D1, employees=[EMP_A], submit=True,
                                    purpose="Test", source_mode="Live MySQL",
                                    allow_recreate=True))
        # D1/EMP_A already holds a submitted log from the first run, so this
        # asserts the SECOND half of the contract: nothing new was created, and
        # the revert therefore removes nothing that was not this batch's.
        rev = sync.revert_batch(final["batch"], force=True)
        left_fl = fl_for(EMP_A, D1)
        check("I14-REVERT-SCOPED",
              rev["status"] == "Reverted" and bool(left_fl),
              f"reverting a batch that created nothing removed "
              f"{rev['removed']} logs and left the pre-existing "
              f"{len(left_fl)} in place — a revert is scoped to what its own "
              f"batch produced, never to the date range it looked at")

        # And the full create -> submit -> revert -> nothing cycle, measured.
        cleanup()
        cycle = seed(LIVE)
        mid_fl = frappe.db.count("Finger Log", {"employee": ("in", EMPS),
                                                "work_date": ("in", DATES)})
        mid_att = frappe.db.count("Attendance", {"employee": ("in", EMPS),
                                                 "attendance_date": ("in", DATES)})
        rev2 = sync.revert_batch(cycle["batch"])
        end_fl = frappe.db.count("Finger Log", {"employee": ("in", EMPS),
                                                "work_date": ("in", DATES)})
        end_att = frappe.db.count("Attendance", {"employee": ("in", EMPS),
                                                 "attendance_date": ("in", DATES)})
        check("I14b-FULL-CYCLE",
              mid_fl == 12 and mid_att == 12 and end_fl == 0 and end_att == 0
              and rev2["attendance_removed"] == 12,
              f"import -> {mid_fl} Finger Logs + {mid_att} Attendance; revert -> "
              f"{end_fl} and {end_att}. 🔴 The Attendance count is the assertion "
              f"that matters: `cancel_attendance` only CANCELS, so the first "
              f"version of revert left 9 cancelled rows behind pointing at logs "
              f"it had deleted. A test fixture you cannot fully remove is not a "
              f"test fixture")

    finally:
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    check("I-RESTORE", frappe.session.user == "Administrator"
          and frappe.flags.in_import is False,
          f"session restored to {frappe.session.user} and in_import="
          f"{frappe.flags.in_import} — asserted, not assumed. A suite that exits "
          f"still switched, or still flagged, poisons every suite after it")

    print("\n=== I — Ingress import ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:28s} {'PASS' if ok else 'FAIL'}  {detail}")
    for tid, why in SKIPPED:
        print(f"{tid:28s} SKIP  {why}")
    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" · {len(SKIPPED)} skipped" if SKIPPED else "")
          + (f" — FAILED: {failed}" if failed else ""))
    if SKIPPED:
        print("⚠️  Skipped rows are NOT passes. Re-run with the Ingress machine "
              "reachable before treating this suite as a full gate.")
    return not failed
