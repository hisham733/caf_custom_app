# Copyright (c) 2026, CAF and contributors
# For license information, please see license.txt

"""Ingress ➜ Finger Log. The negotiation between a machine and a set of humans.

This is not "copy rows in". Ingress recomputes whenever it likes — it rewrites an
entire month at month end — while ERPNext carries correction routes that a human
chose deliberately: D-9 cancel, OD-48 amend, D-13's OT cascade, D-12's leave
guard. An importer that simply wrote what the machine currently says would undo
those, silently, on a schedule.

🔴 THE RULE THE WHOLE MODULE TURNS ON
-------------------------------------
    The machine owns a work_date only while its Finger Log is a Draft that no
    human has touched. Every other state is human-owned, and the importer may
    only REPORT on it.

    none                  -> create Draft
    Draft, machine-owned  -> update in place if the machine values changed
    Draft, human-edited   -> skip + report          "edited by X"
    Submitted             -> skip + report drift    (FBR8: report, never correct)
    Cancelled             -> skip + report          HR un-decided this day

The cancelled case is the one that matters most and the one Chunk 3 got wrong:
`ingress_import.py:141` filters `docstatus < 2`, so a log HR deliberately
cancelled comes back as a fresh Draft on the very next run. That is the defect
this module exists to close.

WHAT IS IMPORTED
----------------
    work_date            the business date, FBR7
    time_in break resume out    the four punches — FACTS, FDR10
    overtime             hour.minute, FBR2
    ftag_id              provenance, and the join key

Everything else is derived by `FingerLog.validate()` or belongs to another
document. See `source.py`'s NEVER_IMPORT.

WHO IS IMPORTED — OD-24
-----------------------
Employees who are **Active** and carry an `attendance_device_id`. Ingress keeps
emitting rostered days for people who left years ago (one ex-employee has 457
such rows, none of them punched). An **active** employee who simply did not turn
up DOES get a row, with no punches — that is the `Absent` case and it is the
point of the design, not noise.

SAFETY
------
**Savepoint per row.** A bare `rollback()` inside a per-row `except` destroyed
~5,600 good rows in this project. Twice.

**A refused submit must not discard the observation.** FBR11 refuses a log
carrying OT with no approval, and that is correct — but rolling back to the outer
savepoint would delete the imported row along with the failed submit, losing what
the clock saw. The draft IS the queue HR works from. A second savepoint, taken
after the insert, keeps it.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, nowdate

from caf.caf.ingress import source as src

# The punch fields, in the order a human reads them. Also exactly the fields that
# constitute DRIFT — see `_machine_differs`.
PUNCH_FIELDS = ("time_in", "break", "resume", "out", "overtime")

# Day-ownership states.
NONE = "none"
DRAFT_MACHINE = "draft_machine"
DRAFT_HUMAN = "draft_human"
SUBMITTED = "submitted"
CANCELLED = "cancelled"


# ─────────────────────────────────────────────────────────────────── helpers

def active_by_device() -> dict:
    """Ingress `userid` -> the ACTIVE Employee carrying it as attendance_device_id.

    This is the only link between the two systems: `Ingress.user.userid` ↔
    `Employee.attendance_device_id`. Neither side shares a name, an email or a
    staff number that the other can be trusted to hold.
    """
    rows = frappe.get_all("Employee", filters={"status": "Active"},
                          fields=["name", "employee_name", "attendance_device_id"])
    return {str(r.attendance_device_id).strip(): r
            for r in rows if r.attendance_device_id}


def day_state(employee: str, work_date):
    """Who owns this (employee, work_date)? Returns (state, finger_log, detail).

    Resolution order is deliberate: a LIVE document (draft or submitted) always
    decides, and only when there is none do we look for a cancelled one. That way
    the amend case falls out for free — a cancelled original plus its live
    amendment reads as the amendment's state, which is what it is.
    """
    live = frappe.get_all(
        "Finger Log",
        filters={"employee": employee, "work_date": work_date,
                 "docstatus": ("<", 2)},
        fields=["name", "docstatus", "owner", "modified_by", "caf_import_batch",
                "amended_from"],
        order_by="creation desc", limit=1)

    if live:
        fl = live[0]
        if fl.docstatus == 1:
            return SUBMITTED, fl.name, _("submitted")
        # 🔴 An amendment is human-owned FROM BIRTH, and this test must come
        # first. `frappe.copy_doc` carries every field that is not `no_copy`,
        # so an amendment of an imported log inherited `caf_import_batch` and
        # read as machine-owned — the importer would then have overwritten the
        # very correction OD-48 Path 2 exists to make. (`caf_import_batch` is
        # now `no_copy` as well; this ordering is the belt to that brace, and
        # covers amendments made before the field changed.)
        if fl.amended_from:
            return DRAFT_HUMAN, fl.name, _("draft amendment of {0}").format(
                fl.amended_from)

        # A plain draft. Ours only if we made it and nobody has been in since.
        # ⚠️ Narrow hole, documented rather than hidden: if the SAME user who ran
        # the import then edits the draft by hand, owner == modified_by still and
        # the row reads as machine-owned. In normal operation the importer runs as
        # Administrator on the scheduler while HR edits as themselves, so the two
        # differ. Tightening this needs a dedicated stamp field — noted, not built.
        if fl.caf_import_batch and fl.modified_by == fl.owner:
            return DRAFT_MACHINE, fl.name, _("draft, machine-owned")
        return DRAFT_HUMAN, fl.name, _("draft, last edited by {0}").format(fl.modified_by)

    cancelled = frappe.get_all(
        "Finger Log",
        filters={"employee": employee, "work_date": work_date, "docstatus": 2},
        fields=["name", "modified_by"], order_by="creation desc", limit=1)
    if cancelled:
        return CANCELLED, cancelled[0].name, _(
            "cancelled by {0} — a cancelled day is HR's decision and the importer "
            "does not undo it").format(cancelled[0].modified_by)

    return NONE, None, ""


def _as_time_str(value) -> str:
    """Canonical 'HH:MM:SS', whatever shape the value arrived in.

    🔴 This function exists because of a bug that made EVERY row look like drift.
    A Frappe `Time` field round-trips through MariaDB as a `datetime.timedelta`,
    and `str(timedelta(hours=8, minutes=23))` is `'8:23:00'` — no leading zero.
    Compared naively against the machine's `'08:23:00'` it never matches, so the
    importer reported drift on all nine rows of a run that had changed nothing.
    Comparing punches means normalising both sides first, always.
    """
    if value in (None, ""):
        return "00:00:00"
    if hasattr(value, "total_seconds"):                 # timedelta, from the DB
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    if hasattr(value, "hour"):                          # datetime.time
        return f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    parts = str(value).strip().split(":")
    if len(parts) == 2:
        parts.append("00")
    try:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(float(parts[2])):02d}"
    except (ValueError, IndexError):
        return str(value)


def _machine_differs(doc, row) -> list:
    """Which punch fields the machine now disagrees with. Punches ONLY.

    🔴 `final_ot` and `ot_approval_id` are deliberately excluded. They are
    ERP-owned and have no machine counterpart, and D-13's OT-cancel cascade
    rewrites both on a SUBMITTED log. Including them would turn every legitimate
    cascade into a false drift alarm.
    """
    changed = []
    for field in PUNCH_FIELDS:
        old, new = doc.get(field), row.get(field)
        if field == "overtime":
            if abs(float(old or 0) - float(new or 0)) > 0.001:
                changed.append(field)
        elif _as_time_str(old) != _as_time_str(new):
            changed.append(field)
    return changed


def _flag_drift(finger_log: str, changed: list, batch_name: str):
    """Put the drift where a human will meet it: on the Finger Log.

    The batch is the run record; `caf_hr_review` is the worklist. HR opening the
    day in dispute sees the flag and the note without knowing an import batch
    exists. Idempotent by content — re-running a sweep over the same unchanged
    disagreement rewrites the same note rather than stacking comments.
    """
    doc = frappe.get_doc("Finger Log", finger_log)
    note = _("Ingress revised this day after ERPNext submitted it ({0}). The log "
             "was NOT changed. If the machine is right, cancel this log and "
             "re-import the day; if ERPNext is right, clear this flag. [{1}]"
             ).format(", ".join(changed), batch_name)
    if doc.caf_hr_review and (doc.caf_hr_review_note or "") == note:
        return
    doc.flags.ignore_permissions = True
    doc.flags.caf_system_write = True          # OD-62's sanctioned machine write
    doc.caf_hr_review = 1
    doc.caf_hr_review_note = note
    doc.save(ignore_permissions=True)


def _apply(doc, row, batch_name):
    """Write the machine's facts onto a Finger Log. Nothing derived is touched."""
    doc.ftag_id = row["ftag_id"]
    for field in ("time_in", "break", "resume", "out"):
        doc.set(field, row[field])
    doc.overtime = row["overtime"]
    doc.caf_import_batch = batch_name


