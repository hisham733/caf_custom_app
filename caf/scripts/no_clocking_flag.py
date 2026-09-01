"""Mark the employees who are NOT expected to clock, so a blank device id is loud.

    bench --site <site> execute caf.scripts.no_clocking_flag.run
    bench --site <site> execute caf.scripts.no_clocking_flag.run --kwargs "{'apply':1}"

MG, 2026-09-01: *"every emp must have erp.attendance_device_id (except the
director)… note the second director she never uses finger log, so this is a
special case where the field can be empty."*

WHY A FLAG AND NOT A HARDCODED NAME
-----------------------------------
**FBR41** already establishes that an active employee with no
`attendance_device_id` receives no attendance ever, and that this is CORRECT for
somebody who does not clock. The danger it also names is that the correct case and
a mapping MISTAKE look identical — both are simply a blank field.

A flag separates them. `caf_no_clocking = 1` means *somebody decided this*;
blank-and-unflagged means *nobody has looked*. That is the same discipline as
`caf_reports_to_nobody` for the org roots (D53) and `EXEMPT` in the readiness
audit (OD-24): **named, never tolerated by count.**

Hardcoding "HR-EMP-00002" would work today and rot the moment she retires or a
second non-clocking role appears — and the failure would be silent in the
direction that matters, because a new unmapped employee would be absorbed into an
exemption nobody re-examined.

MEASURED 2026-09-01: exactly **1** of 89 active employees has a blank device id —
`HR-EMP-00002` Yow Kwee Chin — which is the one MG named. So this script confirms
today's state rather than changing it.
"""

import frappe

FIELD = {
    "dt": "Employee",
    "fieldname": "caf_no_clocking",
    "label": "Does Not Clock In",
    "fieldtype": "Check",
    "default": "0",
    "insert_after": "attendance_device_id",
    "description": (
        "Tick ONLY for someone who genuinely never uses the fingerprint machine. "
        "They will receive no Finger Log and no Attendance, ever (FBR41). "
        "<b>Leave it unticked and the blank Attendance Device ID is reported as a "
        "mistake</b> — which is the point: a deliberate exception and a mapping "
        "error otherwise look identical."),
}

# The one person MG has confirmed. Applied only if they still have no device id —
# never used to CLEAR a device id somebody has since been given.
CONFIRMED = {
    "HR-EMP-00002": "Yow Kwee Chin — director, second org root (FBR50). "
                    "MG confirmed 2026-08-17: 'yes this director never log', and "
                    "again 2026-09-01. She does not use ERPNext either.",
}


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")
    acted = []

    exists = frappe.db.exists("Custom Field",
                              {"dt": "Employee", "fieldname": FIELD["fieldname"]})
    print(f"  {FIELD['fieldname']:20s} {'exists' if exists else '🔴 MISSING'}")
    if apply and not exists:
        from frappe.custom.doctype.custom_field.custom_field import create_custom_field
        create_custom_field(FIELD["dt"], FIELD, ignore_validate=True)
        acted.append(FIELD["fieldname"])
        exists = True

    if not exists:
        print("\n(report only — pass apply=1 to add the field)")
        return {"missing_field": FIELD["fieldname"]}

    blank = frappe.get_all(
        "Employee",
        filters={"status": "Active", "attendance_device_id": ("in", ["", None])},
        fields=["name", "employee_name", "department", "caf_no_clocking"])

    print(f"\n  Active employees with NO Attendance Device ID: {len(blank)}")
    for e in blank:
        why = CONFIRMED.get(e.name)
        if e.caf_no_clocking:
            state = "already flagged"
        elif why:
            state = "+ FLAG (MG confirmed)" if apply else "would flag (MG confirmed)"
        else:
            state = "🔴 NOT CONFIRMED — ask HR before flagging"
        print(f"    {e.name} {e.employee_name[:28]:28s} "
              f"{(e.department or '').replace(' - CAF',''):18s} {state}")
        if why:
            print(f"        {why}")
        if apply and why and not e.caf_no_clocking:
            frappe.db.set_value("Employee", e.name, "caf_no_clocking", 1)
            frappe.get_doc("Employee", e.name).add_comment("Comment", (
                f"Flagged <b>Does Not Clock In</b> by "
                f"caf.scripts.no_clocking_flag.<br>{why}"))
            acted.append(e.name)

    # The other direction: somebody flagged who DOES have a device id. That is a
    # contradiction — they are enrolled on the machine and marked as not clocking.
    contradictory = frappe.get_all(
        "Employee", filters={"status": "Active", "caf_no_clocking": 1,
                             "attendance_device_id": ("not in", ["", None])},
        fields=["name", "employee_name", "attendance_device_id"])
    if contradictory:
        print(f"\n  🔴 {len(contradictory)} flagged as non-clocking but HOLD a "
              f"device id — they will receive attendance despite the flag:")
        for e in contradictory:
            print(f"    {e.name} {e.employee_name} (device {e.attendance_device_id})")

    if not apply:
        print("\n(report only — pass apply=1 to add the field and flag the confirmed)")
        return {"blank": len(blank), "contradictory": len(contradictory)}

    frappe.db.commit()
    frappe.clear_cache()
    print(f"\nDONE — {acted or 'nothing (already correct)'}")
    return {"acted": acted, "contradictory": [e.name for e in contradictory]}


def verify():
    frappe.set_user("Administrator")
    bad = []
    blank = frappe.get_all(
        "Employee",
        filters={"status": "Active", "attendance_device_id": ("in", ["", None])},
        fields=["name", "employee_name", "caf_no_clocking"])
    for e in blank:
        mark = "ok  " if e.caf_no_clocking else "🔴 "
        if not e.caf_no_clocking:
            bad.append(f"{e.name} {e.employee_name} has no device id and no flag")
        print(f"  {mark} {e.name} {e.employee_name}")
    print("\n" + ("🔴 " + "; ".join(bad) if bad else
                  f"✅ all {len(blank)} employee(s) without a device id are "
                  f"deliberately flagged; nobody is silently unmapped"))
    return {"problems": bad}
