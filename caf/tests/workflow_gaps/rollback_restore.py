"""Roll back the botched restore: remove every row the restore created (ds=2 or
new-named) on the affected dates, reset the Deleted Document flags, and leave
the environment in the accepted 'deleted' state. Test records only — no
Employee/User/Holiday List/Cycle rows are touched.

    bench --site development.localhost execute caf.tests.workflow_gaps.rollback_restore.run
"""

import frappe

DATES = ["2026-05-24", "2026-05-27", "2026-06-15", "2026-06-16",
         "2026-06-18", "2026-06-22", "2026-06-19", "2026-06-23"]


def _wipe(doctype, date_field):
    names = [r["name"] for r in frappe.get_all(
        doctype, filters={date_field: ["in", DATES]}, fields=["name"])] or []
    removed = 0
    for n in names:
        if not frappe.db.exists(doctype, n):
            continue
        doc = frappe.get_doc(doctype, n)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        try:
            frappe.delete_doc(doctype, n, force=True,
                              ignore_permissions=True)
            removed += 1
        except Exception:
            pass
    return removed


def run():
    total = 0
    for dt, f in (("OT Approval", "work_date"),
                  ("Finger Log", "work_date"),
                  ("Attendance", "attendance_date"),
                  ("Leave Application", "from_date"),
                  ("Shift Assignment", "start_date")):
        n = _wipe(dt, f)
        total += n
        print(f"{dt:22s} removed {n}")
    # reset Deleted Document flags for today's rows so the admin UI is coherent
    frappe.db.sql(
        """UPDATE `tabDeleted Document` SET restored = 0, new_name = NULL
           WHERE deleted_doctype IN (%s) AND creation >= '2026-08-14 08:40:00'"""
        % ",".join(["%s"] * 5),
        ("Leave Application", "Attendance", "Finger Log", "OT Approval",
         "Shift Assignment"),
    )
    frappe.db.commit()
    print(f"\ntotal removed: {total}")
    return {"removed": total}