# ───────────────────────────────────────────────────────────── batch plumbing

class _Batch:
    """Accumulates the manifest in memory and writes it once, at the end.

    The batch document and the Finger Logs it created commit together in one
    transaction, which is the property that matters: a run that dies leaves
    neither, so there is never a manifest describing rows that do not exist or
    rows nobody can trace.
    """

    def __init__(self, run_type, purpose, from_date, to_date, employees, source_label):
        self.doc = frappe.new_doc("Ingress Import Batch")
        self.doc.run_type = run_type
        self.doc.purpose = purpose
        self.doc.from_date = from_date
        self.doc.to_date = to_date
        self.doc.source_label = (source_label or "")[:140]
        self.doc.status = "Running"
        # The employee filter is an INPUT, recorded as text. It was briefly a
        # Table MultiSelect with its own child doctype; that was a doctype
        # earning nothing. Nobody queries "which batches named employee X" — and
        # if they did, `rows` answers it properly with real Finger Log links.
        # This field says what the run ASKED FOR; the manifest says what it
        # TOUCHED, and those are different questions.
        self.doc.employee_filter = ", ".join(employees) if employees else ""
        self.doc.flags.ignore_permissions = True
        self.doc.insert()

        self.counts = frappe._dict(
            read_rows=0, created=0, updated=0, submitted=0, held=0,
            already_present=0, skipped_no_employee=0, skipped_locked=0,
            drift=0, failed=0)
        self.notes = []

    @property
    def name(self):
        return self.doc.name

    def row(self, action, employee=None, work_date=None, finger_log=None,
            ftag_id=None, edited=None, reason=""):
        self.doc.append("rows", {
            "action": action, "employee": employee, "work_date": work_date,
            "finger_log": finger_log, "ftag_id": ftag_id,
            "adjusted_in_ingress": 1 if edited else 0,
            "reason": (reason or "")[:400],
        })

    def note(self, text):
        self.notes.append(text)

    def finish(self, status="Completed"):
        for key, value in self.counts.items():
            self.doc.set(key, value)
        self.doc.status = status
        if self.notes:
            self.doc.log = "\n".join(self.notes[:500])
        self.doc.flags.ignore_permissions = True
        self.doc.save()
        return self.doc


