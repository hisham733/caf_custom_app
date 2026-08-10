"""Server-side fixture purge for the Finger Log suites.

    bench --site <site> execute caf.tests.fingerlog.purge.run

WHY THIS IS NOT DONE OVER REST
------------------------------
Chunk 3 made `Attendance.caf_finger_log` link back to the Finger Log. Stock then
refuses to **cancel or delete** the log while that Attendance exists
(`frappe/model/delete_doc.py` — the Work Order / Stock Entry guard, spec §6.3),
and the escape hatch is `doc.flags.ignore_links = True`, **which cannot be set
over HTTP**. Setting it inside `on_cancel` is too late: the guard runs first.

So a REST-only cleanup leaves a SUBMITTED log behind, and because
`check_previous_submission()` filters `docstatus = 1`, the very next run fails
its insert — surfacing as a `405` built from a null document name, which looks
like anything but a leftover.

⚠️ SCOPED ON PURPOSE. It only removes rows for the employees and dates handed to
it. An earlier revision purged every log for the fixture employees whatever the
date, and ate ~50 rows of imported production data on its first run after the
Chunk 3 importer landed. **A test fixture must never be able to delete data it
did not create.**
"""

import frappe

# The Chunk 2b / Chunk 3 fixture employees and dates.
EMPLOYEES = [
    "HR-EMP-00016",   # 8am Schedule, OT eligible
    "HR-EMP-00011",   # 8:30am Schedule, caf_allow_ot = 0
    "HR-EMP-00002",   # no default shift
    "HR-EMP-00127",   # Mon-Fri
    "HR-EMP-00003",   # rest-Saturday assignments
    "HR-EMP-00042",   # rest-day OT
    "HR-EMP-00001",   # no-lunch shift
]

DATES = ["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12",
         "2026-03-21", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]

MARKER = "%CHUNK2B TEST%"


def _remove(doctype, name):
    if not frappe.db.exists(doctype, name):
        return True
    try:
        doc = frappe.get_doc(doctype, name)
        doc.flags.ignore_links = True          # the whole reason this is server-side
        doc.flags.ignore_permissions = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
        return True
    except Exception as e:
        print(f"   stuck: {doctype} {name}: {str(e).splitlines()[0][:90]}")
        return False


def run(employees=None, dates=None, extra_dates=None):
    employees = employees or EMPLOYEES
    dates = list(dates or DATES) + list(extra_dates or [])

    # Any Shift Assignment date is a fixture date too - C1 and E3 derive theirs.
    for sa in frappe.get_all("Shift Assignment",
                             filters={"employee": ("in", employees), "docstatus": 1},
                             fields=["start_date"], limit_page_length=0):
        dates.append(str(sa.start_date))
    dates = sorted(set(dates))

    logs = frappe.get_all("Finger Log",
                          filters={"employee": ("in", employees),
                                   "work_date": ("in", dates)},
                          fields=["name"], limit_page_length=0)

    stuck = 0
    for log in logs:
        for att in frappe.get_all("Attendance", filters={"caf_finger_log": log.name},
                                  fields=["name"]):
            if not _remove("Attendance", att.name):
                stuck += 1
        if not _remove("Finger Log", log.name):
            stuck += 1

    for ot in frappe.get_all("OT Approval", filters={"reason": ("like", MARKER)},
                             fields=["name"], limit_page_length=0):
        if not _remove("OT Approval", ot.name):
            stuck += 1

    frappe.db.commit()

    left = frappe.db.count("Finger Log", {"employee": ("in", employees),
                                          "work_date": ("in", dates)})
    print(f"purged {len(logs)} finger log(s); {left} remain; {stuck} stuck")
    return {"removed": len(logs), "remaining": left, "stuck": stuck}
