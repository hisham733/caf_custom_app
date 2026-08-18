"""TEST SERVER ONLY — narrow HR Manager to the four people MG named.

    bench --site development.localhost execute caf.scripts.test_server_hr_roles.run

MG, 2026-08-18: *"only Chen Xio, afiza, the 2 director get HR manager role, pls
change to this for testing purposes on this test server."*

⚠️ **Never run this against production.** It also sets a shared, known password so
MG can log in as each person for manual testing — which is exactly what must not
exist on a real system. Production role correction is GO_LIVE_TODO T-10, and is a
different, considered exercise.

⚠️ This deliberately UNDOES part of commit 0417b73, which imported production's
role assignments so permission tests would be realistic. After this the test server
no longer mirrors production's HR Manager population. That is MG's call and the
right trade for hands-on testing, but it means "12 people hold HR Manager" remains
true of PRODUCTION and is not observable here any more.
"""

import frappe

ROLE = "HR Manager"
TEST_PASSWORD = "abc@123"

# The manual-testing cast (MG, 2026-08-18). These need a known password too, or
# the walk cannot be done as anybody except an HR Manager — and the workflows worth
# testing are precisely the ones that cross roles.
#
# Chosen because each has a device id, a supervisor, a leave approver and at least
# two submitted Leave Allocations, so the leave path does not fail for a data
# reason. They form one working chain: three employees → Too Poh Chin (their
# supervisor) → Chen / Afiza (HR Manager).
# ⚠️ Every address here was READ from `Employee.user_id`, not inferred from the
# person's name — FBR51. Guessing produced two wrong out of three on this very
# list: Nur Najwa Farhana is `wawa@`, not `najwa@`; Nurfarahayu is `farah@`, not
# `farahayu@`.
TEST_CAST = {
    "too@caffood.com": "Too Poh Chin (HR-EMP-00003) — SUPERVISOR of the three below",
    "wawa@caffood.com": "Nur Najwa Farhana (HR-EMP-00005) — alt-Sat 1st-3rd",
    "farah@caffood.com": "Nurfarahayu (HR-EMP-00007) — alt-Sat 2nd-4th, the OPPOSITE group",
    "seow@caffood.com": "Seow Zi Ying (HR-EMP-00009) — 3 allocations",
}

# The four MG named, resolved through Employee.user_id rather than by guessing
# from the email — see the traps below.
KEEP_NAMED = {
    "natalie@caffood.com": "Chen Xiao Natalie (HR-EMP-00006)",
    "fiza@caffood.com": "Afiza binti Mustafa (HR-EMP-00004)",
    "ow.yong@caffood.com": "Ow Yong Mian Fatt — ROOT 1 (HR-EMP-00001)",
}

# 🔴 DELIBERATELY NOT GRANTED — Yow Kwee Chin, ROOT 2 (HR-EMP-00002),
# `yow.kwee@caffood.com`. MG, 2026-08-18. Two reasons, and the second is the
# better one:
#
#  1. TECHNICAL — that account is the `STRANGER` fixture in
#     run_leave_workflow.ps1, which asserts a director who is NOT this employee's
#     approver is REFUSED (W4 read, W5 workflow transition). HR Manager can read
#     every Leave Application and drive the workflow, so granting it would turn
#     both assertions green for the wrong reason — the worst kind of passing test.
#
#  2. SUBSTANTIVE — *"this dir never uses ERPNext anyway"* (MG). Granting HR
#     Manager to a dormant account hands real power to a login nobody watches, and
#     buys nothing. In practice the HR Manager approves leave on both roots'
#     behalf, so the role is not needed for the business flow either.
#
# Neither reason is about difficulty. If she ever starts using ERPNext, grant it
# and re-point STRANGER to `quality@caffood.com` (Nurulfarehah, HR-EMP-00036 —
# Leave Approver, no HR Manager, no System Manager), which is already prepared.