# ────────────────────────────────────────────────────────────── the importer

def _import(batch, rows, by_device, submit, allow_recreate):
    """The row loop. Shared by every entry point so the rules cannot diverge."""
    for row in rows:
        emp = by_device.get(row["ftag_id"])
        if not emp:
            batch.counts.skipped_no_employee += 1
            continue

        batch.counts.read_rows += 1
        day = row["work_date"]
        state, existing, detail = day_state(emp.name, day)

        # ── the day is human-owned: report, never touch ──────────────────────
        if state in (SUBMITTED, DRAFT_HUMAN, CANCELLED):
            if state == CANCELLED and allow_recreate:
                pass                    # falls through to the create path below
            else:
                action = "Skipped"
                reason = detail
                if state == SUBMITTED:
                    doc = frappe.get_doc("Finger Log", existing)
                    changed = _machine_differs(doc, row)
                    if changed:
                        # FBR8 — report, never auto-correct. The machine revising
                        # a day ERPNext already decided is a fact a human needs,
                        # not a fact the importer should act on.
                        action = "Drift"
                        batch.counts.drift += 1
                        reason = _("machine now differs on {0} — submitted log left "
                                   "untouched").format(", ".join(changed))
                        batch.note(f"DRIFT {emp.name} {day} {existing}: {', '.join(changed)}")
                        # 🔴 MG, 2026-08-17: *"where will this report live?"* — a
                        # drift buried in a batch document is a drift nobody sees.
                        # It has to reach the DOCUMENT in dispute, so flag the log
                        # itself: `caf_hr_review` already exists for exactly this
                        # and already feeds the HR appraisal dashboard's review
                        # panel (D-13 uses it for the OT cascade).
                        # `caf_system_write` is the one marker OD-62's
                        # after-submit guard lets past.
                        _flag_drift(existing, changed, batch.name)
                    else:
                        batch.counts.already_present += 1
                        continue
                else:
                    batch.counts.skipped_locked += 1
                batch.row(action, emp.name, day, existing, row["ftag_id"],
                          row["edited"], reason)
                continue

        # ── the machine's draft: update in place if anything moved ───────────
        if state == DRAFT_MACHINE:
            doc = frappe.get_doc("Finger Log", existing)
            changed = _machine_differs(doc, row)
            if not changed:
                batch.counts.already_present += 1
                continue
            sp = f"upd_{batch.counts.read_rows}"
            frappe.db.savepoint(sp)
            try:
                _apply(doc, row, batch.name)
                doc.flags.ignore_permissions = True
                doc.save()
                batch.counts.updated += 1
                batch.row("Updated", emp.name, day, doc.name, row["ftag_id"],
                          row["edited"],
                          _("machine changed {0}").format(", ".join(changed)))
            except Exception as e:
                frappe.db.rollback(save_point=sp)
                batch.counts.failed += 1
                batch.row("Failed", emp.name, day, existing, row["ftag_id"],
                          row["edited"], str(e).splitlines()[0][:300])
            continue

        # ── nothing there (or an explicitly allowed re-create): make one ─────
        sp = f"fl_{batch.counts.read_rows}"
        frappe.db.savepoint(sp)
        try:
            doc = frappe.new_doc("Finger Log")
            doc.employee = emp.name
            doc.employee_name = emp.employee_name     # from ERPNext, never Ingress
            doc.work_date = day
            _apply(doc, row, batch.name)
            doc.flags.ignore_permissions = True
            doc.insert()                              # validate() derives the rest
            batch.counts.created += 1

            reason = ""
            if row["edited"]:
                reason = _("punches edited on the machine: {0}").format(
                    ", ".join(row["edited"]))
            if state == CANCELLED:
                reason = (reason + " · " if reason else "") + _(
                    "re-created over cancelled {0} by explicit request").format(existing)

            if doc.caf_not_full_day:
                # OD-58 — an incomplete punch record may not become a verdict.
                # Left in draft for HR. Not an error.
                batch.counts.held += 1
                batch.row("Held", emp.name, day, doc.name, row["ftag_id"],
                          row["edited"],
                          (reason + " · " if reason else "") +
                          _("not a full day — left as draft for HR (OD-58)"))
            elif submit:
                sp2 = f"{sp}_sub"
                frappe.db.savepoint(sp2)
                try:
                    doc.submit()
                    batch.counts.submitted += 1
                    batch.row("Submitted", emp.name, day, doc.name, row["ftag_id"],
                              row["edited"], reason)
                except Exception as e:
                    # ⚠️ Roll back to sp2, NOT sp — the observation survives the
                    # refused submit. The draft is HR's worklist.
                    frappe.db.rollback(save_point=sp2)
                    batch.counts.held += 1
                    msg = frappe.utils.strip_html(str(e)).strip().splitlines()
                    batch.row("Held", emp.name, day, doc.name, row["ftag_id"],
                              row["edited"],
                              (reason + " · " if reason else "") +
                              (msg[0][:280] if msg else _("submit refused")))
            else:
                batch.row("Created", emp.name, day, doc.name, row["ftag_id"],
                          row["edited"], reason)
        except Exception as e:
            frappe.db.rollback(save_point=sp)
            batch.counts.failed += 1
            batch.row("Failed", emp.name, day, None, row["ftag_id"],
                      row["edited"], str(e).splitlines()[0][:300])


