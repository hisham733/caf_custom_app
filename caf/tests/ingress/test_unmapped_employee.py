"""Nobody may silently receive no attendance — MG's three remedies, 2026-09-01.

    bench --site <site> execute caf.tests.ingress.test_unmapped_employee.run

MG, after the manifest work: *"the real issue here is every emp must have
erp.attendance_device_id (except the director)."*

🔴 FIRST, THE MECHANISM — because it runs the OPPOSITE WAY to the obvious guess
------------------------------------------------------------------------------
The importer walks **Ingress rows**, not employees:

    emp = by_device.get(row["ftag_id"])
    if not emp:
        batch.counts.skipped_no_employee += 1
        continue                            # ← no manifest row is written

So `skipped_no_employee` counts **Ingress accounts with no ERPNext employee** —
measured 2026-09-01: 220 of them, 1,528 punchless rows, ex-staff whose Ingress
accounts were never suspended. That number says nothing about CAF's own people.

An ERPNext employee with a blank `attendance_device_id` produces **no count at
all**. They are simply absent from `active_by_device()`, so no Ingress row ever
matches them, and there is nothing to report. **That silence is the danger**
(FBR41), and it is what these three remedies close:

    1. a caution on the Employee form when the field is blank
    2. `caf_no_clocking`, so a deliberate exception is a decision and not a blank
    3. a note on every import batch naming anyone who will receive nothing

Read-only except for one throwaway employee, removed in `finally`.
"""

import frappe

RESULTS = []
PROBE = "ZZ Test Unmapped Employee"


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:28s} {'PASS' if ok else 'FAIL'}  {detail}")


def run():
    frappe.set_user("Administrator")
    from caf.caf.ingress import sync
    from caf.scripts import readiness_audit as ra

    made = None
    try:
        # ── UM1 — today's data is clean, and the exception is NAMED ────────
        blank = frappe.get_all(
            "Employee", filters={"status": "Active",
                                 "attendance_device_id": ("in", ["", None])},
            fields=["name", "employee_name", "caf_no_clocking"])
        unflagged = [e for e in blank if not e.caf_no_clocking]
        check("UM1-EXCEPTION-IS-NAMED", blank and not unflagged,
              f"{len(blank)} active employee(s) have no device id and every one is "
              f"flagged 'Does Not Clock In' "
              f"({', '.join(e.employee_name for e in blank)}). A blank field is "
              f"correct for somebody who never clocks and a typo otherwise — the "
              f"flag is the only thing that tells them apart")

        # ── UM2 — the clean case is STATED, not left as silence ────────────
        gaps = sync.unmapped_employees()
        check("UM2-CLEAN-CASE-REPORTED", gaps == [],
              f"`unmapped_employees()` returns {gaps} — the flagged director is "
              f"excluded, so a genuine exception does not train HR to ignore the "
              f"message. The batch still records that the check RAN, because "
              f"silence is indistinguishable from a check that never happened")

        # ── UM3 — 🔴 a new unmapped employee is caught ─────────────────────
        made = frappe.new_doc("Employee")
        made.first_name = PROBE
        made.employee_name = PROBE
        made.status = "Active"
        made.date_of_joining = "2026-01-01"
        made.date_of_birth = "1990-01-01"
        made.gender = frappe.db.get_value("Gender", {}, "name") or "Male"
        made.company = frappe.db.get_value("Company", {}, "name")
        made.reports_to = "HR-EMP-00003"
        made.flags.ignore_permissions = True
        made.insert(ignore_permissions=True)

        gaps_now = sync.unmapped_employees()
        check("UM3-NEW-GAP-IS-CAUGHT", any(g.name == made.name for g in gaps_now),
              f"an employee created with no device id appears immediately in the "
              f"import-batch note ({len(gaps_now)} name(s)). Without this they "
              f"would receive no Finger Log and no Attendance for as long as "
              f"nobody noticed — and there is no row anywhere to notice")

        # ── UM4 — the readiness audit agrees with the importer ─────────────
        row = next((r for r in ra.audit()["rows"]
                    if "NO attendance" in r["check"]), None)
        check("UM4-AUDIT-AGREES", row and row["count"] == len(gaps_now)
              and row["severity"] == "BLOCK",
              f"the readiness audit reports the same {row['count'] if row else '?'} "
              f"as BLOCK. Two places ask this question — the audit and every "
              f"import — and they must not be able to disagree")

        # ── UM5 — the flag silences it, and only the flag ──────────────────
        frappe.db.set_value("Employee", made.name, "caf_no_clocking", 1)
        after = sync.unmapped_employees()
        check("UM5-FLAG-SILENCES", not any(g.name == made.name for g in after),
              f"ticking 'Does Not Clock In' removes them ({len(after)} left). This "
              f"is the whole design: the list is normally EMPTY, so its contents "
              f"always mean something")

        # ── UM6 — the form caution fires, and does NOT block the save ──────
        frappe.db.set_value("Employee", made.name, "caf_no_clocking", 0)
        doc = frappe.get_doc("Employee", made.name)
        doc.flags.ignore_permissions = True
        frappe.clear_messages()
        doc.save(ignore_permissions=True)          # must NOT throw
        msgs = " ".join(frappe.utils.strip_html(str(m))
                        for m in (frappe.get_message_log() or []))
        check("UM6-WARNS-BUT-SAVES",
              "Attendance Device ID" in msgs or "no attendance" in msgs.lower(),
              f"saving warns rather than refusing — HR creates an employee BEFORE "
              f"the person is enrolled on the machine, so a throw would make the "
              f"normal order of work impossible. Message seen: "
              f"{msgs[:110] or '🔴 none'}")

    finally:
        frappe.set_user("Administrator")
        if made is not None and made.name and frappe.db.exists("Employee", made.name):
            frappe.delete_doc("Employee", made.name, force=True,
                              ignore_permissions=True)
        frappe.db.commit()

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    return not failed
