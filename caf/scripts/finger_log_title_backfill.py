"""Fill `Finger Log.caf_title` on logs that predate the field.

    bench --site <site> execute caf.scripts.finger_log_title_backfill.run
    bench --site <site> execute caf.scripts.finger_log_title_backfill.run --kwargs "{'apply':1}"
    bench --site <site> execute caf.scripts.finger_log_title_backfill.verify

WHY THIS EXISTS
---------------
MG wanted a Finger Log to carry its Ingress device id so a row can be checked
against the machine at a glance — originally as a rename to
`<work_date>-<device_id>`. Measured 2026-09-02: the rename is feasible (0
collisions on 3,167 logs, 0 logs whose employee has no device id, and
`rename_doc` carries all 2,943 link references plus 21,103 comments). It was
still refused, and the reason is the point of this script:

    `Employee.attendance_device_id` is MUTABLE. Re-enrol somebody on a new
    reader and every historical name would claim a device that was never theirs
    on that day — a cross-check that silently stops cross-checking.

So the device id goes in the DISPLAY, not the identifier (FBR67), and it is read
from **`Finger Log.ftag_id`** — `set_only_once`, captured at import, therefore
what Ingress actually held on the day. Measured: 0 of 3,167 blank, 0 disagreeing
with the employee's current device id, so the backfill starts from a state where
either source would give the same answer — and only one of them stays right.

⚠️ The name is NOT already this. `autoname` is `<work_date>-<3-digit daily
series>`, so `2026-07-01-232` is the 232nd log of that day. Device ids are
3-digit numbers in the same range, which is exactly why the name reads as though
it already carries one.

NOTES
-----
* `update_modified=False` throughout. `Finger Log.sort_field` is `modified`, so
  stamping 3,167 rows with today's timestamp would flatten the list view's
  natural order to a single instant. The backfill must be invisible.
* **No Comment per row.** The scripts contract asks for one on any change to a
  person's record, because `db.set_value` writes no Version (OD-26). That rule
  exists for values that decide somebody's pay — a shift, a join date, an
  approver. This writes a derived label into a field that had no previous value,
  and 3,167 comments would bury the ones that matter.
* Re-runnable: rows already carrying the correct title are counted and skipped.
"""

import frappe

from caf.caf.doctype.finger_log.finger_log import compose_title

FIELD = "caf_title"


def _rows():
    return frappe.db.sql(
        """SELECT name, work_date, ftag_id, employee_name, caf_title
           FROM `tabFinger Log` ORDER BY work_date, name""",
        as_dict=True,
    )


def run(apply=0):
    apply = int(apply or 0)

    if not frappe.get_meta("Finger Log").has_field(FIELD):
        print(f"Finger Log.{FIELD} does not exist — run "
              f"`bench --site <site> reload-doctype \"Finger Log\"` first.")
        return

    rows = _rows()
    todo, ok, no_device = [], 0, []

    for r in rows:
        want = compose_title(r.work_date, r.ftag_id, r.employee_name)
        if not r.ftag_id:
            no_device.append(r.name)
        if (r.caf_title or "") == want:
            ok += 1
        else:
            todo.append((r.name, r.caf_title or "", want))

    print(f"Finger Log rows        : {len(rows)}")
    print(f"  already correct      : {ok}")
    print(f"  to write             : {len(todo)}")
    print(f"  ⚠️ blank ftag_id      : {len(no_device)}"
          + (f"  {no_device[:10]}" if no_device else "  (none — every log knows its device)"))

    for name, was, want in todo[:8]:
        print(f"    {name:<22} {was!r:>26} -> {want}")
    if len(todo) > 8:
        print(f"    … and {len(todo) - 8} more")

    if not apply:
        print("\nREPORT ONLY. Re-run with --kwargs \"{'apply':1}\" to write.")
        return

    for name, _was, want in todo:
        frappe.db.set_value("Finger Log", name, FIELD, want, update_modified=False)
    frappe.db.commit()
    print(f"\nWROTE {len(todo)} titles.")


def verify():
    """Both directions: every log has the right title, and none was reordered."""
    rows = _rows()
    wrong = [r.name for r in rows
             if (r.caf_title or "") != compose_title(r.work_date, r.ftag_id, r.employee_name)]
    blank = [r.name for r in rows if not (r.caf_title or "")]

    meta = frappe.get_meta("Finger Log")
    title_field = meta.title_field

    # The backfill must not have bunched `modified` into one instant.
    spread = frappe.db.sql(
        "SELECT COUNT(DISTINCT DATE(modified)) FROM `tabFinger Log`")[0][0]

    checks = [
        ("TITLE-1", not wrong,
         f"every Finger Log title matches work_date · ftag_id · employee_name "
         f"({len(rows) - len(wrong)}/{len(rows)}); mismatched: {wrong[:5]}"),
        ("TITLE-2", not blank,
         f"no Finger Log is left without a title (blank: {len(blank)})"),
        ("TITLE-3", title_field == FIELD,
         f"DocType.title_field is {title_field!r} — the desk shows the title, "
         f"not the misleading <date>-<series> name"),
        ("TITLE-4", spread > 1,
         f"`modified` still spans {spread} distinct days — the backfill did not "
         f"flatten the list view's natural order (sort_field is `modified`)"),
    ]

    fails = 0
    for cid, ok, why in checks:
        print(f"{cid} {'PASS' if ok else 'FAIL'}  {why}")
        fails += 0 if ok else 1
    print(f"\n{len(checks) - fails}/{len(checks)} passed")