# ───────────────────────────────────────────────────────────── entry points

def manual_import(from_date, to_date, employees=None, submit=False,
                  purpose="Test", allow_recreate=False, source_mode=None):
    """Import a window, optionally narrowed to named employees.

    🔴 **HR Manager only, and the check lives HERE.** Found 2026-08-17 by the
    role-driven suite (S11 A3/A4): the desk wrapper was `@frappe.whitelist()` with
    no role guard, and everything below it runs `ignore_permissions = True` because
    the importer legitimately writes documents a person could not. Net effect —
    **any logged-in employee could create and SUBMIT Finger Logs and Attendance
    for the entire company.** A plain Employee got HTTP 200.

    The doctype permissions were right and meant nothing: a whitelisted method is
    its own front door. The guard sits on this function rather than only on the
    wrapper so every caller is covered — desk dialog, `reimport_day`, the CLI
    helpers, and anything added later.

    This is the surface MG asked for: pull the logs for one date or one person,
    test against them, then throw them away with `revert_batch`.

    allow_recreate — the ONE way a day HR cancelled comes back. Never set by the
    scheduled passes; only a human asking for this employee on this date.
    """
    # Importing rewrites other people's attendance. Not the employee's own act,
    # and not a supervisor's either — seniority is not the same as being HR.
    #
    # HR Manager ONLY here, while `revert_batch` and `reimport_day` also admit
    # System Manager. The asymmetry is deliberate: CREATING the company's
    # attendance is a business act that belongs to HR, whereas those two are
    # repair paths, and a stuck batch or a wrong day should not need an HR role to
    # clean up. Administrator reaches all three regardless, so nothing is
    # strandable.
    frappe.only_for("HR Manager")

    from_date, to_date = getdate(from_date), getdate(to_date)
    if to_date < from_date:
        frappe.throw(_("to_date {0} is before from_date {1}").format(to_date, from_date))

    # 🔴 TODAY IS NEVER IMPORTABLE — MG, 2026-08-17.
    #
    # A punch record for today is mid-sentence: the person has clocked in and not
    # out. Importing it would derive a day from half the facts, and because the
    # importer is allowed to UPDATE its own drafts, the wrong verdict would sit in
    # front of HR until something happened to correct it.
    #
    # The cap is refused loudly rather than silently clamped: a clamp would let
    # somebody ask for 1–17 Aug, receive 1–16, and never learn the difference.
    # Yesterday is the newest date the machine can be trusted on.
    yesterday = add_days(getdate(nowdate()), -1)
    if to_date > yesterday:
        frappe.throw(_(
            "Cannot import {0} — today's punches are still incomplete (somebody "
            "has clocked in and not out yet). The newest importable work date is "
            "{1}. Ask again with to_date = {1} or earlier."
        ).format(to_date, yesterday))

    by_device = active_by_device()
    ftag_ids = None
    if employees:
        employees = [employees] if isinstance(employees, str) else list(employees)
        by_emp = {e.name: tag for tag, e in by_device.items()}
        ftag_ids = [by_emp[e] for e in employees if e in by_emp]
        missing = [e for e in employees if e not in by_emp]
        if missing:
            frappe.throw(_(
                "No Attendance Device ID on: {0}. Ingress can only be matched by "
                "device id, so these employees have no machine rows to import."
            ).format(", ".join(missing)))

    # 🔴 The batch is created BEFORE the machine is touched, and the order is the
    # point. It used to probe first and `throw` on failure — so an unreachable
    # machine produced an exception and NO RECORD AT ALL. For a desk click that is
    # survivable (a human reads the message); for the Phase-2 scheduled passes it
    # is precisely the silent failure this feature exists to prevent (§6.5 blocker
    # 7): a cron job that throws leaves nothing behind to notice.
    #
    # Found the honest way, 2026-08-17: Natalie went off the network mid-session
    # (HR shut the PC down after making the test edits) and four runs produced
    # four tracebacks and zero batches.
    reader = src.get_source(source_mode)
    batch = _Batch("Manual", purpose, from_date, to_date, employees,
                   f"{source_mode or 'configured'} (connecting…)")
    try:
        label = reader.describe()
        batch.doc.source_label = label[:140]

        # 🔴 Has Ingress caught up with its own devices? Measured 2026-08-18:
        # `attendance` is materialised when Ingress processes a date range, not
        # per tap, so a day can hold an IN and no OUT purely because nobody has
        # refreshed it yet. Importing then gives ERPNext half a day.
        #
        # Reported, NOT refused — the same rule the rest of this module follows.
        # Refusing would block HR on a judgement only she can make (an old day
        # with a trailing tap is usually fine; yesterday evening is usually not),
        # and OD-58 already holds an incomplete day as a draft rather than
        # submitting a wrong verdict. She needs to KNOW, not to be stopped.
        if hasattr(reader, "unprocessed_dates"):
            stale = reader.unprocessed_dates(from_date, to_date)
            for s in stale:
                batch.note(
                    f"⚠️ NOT PROCESSED BY INGRESS: {s['work_date']} — last tap "
                    f"{s['last_tap']}, attendance last written "
                    f"{s['attendance_written']}. Punches after that are NOT in "
                    f"this import. Refresh the day in Ingress, then re-import.")
            batch.doc.unprocessed_dates = "\n".join(
                f"{s['work_date']}: taps to {s['last_tap']}, "
                f"processed to {s['attendance_written']}" for s in stale)
    except Exception as e:
        detail = frappe.utils.strip_html(str(e))[:300]
        batch.note(f"SOURCE UNREACHABLE: {detail}")
        batch.finish("Failed")
        frappe.db.commit()
        frappe.throw(_("Ingress source unreachable: {0}<br><br>Recorded as batch "
                       "{1}.").format(detail, batch.name))

    # D-15 — the Finger Log on_submit doc_event skips its appraisal refresh while
    # this flag is set, so a batch does not refresh per row. Reset in `finally`:
    # an exception escaping mid-batch must not leave it set for the next caller
    # in the same process.
    frappe.flags.in_import = True
    try:
        _import(batch, reader.read(from_date, to_date, ftag_ids), by_device,
                submit, allow_recreate)
        doc = batch.finish("Completed")
    except Exception as e:
        batch.note(f"RUN FAILED: {e}")
        doc = batch.finish("Failed")
        frappe.db.commit()
        raise
    finally:
        frappe.flags.in_import = False

    frappe.db.commit()
    # `unprocessed_dates` is returned, not just stored: the desk dialog raises it
    # in red, because a day Ingress has not finished building imports as HALF a day
    # and is indistinguishable from an ordinary held draft. Anyone who has to think
    # to go and open the batch record will not (FBR49).
    return {"batch": doc.name, "status": doc.status, "counts": dict(batch.counts),
            "unprocessed_dates": doc.get("unprocessed_dates") or ""}


