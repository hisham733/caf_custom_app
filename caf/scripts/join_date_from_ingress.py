"""Correct the nine join dates ERPNext and Ingress disagreed about.

    bench --site <site> execute caf.scripts.join_date_from_ingress.run
    bench --site <site> execute caf.scripts.join_date_from_ingress.run --kwargs "{'apply':1}"
    bench --site <site> execute caf.scripts.join_date_from_ingress.verify

MG's rulings, 2026-09-01, after HR corrected the Ingress side. 79 of 88 mapped
active employees already agree and none is blank, so this touches nine people.

🔴 `IssueDate` IS NOT RELIABLY THE JOIN DATE — measured, and it changed the answer
--------------------------------------------------------------------------------
The first pass compared ERPNext against Ingress `user.IssueDate` and treated a
difference as "ERPNext is stale". Reading the machine's OWN first record of each
person shows that is wrong for some of them:

    ftag  employee            ERP join    IssueDate   1st RAW TAP   1st att day
    1083  Nur Syamimi         2025-03-17  2025-08-01  2025-03-17    2025-08-01
    1115  Nur Aida Basirah    2025-08-04  2025-12-01  2025-08-04    2025-12-01
    1029  Md Uzzal Hossan     2024-01-01  2025-12-01  2023-09-02    2025-12-01

For all three, **`IssueDate` equals the first `attendance` day, not the first
tap** — i.e. it records when Ingress started MATERIALISING that person's days
(FBR49), which can be years after they joined. `auditdata`'s earliest `checktime`
is the honest witness: it is the first time the person physically touched the
machine, and it cannot be back-filled by a report run.

So the rule used here is: **`auditdata` first tap adjudicates; `IssueDate` only
corroborates.** Where they agree, either is fine. Where they differ, the tap wins.

⚠️ The machine can only speak about the period it has data for. `810` Md Sultan
joined in 2018 and the machine's earliest tap for him is 2022-04-13 — the device
was replaced. There, ERPNext is the only witness and MG ruled accordingly.
"""

import frappe
from frappe.utils import getdate

TRAIL = "Join date corrected by caf.scripts.join_date_from_ingress"

# MG's rulings, one row per person, with the evidence that supports each.
# `want` is stated explicitly rather than computed: these are DECISIONS, and a
# script that re-derives them could quietly decide differently next run.
RULINGS = [
    # ── copy from Ingress: a one-day batch slip on three men hired together ──
    ("HR-EMP-00118", "1013", "Md Iliach", "2023-02-09",
     "MG: copy from Ingress. ERP 2023-02-08, Ingress 2023-02-09 — a one-day slip "
     "across a batch of three hired the same day. The machine cannot adjudicate "
     "(first tap 2025-10-10, long after), so MG's ruling stands on HR's record"),
    ("HR-EMP-00119", "1014", "Mizanur Rahman", "2023-02-09",
     "MG: copy from Ingress. Same batch as 1013"),
    ("HR-EMP-00120", "1015", "Nayan Miah", "2023-02-09",
     "MG: copy from Ingress. Same batch as 1013"),

    # ── keep ERPNext: the machine predates nothing useful ────────────────────
    ("HR-EMP-00035", "810", "Md Sultan Hosen Rubel", "2018-08-04",
     "MG: 2018-08-04 — i.e. ERPNext's value is KEPT and Ingress's 2018-09-04 is "
     "the typo. Corroborated by the machine being unable to speak: its earliest "
     "tap for him is 2022-04-13, four years after either date, because the device "
     "was replaced. No change is written for this row"),

    # ── copy from Ingress: ERP holds the 2024-01-01 placeholder ──────────────
    ("HR-EMP-00065", "1031", "Muhammad Aliff Bin Mohd Azhar", "2023-09-18",
     "MG: copy from Ingress. ✅ CONFIRMED by the machine — IssueDate 2023-09-18 "
     "equals the FIRST RAW TAP exactly, and the account was created 2023-09-20. "
     "ERP's 2024-01-01 is one of exactly three placeholder values on this site"),
    ("HR-EMP-00075", "965", "Seriramulu A/L Apanah", "2022-08-01",
     "MG: copy from Ingress. ERP's 2024-01-01 is a placeholder. ⚠️ Note for HR: "
     "the machine's first RAW TAP is 2022-08-25 and the account was created the "
     "same day, so 2022-08-25 is the better-evidenced date; 2022-08-01 is the "
     "first materialised attendance day. 24 days apart — MG's ruling is applied, "
     "and the discrepancy recorded rather than silently resolved"),

    # ── reported back to MG: the machine says ERPNext was already right ───────
    ("HR-EMP-00127x", "1083", "Nur Syamimi Binti Sadli", None,
     "REPORT ONLY — no change. ERP 2025-03-17 equals the FIRST RAW TAP exactly. "
     "Ingress's 2025-08-01 is the first materialised attendance day, not a join "
     "date. ERPNext is right and Ingress is the stale one"),
    ("HR-EMP-00141x", "1115", "Nur Aida Basirah", None,
     "REPORT ONLY — no change. ERP 2025-08-04 equals BOTH the first raw tap and "
     "the account creation date. Ingress's 2025-12-01 is again the first "
     "materialised attendance day. ERPNext is right"),
    ("HR-EMP-00xxx", "1029", "Md Uzzal Hossan", None,
     "🔴 REPORT ONLY — needs HR. NEITHER side is credible: ERP holds the "
     "2024-01-01 placeholder, Ingress says 2025-12-01 (the first materialised "
     "day). The machine says he was created 2023-08-29 and FIRST TAPPED "
     "2023-09-02, with 1,541 taps since — so he has worked here since Sept 2023 "
     "and both stored dates are wrong"),
]