# ⚠️ TWO NAME TRAPS, both corrected the hard way. Left here because the next
# person will hit them:
#
#   "Afiza"  -> `fiza@caffood.com` is Afiza binti Mustafa (HR-EMP-00004).
#              `afiza@caffood.com` is AFRIZA MAULANA, a DIFFERENT PERSON.
#
#   "the 2 directors" -> the two org roots (`reports_to IS NULL`) are
#              HR-EMP-00001 Ow Yong Mian Fatt and HR-EMP-00002 Yow Kwee Chin.
#              `production1@caffood.com` / HR-EMP-00008 Ow Yong Nin Geet is the
#              PRODUCTION MANAGER and reports to HR-EMP-00001 — he was granted the
#              role in error on 2026-08-18 and it is removed here. Corrected by MG.
#
# Resolve people through `Employee.user_id`, never by reading the email address.

# Kept for reasons that are NOT about who should hold the role in the business.
KEEP_TECHNICAL = {
    "Administrator": "the system account; bypasses every permission check anyway, "
                     "and removing it would only make recovery harder",
    "hr.manager.test@caffood.com": "🔴 the automated suites' HR Manager fixture — "
                                   "S11 and run_leave_workflow assert AS this user. "
                                   "Strip it and the gate breaks, not the product",
    "mg@caffood.com": "MG's own account. Removing a user's own access to their own "
                      "test server is not something to do on inference — say the "
                      "word and it goes",
}


def run(apply=0):
    """apply=0 reports what would change; apply=1 does it."""
    apply = int(apply)
    frappe.set_user("Administrator")

    holders = {r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "User"},
        fields=["parent"])}

    keep = set(KEEP_NAMED) | set(KEEP_TECHNICAL)
    revoke = sorted(holders - keep)
    grant = sorted(k for k in KEEP_NAMED if k not in holders)

    print(f"\n{ROLE} holders now: {len(holders)}")
    print(f"\nGRANT to ({len(grant)}):")
    for u in grant:
        print(f"  + {u:32s} {KEEP_NAMED[u]}")
    print(f"\nALREADY HELD, keeping ({len(set(KEEP_NAMED) & holders)}):")
    for u in sorted(set(KEEP_NAMED) & holders):
        print(f"  = {u:32s} {KEEP_NAMED[u]}")
    print(f"\nKEEPING for technical reasons ({len(KEEP_TECHNICAL & holders if isinstance(KEEP_TECHNICAL, set) else set(KEEP_TECHNICAL) & holders)}):")
    for u in sorted(set(KEEP_TECHNICAL) & holders):
        print(f"  = {u:32s} {KEEP_TECHNICAL[u]}")
    print(f"\nREVOKE from ({len(revoke)}):")
    for u in revoke:
        print(f"  - {u}")

    if not apply:
        print("\n(dry run — pass apply=1 to make the change)")
        return

    for u in grant:
        frappe.get_doc("User", u).add_roles(ROLE)
    for u in revoke:
        frappe.get_doc("User", u).remove_roles(ROLE)

    # Known password, test server only, so MG can sign in as each person.
    from frappe.utils.password import update_password
    for u in list(KEEP_NAMED) + list(TEST_CAST):
        if frappe.db.exists("User", u):
            update_password(u, TEST_PASSWORD)
            frappe.db.set_value("User", u, "enabled", 1, update_modified=False)

    frappe.db.commit()

    after = {r.parent for r in frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "User"},
        fields=["parent"])}
    print(f"\nDONE. {ROLE} now held by {len(after)}:")
    for u in sorted(after):
        print(f"  {u}")
    print(f"\npassword {TEST_PASSWORD!r} set for the HR Managers:")
    for u in sorted(KEEP_NAMED):
        print(f"  {u:26s} {KEEP_NAMED[u]}")
    print(f"\n…and the manual-testing cast:")
    for u in sorted(TEST_CAST):
        print(f"  {u:26s} {TEST_CAST[u]}")