@frappe.whitelist()
def check_amendments(since=None, update_watermark=1):
    """Which already-imported days has somebody edited on the machine since?

    🔴 **This is what FBR44 makes necessary.** With no scheduled fetch, an Ingress
    amendment to a day ERPNext has already imported is invisible **forever** —
    nothing re-reads that date unless HR happens to ask for it by hand, and she has
    no way of knowing which date to ask for. Measured 2026-08-17: **543 rows** were
    revised in August carrying work dates back to January, so this is a real
    population, not a theoretical one.

    It REPORTS and changes nothing. That is the whole design: it tells HR which
    days moved and what each one needs, and she decides. Re-importing on her behalf
    would be the auto-refresh FBR39 exists to avoid, one layer down.

    The watermark is the MACHINE's clock, never this server's — comparing a
    timestamp written on Natalie against `now()` here loses every row inside the
    clock difference between the two hosts.
    """
    frappe.only_for("HR Manager")

    from caf.caf.doctype.ingress_sync_settings.ingress_sync_settings import get_settings

    settings = get_settings()
    reader = src.get_source(None, settings)
    if not hasattr(reader, "read_revised_since"):
        frappe.throw(_("Amendment checking needs the live machine — a snapshot has "
                       "no lastupdate history."))

    since = since or settings.get("last_amendment_check")
    if not since:
        frappe.throw(_(
            "No watermark yet, so there is nothing to compare against. Pass an "
            "explicit date to start from — the first import date is the usual "
            "choice — and this will record where it got to for next time."))

    try:
        machine_now = reader.clock()
    except Exception as e:
        frappe.throw(_("Ingress source unreachable: {0}").format(
            frappe.utils.strip_html(str(e))[:200]))

    by_device = active_by_device()
    findings, seen = [], 0
    for row in reader.read_revised_since(since):
        seen += 1
        emp = by_device.get(str(row["ftag_id"]))
        if not emp:
            continue                      # not an active mapped employee
        day = row["work_date"]
        # day_state returns (state, finger_log, detail) — the same ownership
        # verdict `_import` acts on, so this report cannot drift from the importer.
        state, existing, _detail = day_state(emp.name, day)

        if state == NONE:
            verdict, action = "Never imported", _("import this day")
        elif state == CANCELLED:
            verdict, action = "Cancelled in ERPNext", _(
                "re-import only if this day should come back")
        elif state == SUBMITTED:
            doc = frappe.get_doc("Finger Log", existing)
            changed = _machine_differs(doc, row)
            if not changed:
                continue                  # submitted and still agrees — silent
            verdict = "SUBMITTED — punches differ ({0})".format(", ".join(changed))
            action = _("cancel the Finger Log, then Re-import from Ingress")
        elif state == DRAFT_HUMAN:
            verdict, action = "Draft, edited by a person", _(
                "check with whoever edited it before re-importing — a re-import "
                "would discard their change")
        else:                             # MACHINE_DRAFT
            verdict, action = "Draft", _("re-import — the draft updates in place")

        findings.append({
            "employee": emp.name, "employee_name": emp.employee_name,
            "ftag_id": row["ftag_id"], "work_date": str(day),
            "finger_log": existing, "verdict": verdict, "what_to_do": action,
            "machine_changed_at": str(row.get("lastupdate") or ""),
            "adjusted_in_ingress": 1 if row.get("edited") else 0,
        })

    if int(update_watermark or 0):
        frappe.db.set_value("Ingress Sync Settings", "Ingress Sync Settings",
                            "last_amendment_check", machine_now,
                            update_modified=False)
        frappe.db.commit()

    findings.sort(key=lambda f: (not f["verdict"].startswith("SUBMITTED"),
                                 f["work_date"]))
    return {
        "checked_since": str(since),
        "machine_clock_now": str(machine_now),
        "machine_rows_revised": seen,
        "needs_attention": len(findings),
        "submitted_conflicts": sum(1 for f in findings
                                   if f["verdict"].startswith("SUBMITTED")),
        "findings": findings,
    }


