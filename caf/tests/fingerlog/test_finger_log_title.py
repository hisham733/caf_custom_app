"""The Finger Log title — and the reason it is a title and not the name.

    bench --site <site> execute caf.tests.fingerlog.test_finger_log_title.run

MG asked for `2026-08-03-<device_id>` as the document NAME, so a log could be
cross-checked against Ingress at a glance. The rename measured clean (0
collisions, `rename_doc` carries everything), and it was still refused for one
reason, which is what this suite exists to keep true:

    the device id is MUTABLE, and a name is forever.

So the device id lives in `caf_title`, the doctype's `title_field` (FBR67). Three
things must hold, and each has a test here because each is a way the idea could
quietly stop working:

  FLT1..FLT2   the title exists on every log, draft and submitted
  FLT3..FLT4   🔴 it reads `ftag_id` — the value Ingress recorded ON THE DAY —
               and NOT `Employee.attendance_device_id`, which moves. FLT4 is the
               one that matters: it forces them apart and proves which wins
  FLT5..FLT8   the desk actually uses it, it degrades safely, and the NAME is
               demonstrably not already the device id — which is the whole
               confusion the title removes

Self-cleaning: builds one throwaway log in June, removes it in `finally`.
⚠️ June, not July — July holds imported logs (tests/CLAUDE.md).
"""

import frappe

from caf.caf.doctype.finger_log.finger_log import compose_title

RESULTS = []
D_LOG = "2026-06-03"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:24s} {'PASS' if ok else 'FAIL'}  {detail}")


def _make(emp, ftag):
    doc = frappe.new_doc("Finger Log")
    doc.employee = emp
    doc.employee_name = frappe.db.get_value("Employee", emp, "employee_name")
    doc.work_date = D_LOG
    doc.ftag_id = ftag
    for f in ("time_in", "break", "resume", "out"):
        doc.set(f, "00:00:00")
    doc.overtime = 0
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


