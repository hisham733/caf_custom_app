"""One-time joining-date migration from Ingress into ERPNext. MG, 2026-08-13.

Purpose : apply the two rules HR could decide without case-by-case review, and
          leave the rest listed for them.
Run     : bench --site <site> execute caf.scripts.join_date_reconcile.plan
          bench --site <site> execute caf.scripts.join_date_reconcile.apply
Needs   : /tmp/ingress_join.csv  (userid,name,issuedate,createdate,suspended)
Refs    : FBR29 · P-6 · LEAVE_FORMULA_for_HR_verification.html

🔴 ONE TIME, NOT A SYNC. MG: *"kinda migrating data from ingress to erpnext — in
the new structure emp.join_date is purely managed by ERP."* After this runs,
Ingress has no further say and this script should not be run again. It is
deliberately not hooked to anything.

THE RULES, AND WHAT EACH ONE REACHES
------------------------------------
  gap of exactly 1 day        -> take Ingress.   9 employees.
                                 Almost certainly a timezone or off-by-one in
                                 the original import, not a disagreement about
                                 the facts.

  ERP date is 2022-03-01      -> take Ingress.   ZERO employees. ⚠️
                                 MG's second rule matches nothing, and it is
                                 worth saying why: **2022-03-01 is on the
                                 INGRESS side, not the ERP side** — it is the
                                 day Ingress was installed, written onto all 18
                                 people already employed. For those 18 Ingress
                                 cannot tell us anything, and the ERPNext date
                                 is all there is.

  everything else             -> LEFT ALONE, listed for HR. 9 employees, gaps
                                 from 105 days to 37 years.

⚠️ Changing a joining date changes what the pro-rating formula gives, so
`plan()` prints the leave consequence beside each change before anything is
written.

Changelog
---------
1.0  2026-08-13  Initial — one-time migration
"""

import csv
import os

import frappe
from frappe.utils import getdate

from caf.scripts.leave_formula import entitlement

INGRESS_CSV = "/tmp/ingress_join.csv"
INSTALL_DATE = "2022-03-01"
CYCLE = 2026
AUTO_GAP_DAYS = 1


def _ingress():
    if not os.path.exists(INGRESS_CSV):
        frappe.throw(f"{INGRESS_CSV} not found — extract it from "
                     f"ingress_snapshot/user.csv.gz first")
    with open(INGRESS_CSV, newline="", encoding="utf-8", errors="replace") as fh:
        return {r["userid"].strip(): r for r in csv.DictReader(fh) if r.get("userid")}


def classify():
    ing = _ingress()
    auto, manual, install, agree, nolink = [], [], [], [], []

    for e in frappe.get_all("Employee", filters={"status": "Active"},
                            fields=["name", "employee_name", "date_of_joining",
                                    "attendance_device_id"],
                            order_by="employee_name"):
        i = ing.get((e.attendance_device_id or "").strip()) if e.attendance_device_id else None
        issue = (i or {}).get("issuedate") or ""
        if not issue or not e.date_of_joining:
            nolink.append(e)
            continue
        if issue == INSTALL_DATE:
            install.append(e)
            continue
        gap = (getdate(issue) - getdate(e.date_of_joining)).days
        if gap == 0:
            agree.append(e)
            continue

        before = entitlement(e.date_of_joining, CYCLE)
        after = entitlement(issue, CYCLE)
        row = {"employee": e.name, "name": e.employee_name,
               "erp": str(e.date_of_joining), "ingress": issue, "gap": gap,
               "al": (before["al"], after["al"]), "mc": (before["mc"], after["mc"])}
        (auto if abs(gap) <= AUTO_GAP_DAYS else manual).append(row)

    return {"auto": auto, "manual": manual, "install": install,
            "agree": agree, "nolink": nolink}


def plan():
    c = classify()
    print(f"AUTOMATIC — gap of {AUTO_GAP_DAYS} day or less, take Ingress "
          f"({len(c['auto'])})")
    for r in c["auto"]:
        moved = "" if r["al"][0] == r["al"][1] and r["mc"][0] == r["mc"][1] \
            else f"   ⚠️ AL {r['al'][0]}➜{r['al'][1]}  MC {r['mc'][0]}➜{r['mc'][1]}"
        print(f"   {r['name'][:34]:34s} {r['erp']} ➜ {r['ingress']} "
              f"({r['gap']:+d}d){moved}")

    print(f"\nHR MUST DECIDE — gap too large to assume ({len(c['manual'])})")
    for r in sorted(c["manual"], key=lambda x: -abs(x["gap"])):
        moved = "" if r["al"][0] == r["al"][1] and r["mc"][0] == r["mc"][1] \
            else f"   AL {r['al'][0]}➜{r['al'][1]}  MC {r['mc'][0]}➜{r['mc'][1]}"
        print(f"   {r['name'][:34]:34s} {r['erp']} vs {r['ingress']} "
              f"({r['gap']:+d}d){moved}")

    print(f"\nINGRESS CANNOT HELP — it shows {INSTALL_DATE}, the install date "
          f"({len(c['install'])})")
    print(f"ALREADY AGREE ({len(c['agree'])}) · NO INGRESS RECORD ({len(c['nolink'])})")
    print(f"\nNothing has been written. Run `.apply` to make the "
          f"{len(c['auto'])} automatic changes.")
    return c


def apply():
    """Write only the automatic ones. HR's cases are never touched here."""
    c = classify()
    done = []
    for r in c["auto"]:
        frappe.db.set_value("Employee", r["employee"], "date_of_joining",
                            getdate(r["ingress"]))
        # OD-26's habit: a db_set leaves no Version, so say what happened and why.
        frappe.get_doc("Employee", r["employee"]).add_comment(
            "Comment",
            f"Joining date corrected {r['erp']} ➜ {r['ingress']} from the Ingress "
            f"record ({r['gap']:+d} day). One-time migration, 2026-08-13 — "
            f"ERPNext owns this field from now on.")
        done.append(r["name"])
    frappe.db.commit()
    print(f"updated {len(done)}: {', '.join(done)}")
    print(f"⚠️ {len(c['manual'])} still need HR, one by one.")
    return {"updated": done, "pending": len(c["manual"])}