@frappe.whitelist()
def reimport_day(finger_log=None, employee=None, work_date=None, submit=0):
    """The "Re-import from Ingress" button — one employee, one date.

    🔴 The scenario this exists for: the punches in ERPNext are wrong. Amend
    cannot fix that — every punch field is read_only, so HR cannot type a
    correction, and `copy_doc` would faithfully carry the wrong values forward.
    The machine is the single source of punch facts (FDR10), so the only honest
    repair is to read it again.

    When the punches are RIGHT and something around them was wrong — the OT
    approval, the shift — amend is the route, not this.
    """
    frappe.only_for(("System Manager", "HR Manager"))

    if finger_log:
        employee, work_date = frappe.db.get_value(
            "Finger Log", finger_log, ["employee", "work_date"])
    if not (employee and work_date):
        frappe.throw(_("Need either a Finger Log, or an employee and a work date."))

    state, existing, detail = day_state(employee, work_date)
    if state in (SUBMITTED, DRAFT_HUMAN):
        frappe.throw(_(
            "{0} on {1} is {2} ({3}). Cancel it first — a re-import replaces what "
            "the machine saw, and this document is not the machine's to replace."
        ).format(employee, work_date, detail, existing), title=_("Day is human-owned"))

    return manual_import(work_date, work_date, employees=[employee],
                         submit=bool(int(submit or 0)), purpose="Production",
                         allow_recreate=True)


