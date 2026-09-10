"""Cancel Attendance rows that no Finger Log and no Leave Application produced.

    bench --site <site> execute caf.scripts.stray_attendance_cleanup.run
    bench --site <site> execute caf.scripts.stray_attendance_cleanup.run --kwargs "{'apply':1}"
    bench --site <site> execute caf.scripts.stray_attendance_cleanup.verify

WHY THIS EXISTS
---------------
🔴 **FBR69: ERPNext holds exactly ONE source of attendance** — the Finger Log,
plus pre-approved leave. When the machine is down, HR writes on paper and keys it
into **INGRESS**; the escape hatch is upstream. That is why stock's *Mark
Attendance* button was deliberately left unguarded rather than blocked — there is
no CAF scenario that needs it.

⚠️ But it was reachable, and it was used. MG's manual pass on **2026-08-19**
(`MG_LLM_ui_touch up.md`, item 6): *"tested with Too — button 'Mark Attendance'
is visible — able to use it to mark attendance for Ow Yong Mian Fatt —
HR-ATT-2026-11277"*. `too@` holds **no HR role**; the likely closer since is
`retire_hr_user_role`, which took HR User from 32 holders to 3. **Measured
2026-09-10: he cannot do it today** — `create=False write=False cancel=False`.

So two submitted Attendance rows sit on a **director's** record, produced by
neither of FBR69's two sources. MG, 2026-09-10, deciding ⑮: *"cancelling them."*

WHY CANCEL AND NOT DELETE
-------------------------
A cancelled document keeps its number, its owner and its history, so the record
of what happened survives. Deleting would erase the only evidence that the gap
was ever open — and this file plus the cancellation Comment are what stop it
being rediscovered as a mystery.

⚠️ **Attendance cannot be AMENDED at all** (`amend = 0` for every role; measured:
0 of 5,353 rows have ever been amended), so cancel is the whole of the operation.

WHAT IT WILL NOT TOUCH
----------------------
🔴 Only rows that are **submitted**, carry **no `leave_application`**, and have
**no Finger Log** for the same employee and date. A row either of FBR69's sources
produced is left alone, however odd it looks — this script removes what the
framework cannot explain, not what somebody dislikes.

⚠️ Attendance is transactional and does NOT migrate to production (MG, 2026-09-10),
so this is a test-server tidy. It is written as a script anyway because it changes
submitted documents on a real person's record.
"""

import frappe

# The rows MG approved. Named explicitly rather than discovered by pattern: a
# script that decides for itself which of a director's attendance records to
# cancel is not one anybody should run twice.
TARGETS = ("HR-ATT-2026-11277", "HR-ATT-2026-11278")

REASON = ("Cancelled 2026-09-10 (MG, decision ⑮). Created by too@caffood.com on "
          "2026-08-19 through stock's Mark Attendance button during manual "
          "testing. Neither a Finger Log nor a Leave Application produced it, so "
          "it is not one of FBR69's two sources of attendance.")


def _rows():
    out = []
    for name in TARGETS:
        doc = frappe.db.get_value(
            "Attendance", name,
            ["name", "employee", "employee_name", "attendance_date", "status",
             "docstatus", "leave_application", "owner"], as_dict=True)
        if not doc:
            out.append({"name": name, "state": "not on this site"})
            continue
        fl = frappe.db.exists("Finger Log", {"employee": doc.employee,
                                             "work_date": doc.attendance_date})
        doc["finger_log"] = fl or ""
        doc["state"] = (
            "already cancelled" if doc.docstatus == 2
            else "DRAFT — not submitted, nothing to cancel" if doc.docstatus == 0
            else "PROTECTED: a Leave Application owns this day" if doc.leave_application
            else f"PROTECTED: Finger Log {fl} covers this day" if fl
            else "stray — will cancel")
        out.append(doc)
    return out


def run(apply=0):
    rows = _rows()
    print("=" * 78)
    for r in rows:
        if "employee" not in r:
            print(f"  {r['name']}  {r['state']}")
            continue
        print(f"  {r['name']}  {r.get('employee_name') or r['employee']}  "
              f"{r['attendance_date']}  status={r['status']}  "
              f"docstatus={r['docstatus']}  owner={r['owner']}")
        print(f"      leave_application={r['leave_application'] or '(none)'}  "
              f"finger_log={r['finger_log'] or '(none)'}")
        print(f"      -> {r['state']}")

    doable = [r for r in rows if r.get("state") == "stray — will cancel"]
    if not apply:
        print(f"\n🔴 Nothing was written. {len(doable)} row(s) would be cancelled.")
        return {"would_cancel": [r["name"] for r in doable]}

    done = []
    for r in doable:
        doc = frappe.get_doc("Attendance", r["name"])
        doc.flags.ignore_permissions = True
        doc.cancel()
        # OD-26 — db writes leave no Version, and a cancellation on somebody's
        # attendance record must say who and why in a place a human will read.
        doc.add_comment("Comment", REASON)
        done.append(r["name"])
    frappe.db.commit()
    print(f"\ncancelled {len(done)}: {', '.join(done) or '(none)'}")
    return {"cancelled": done}


def verify():
    """Both directions: the strays are gone, and nothing else moved."""
    rows = _rows()
    still_open = [r["name"] for r in rows
                  if r.get("docstatus") == 1]
    protected = [r["name"] for r in rows
                 if str(r.get("state", "")).startswith("PROTECTED")]

    total = frappe.db.count("Attendance")
    submitted = frappe.db.count("Attendance", {"docstatus": 1})
    print(f"targets still submitted : {still_open or 'none'}")
    print(f"targets protected       : {protected or 'none'}")
    print(f"Attendance rows on site : {total} ({submitted} submitted)")
    ok = not still_open
    print("PASS" if ok else "FAIL — a target is still submitted")
    return {"ok": ok, "still_open": still_open, "total": total}