# Resolved by DEVICE ID rather than trusting the employee ids typed above —
# FBR51's lesson in a different key: a plausible-looking identifier is not a
# verified one.
def _by_ftag(ftag):
    return frappe.db.get_value("Employee", {"attendance_device_id": ftag,
                                            "status": "Active"},
                               ["name", "employee_name", "date_of_joining"],
                               as_dict=True)


def run(apply=0):
    apply = int(apply)
    frappe.set_user("Administrator")
    changed, reported, problems = [], [], []

    print(f"{'ftag':>5s} {'employee':30s} {'now':11s} {'want':11s} action")
    for _guess, ftag, who, want, why in RULINGS:
        emp = _by_ftag(ftag)
        if not emp:
            problems.append(f"ftag {ftag} ({who}) matches no active employee")
            print(f"{ftag:>5s} {who[:30]:30s} 🔴 NOT FOUND")
            continue

        now = str(emp.date_of_joining)
        if want is None:
            action = "report only — no change"
            reported.append((ftag, emp, why))
        elif now == want:
            action = "already correct"
        else:
            action = f"{'WRITE' if apply else 'would write'} {want}"
            if apply:
                frappe.db.set_value("Employee", emp.name, "date_of_joining", want)
                # db.set_value writes no Version (OD-26), so the comment IS the
                # trail — and a join date decides service duration, which decides
                # somebody's leave entitlement.
                frappe.get_doc("Employee", emp.name).add_comment("Comment", (
                    f"{TRAIL}: <b>{now}</b> ➜ <b>{want}</b>.<br>{why}"))
            changed.append((ftag, emp, now, want))

        print(f"{ftag:>5s} {emp.employee_name[:30]:30s} {now:11s} "
              f"{str(want or '—'):11s} {action}")
        print(f"      {why}")

    print(f"\n  {len(changed)} to change · {len(reported)} reported only · "
          f"{len(problems)} problem(s)")
    for p in problems:
        print(f"    🔴 {p}")

    if not apply:
        print("\n(report only — pass apply=1 to write the join dates)")
        return {"would_change": len(changed), "reported": len(reported),
                "problems": problems}

    frappe.db.commit()
    print(f"\nDONE — {len(changed)} join date(s) corrected, each with a Comment "
          f"naming the old value and the reason.")
    return {"changed": [c[0] for c in changed], "problems": problems}


def verify():
    """Every ruling that names a target date is now that date."""
    frappe.set_user("Administrator")
    bad = []
    for _g, ftag, who, want, _why in RULINGS:
        emp = _by_ftag(ftag)
        if not emp:
            bad.append(f"ftag {ftag} ({who}) not found")
            continue
        if want and str(emp.date_of_joining) != want:
            bad.append(f"{who}: {emp.date_of_joining} != {want}")
        mark = "n/a  " if not want else ("ok  " if str(emp.date_of_joining) == want
                                         else "🔴 ")
        print(f"  {mark} {ftag:>5s} {emp.employee_name[:30]:30s} "
              f"{emp.date_of_joining}")
    print("\n" + ("🔴 " + "; ".join(bad) if bad else
                  "✅ every ruled join date is in place; three remain reported to "
                  "MG rather than changed"))
    return {"problems": bad}