def revert_batch(batch_name: str, force: bool = False):
    """Undo a batch — cancel and delete every Finger Log it created.

    🔴 Two refusals, both deliberate:
      · a Finger Log somebody else has modified is NOT deleted. Somebody is
        working against it, and a revert that destroys their work is worse than
        one that stops and says so.
      · a `Production` batch is not reverted without an explicit force. This
        button exists for test fixtures, not for last week's payroll input.

    Order matters: cancel first, which runs `FingerLog.on_cancel` and cascades
    the Attendance down (`ignore_links` + `cancel_attendance`), THEN delete. The
    reverse order hits stock's link guard and fails.
    """
    frappe.only_for(("System Manager", "HR Manager"))

    batch = frappe.get_doc("Ingress Import Batch", batch_name)

    if batch.status == "Reverted":
        frappe.throw(_("Batch {0} is already reverted.").format(batch_name))

    if batch.purpose == "Production" and not force:
        frappe.throw(_(
            "Batch {0} is a Production run. Reverting it would cancel and DELETE "
            "{1} Finger Logs and their Attendance. Pass force to proceed."
        ).format(frappe.bold(batch_name), batch.created),
            title=_("Production batch"))

    removed, refused, missing, attendance_removed = [], [], [], []

    # Reverse creation order: the newest documents are the ones most likely to
    # be linked from something else.
    for row in sorted(batch.rows, key=lambda r: r.idx, reverse=True):
        if not row.finger_log:
            continue
        if not frappe.db.exists("Finger Log", row.finger_log):
            # Somebody else already removed it — most often an EARLIER batch that
            # created the same day and was reverted first. The link must still be
            # cleared or this batch can never be saved again: Frappe validates
            # child links on every save, including the ones we are only reporting
            # on. Two batches can legitimately name the same Finger Log.
            missing.append(row.finger_log)
            row.reason = _("already gone: {0} · {1}").format(
                row.finger_log, row.reason or "")[:400]
            row.finger_log = None
            continue

        doc = frappe.get_doc("Finger Log", row.finger_log)

        if doc.caf_import_batch != batch_name and not force:
            refused.append(f"{doc.name} (now owned by batch {doc.caf_import_batch})")
            continue
        if doc.modified_by != doc.owner and not force:
            refused.append(f"{doc.name} (modified by {doc.modified_by})")
            continue

        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.reload()
            doc.cancel()                    # cascades the Attendance down
        frappe.delete_doc("Finger Log", doc.name, ignore_permissions=True,
                          force=True, delete_permanently=True)
        removed.append(doc.name)

        # 🔴 `cancel_attendance` CANCELS, it does not delete — correct for an
        # ordinary FL cancel, where the trail must survive (spec §6.6). But we
        # have just erased the Finger Log itself, so those cancelled rows are
        # orphans pointing at a document that no longer exists, and the batch
        # would not be undone at all: a revert left 9 of them behind the first
        # time this ran. If the observation is gone, its verdict goes with it.
        for att in frappe.get_all("Attendance",
                                  filters={"caf_finger_log": doc.name},
                                  fields=["name"]):
            frappe.delete_doc("Attendance", att.name, ignore_permissions=True,
                              force=True, delete_permanently=True)
            attendance_removed.append(att.name)

        # ⚠️ The link must be CLEARED, not left pointing at a deleted document.
        # Frappe validates child-table links on every save, so a manifest still
        # naming the rows it just deleted makes the batch unsaveable —
        # `LinkValidationError: Could not find Row #1: Finger Log: ...`, which
        # rolled the whole revert back the first time this ran. The name moves
        # into `reason`, so the trail survives as text where a link cannot.
        row.action = "Reverted"
        row.reason = _("deleted {0} · {1}").format(doc.name, row.reason or "")[:400]
        row.finger_log = None

    still = frappe.get_all("Finger Log", filters={"caf_import_batch": batch_name},
                           fields=["name"])
    batch.status = "Reverted" if not still else batch.status
    batch.log = ((batch.log or "") + "\n" + _(
        "REVERTED {0}: removed {1} logs + {2} attendance, refused {3}, "
        "already gone {4}").format(now_datetime(), len(removed),
                                   len(attendance_removed), len(refused),
                                   len(missing)))[:100000]
    if refused:
        batch.log += "\n" + "\n".join(f"  refused: {r}" for r in refused[:50])
    batch.flags.ignore_permissions = True
    batch.save()
    frappe.db.commit()

    return {"batch": batch_name, "status": batch.status, "removed": len(removed),
            "attendance_removed": len(attendance_removed), "refused": refused,
            "already_gone": len(missing),
            "still_linked": [s.name for s in still]}


# ───────────────────────────────────────────────────── bench-friendly wrappers
# ⚠️ `bench execute --kwargs "{...}"` is unusable from PowerShell (ParserError on
# the colon — protocol §1). These take positional --args only.

def cli_import(from_date, to_date, employee=None, submit="0", purpose="Test"):
    out = manual_import(from_date, to_date,
                        employees=[employee] if employee else None,
                        submit=str(submit) in ("1", "True", "true"),
                        purpose=purpose)
    print(json.dumps(out, indent=2, default=str))
    return out


def cli_revert(batch_name, force="0"):
    out = revert_batch(batch_name, force=str(force) in ("1", "True", "true"))
    print(json.dumps(out, indent=2, default=str))
    return out