def run():
    frappe.set_user("Administrator")
    made = []
    try:
        emp, dev = frappe.db.get_value(
            "Employee",
            {"status": "Active", "attendance_device_id": ("!=", "")},
            ["name", "attendance_device_id"],
        )

        for old in frappe.get_all("Finger Log",
                                  filters={"employee": emp, "work_date": D_LOG}):
            frappe.delete_doc("Finger Log", old.name, force=True,
                              ignore_permissions=True)

        # ── FLT1 — a draft has a title the moment it is saved ──────────────
        doc = _make(emp, dev)
        made.append(doc.name)
        want = f"{D_LOG} · {dev} · {doc.employee_name}"
        check("FLT1-DRAFT-HAS-TITLE", doc.caf_title == want,
              f"a freshly inserted DRAFT already reads {doc.caf_title!r}. It is set "
              f"in validate() outside the `docstatus != 1` guard, because a "
              f"title_field that only appears after submission leaves HR's draft "
              f"queue — the one place they most need to identify a row — unlabelled")

        # ── FLT2 — and it survives submission ──────────────────────────────
        doc.submit()
        doc.reload()
        check("FLT2-SURVIVES-SUBMIT", doc.caf_title == want,
              f"still {doc.caf_title!r} after submit. Submitting re-runs validate(), "
              f"so a title built from set_only_once inputs cannot disagree with "
              f"itself across the transition")

        # ── FLT3 — the three inputs are the ones that cannot move ──────────
        meta = frappe.get_meta("Finger Log")
        frozen = [f for f in ("work_date", "ftag_id", "employee_name")
                  if meta.get_field(f).set_only_once]
        check("FLT3-INPUTS-FROZEN", len(frozen) == 3,
              f"all three title inputs carry set_only_once: {frozen}. That is what "
              f"makes the title reproducible — recomputing it on any future save "
              f"gives the same string, so it can never silently rewrite history")

        # ── FLT4 — 🔴 the whole argument, forced ───────────────────────────
        # Move the employee onto a different reader and prove the title does NOT
        # follow. If this ever fails, the title has the same defect as the rename
        # and the reason for choosing it has evaporated.
        other = "999999"
        frappe.db.set_value("Employee", emp, "attendance_device_id", other,
                            update_modified=False)
        try:
            fresh = frappe.get_doc("Finger Log", doc.name)
            fresh.caf_hr_review_note = "title re-read probe"
            fresh.flags.ignore_permissions = True
            fresh.save()
            fresh.reload()
            live = frappe.db.get_value("Employee", emp, "attendance_device_id")
            check("FLT4-READS-FTAG-NOT-EMPLOYEE",
                  fresh.caf_title == want and str(live) == other
                  and other not in (fresh.caf_title or ""),
                  f"the employee is now on reader {live}, and the log still reads "
                  f"{fresh.caf_title!r} — the device Ingress recorded on {D_LOG}. "
                  f"🔴 THIS IS THE REASON THE RENAME WAS REFUSED: had the device id "
                  f"gone into `name`, this row would now claim reader {other} for a "
                  f"day it was never used, and the Ingress cross-check would be "
                  f"quietly wrong instead of loudly absent")
        finally:
            frappe.db.set_value("Employee", emp, "attendance_device_id", dev,
                                update_modified=False)

        # ── FLT5 — the desk is actually told to use it ─────────────────────
        check("FLT5-DESK-USES-TITLE",
              meta.title_field == "caf_title" and meta.show_title_field_in_link,
              f"title_field={meta.title_field!r} and show_title_field_in_link="
              f"{meta.show_title_field_in_link} — so the list view heading AND every "
              f"Link dropdown that points at a Finger Log show the title. Setting "
              f"the field without these two is a column nobody looks at")

        # ── FLT6 — it degrades rather than crashes ─────────────────────────
        check("FLT6-DEGRADES-SAFELY",
              compose_title(None, None, None) == "????-??-?? · no device · ?",
              f"missing inputs give {compose_title(None, None, None)!r} instead of "
              f"raising. compose_title runs inside validate() on EVERY save, "
              f"including the importer's thousands — a TypeError here would stop an "
              f"import, and a display value is never worth that")

        # ── FLT7 — 🔴 the name is NOT already the device id ────────────────
        # `autoname` is <work_date>-<3-digit daily series>. Device ids are 3-digit
        # numbers in the same range, so the name READS like the thing MG wanted.
        rows = frappe.db.sql(
            """SELECT name, ftag_id FROM `tabFinger Log`
               WHERE ftag_id IS NOT NULL AND ftag_id <> '' LIMIT 500""",
            as_dict=True)
        looks_like, actually_is = 0, 0
        for r in rows:
            tail = r.name.rsplit("-", 1)[-1]
            if tail.isdigit():
                looks_like += 1
                if str(int(tail)) == str(r.ftag_id):
                    actually_is += 1
        check("FLT7-NAME-IS-NOT-DEVICE",
              looks_like > 0 and actually_is < looks_like,
              f"of {looks_like} names ending in a number, only {actually_is} happen "
              f"to match that log's device id. The name is the Nth log OF THAT DAY, "
              f"not a device — `2026-07-01-232` is log 232 and belongs to device "
              f"385. This coincidence of shape is exactly why HR needed a title")

        # ── FLT8 — every existing log carries one ──────────────────────────
        missing = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabFinger Log` WHERE caf_title IS NULL OR caf_title=''"
        )[0][0]
        check("FLT8-BACKFILLED", missing == 0,
              f"{missing} logs without a title. The backfill "
              f"(caf.scripts.finger_log_title_backfill) has to have run, or the "
              f"list view shows a blank heading for every row that predates the "
              f"field — worse than the misleading name it replaced")

    finally:
        frappe.set_user("Administrator")
        for n in made:
            if frappe.db.exists("Finger Log", n):
                d = frappe.get_doc("Finger Log", n)
                if d.docstatus == 1:
                    d.flags.ignore_permissions = True
                    d.cancel()
                frappe.delete_doc("Finger Log", n, force=True,
                                  ignore_permissions=True)
        frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
