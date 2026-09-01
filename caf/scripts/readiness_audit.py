"""Pre-go-live readiness — the latent blockers that only surface at first use.

Purpose : find the things that corrupt nothing and break everything the first
          time somebody uses a feature. Go-live is when a lot of features get
          used for the first time, all at once.
Run     : bench --site <site> execute caf.scripts.readiness_audit.audit
Refs    : OD-75 (naming counters) · OD-76 (report_to vs leave approver) ·
          OD-71b (next year's holidays) · OD-24 · FDR6 · framework §6

🔴 WHY THIS EXISTS
------------------
2026-08-13, building the Leave Policy seed: `HR-LAL-2026-` read 1 while 55 rows
existed. Nothing was corrupted. Nothing was wrong on any screen. **Nobody could
have been granted leave**, and the only way to discover it was to try.

A full sweep then found **nine** broken naming counters — including `HR-EMP-` at
7 against 214 employees — plus 22 employees reporting to a manager with no
login, and two employees with annual leave but no medical entitlement at all.
**None of those show up anywhere until the moment they block somebody.**

So: one command that tries the questions in advance. It writes nothing.

⚠️ Each check names what BREAKS, not what is unusual. A readiness list that
reports oddities trains people to skip it — the same failure the alternate-
Saturday detector was designed around (§6.14, `C75-QUIET`).

Changelog
---------
1.0  2026-08-13  Initial — after OD-75 and OD-76
"""

import frappe
from frappe.utils import getdate, nowdate

from caf.scripts.naming_series_audit import _gaps


# OD-24 — a director who never punches, deliberately outside the import filter.
# Exempted BY NAME, so a second empty row is still a block rather than being
# absorbed into an expected count.
EXEMPT = {"HR-EMP-00002"}


def _row(sev, what, count, detail):
    return {"severity": sev, "check": what, "count": count, "detail": detail}


def check_naming():
    gaps = _gaps()
    return _row("BLOCK" if gaps else "ok", "naming counters behind", len(gaps),
                ", ".join(f"{g[1]} ({g[2]}<{g[3]})" for g in gaps[:5])
                or "every counter is at or above the rows in use")


def check_default_shift():
    rows = frappe.get_all("Employee", filters={
        "status": "Active", "default_shift": ("in", ["", None])},
        fields=["name", "employee_name"])
    # OD-24: HR-EMP-00002 is deliberately empty — a director who never punches
    # and is excluded from the import filter. Named, not silently tolerated.
    unexpected = [r for r in rows if r.name not in EXEMPT]
    return _row("BLOCK" if unexpected else "ok",
                "active employees with no default shift", len(unexpected),
                ", ".join(f"{r.employee_name}" for r in unexpected[:5])
                or f"only the {len(rows)} expected (OD-24)")


def check_holiday_list():
    rows = frappe.get_all("Employee", filters={
        "status": "Active", "holiday_list": ("in", ["", None])},
        fields=["name", "employee_name"])
    # Same OD-24 exemption as the shift check, and for the same person: a
    # director who never punches, excluded from the import filter. Exempting him
    # by NAME rather than by count, so a second empty row is still a block.
    unexpected = [r for r in rows if r.name not in EXEMPT]
    return _row("BLOCK" if unexpected else "ok",
                "active employees with no holiday list", len(unexpected),
                ", ".join(r.employee_name for r in unexpected[:5])
                or f"FDR6's copy-down has reached everybody except the "
                   f"{len(rows)} exempt (OD-24)")


def check_shift_lists():
    rows = frappe.get_all("Shift Type", filters={
        "holiday_list": ("in", ["", None])}, fields=["name"])
    return _row("BLOCK" if rows else "ok", "shift types with no holiday list",
                len(rows), ", ".join(r.name for r in rows[:5]) or "all shifts carry one")


def check_alt_pairs():
    """A mirror that points one way is a half-configured pair, and it fails in
    the direction nobody tests (§6.9, I9)."""
    bad = []
    for s in frappe.get_all("Shift Type", filters={"caf_alt_sat": 1},
                            fields=["name", "caf_sat_mirror",
                                    "caf_sat_anchor", "caf_sat_anchor_date"]):
        if not s.caf_sat_mirror or not s.caf_sat_anchor or not s.caf_sat_anchor_date:
            bad.append(f"{s.name} incomplete")
        elif frappe.db.get_value("Shift Type", s.caf_sat_mirror,
                                 "caf_sat_mirror") != s.name:
            bad.append(f"{s.name} mirror is one-way")
    return _row("BLOCK" if bad else "ok", "alternate-Saturday pairs broken",
                len(bad), ", ".join(bad[:4]) or "every pair is complete and mutual")


def check_manager_logins():
    """OD-76. An appraisal is opened by the manager an employee reports to. A
    manager with no user account cannot open anything."""
    bad = []
    for m in frappe.db.sql("""
        SELECT e.reports_to, mgr.employee_name, COUNT(*) AS n
          FROM `tabEmployee` e
          LEFT JOIN `tabEmployee` mgr ON mgr.name = e.reports_to
         WHERE e.status = 'Active' AND IFNULL(e.reports_to,'') <> ''
           AND IFNULL(mgr.user_id,'') = ''
      GROUP BY e.reports_to, mgr.employee_name""", as_dict=True):
        bad.append(f"{m.employee_name or m.reports_to} ({m.n} reports)")
    total = sum(int(x.split("(")[1].split(" ")[0]) for x in bad) if bad else 0
    return _row("BLOCK" if bad else "ok",
                "employees whose manager has no login", total,
                ", ".join(bad[:4]) or "every manager can log in")


def check_leave_period():
    year = getdate(nowdate()).year
    missing = [y for y in (year, year + 1)
               if not frappe.db.exists("Leave Period", {"from_date": f"{y}-01-01"})]
    return _row("BLOCK" if missing else "ok", "leave periods missing",
                len(missing), ", ".join(str(y) for y in missing)
                or f"{year} and {year + 1} both exist")


def check_next_year_holidays():
    """OD-71b. The alternate-Saturday walk REFUSES a year whose public-holiday
    list does not exist, and Ingress holds nothing for 2027 — HR enters it from
    the gazette."""
    year = getdate(nowdate()).year + 1
    name = f"CAF Public Holidays {year}"
    exists = frappe.db.exists("Holiday List", name)
    n = frappe.db.count("Holiday", {"parent": name}) if exists else 0
    return _row("WARN" if not n else "ok",
                f"public holidays for {year}", n,
                f"{name} is missing — next year's alternate-Saturday calendar "
                f"cannot be generated (OD-71b)" if not n
                else f"{n} holidays recorded")


def _entitlement_rows():
    year = getdate(nowdate()).year
    return year, frappe.db.sql("""
        SELECT e.employee_name,
               SUM(la.leave_type = 'Annual') AS annual,
               SUM(la.leave_type = 'MC')     AS mc
          FROM `tabLeave Allocation` la
          JOIN `tabEmployee` e ON e.name = la.employee
         WHERE la.docstatus = 1 AND YEAR(la.from_date) = %s
      GROUP BY la.employee, e.employee_name
        HAVING annual = 0 OR mc = 0""", year, as_dict=True)


def check_missing_mc():
    """🔴 BLOCKING. Medical leave is statutory — somebody holding annual leave
    and no MC cannot file a sick day at all, and it is very unlikely to be
    deliberate."""
    year, rows = _entitlement_rows()
    bad = [r for r in rows if not r.mc]
    return _row("BLOCK" if bad else "ok",
                f"{year}: has leave but NO medical entitlement", len(bad),
                ", ".join(r.employee_name for r in bad[:5])
                or "everyone allocated has medical leave")


def check_missing_annual():
    """⚠️ INFORMATIONAL, not blocking, and the distinction matters.

    Eight employees hold MC and no Annual — and for a new joiner that may be
    exactly right: CAF appears not to grant annual leave in the first months
    (HR Q3). Reporting it as a BLOCK alongside the genuine MC gap would bury the
    two people who really are stuck, which is how a readiness list stops being
    read (`C75-QUIET`, same reasoning).
    """
    year, rows = _entitlement_rows()
    bad = [r for r in rows if not r.annual]
    return _row("note", f"{year}: medical leave but no annual (may be correct)",
                len(bad), ", ".join(r.employee_name for r in bad[:4])
                or "everyone allocated has annual leave")


# The two org roots. `reports_to` and `leave_approver` are blank on these by
# definition — FBR50: `HR-EMP-00001` Ow Yong Mian Fatt and `HR-EMP-00002` Yow Kwee
# Chin are the only employees with nobody above them. Named rather than tolerated
# by count, the same discipline as EXEMPT above (OD-24 / RDY-EXEMPT).
ORG_ROOTS = {"HR-EMP-00001", "HR-EMP-00002"}


def check_org_chart():
    """🔴 Every active employee must name BOTH a manager and a leave approver.

    MG, 2026-09-01: *"moving forward in this test server, we will use both emp
    reports_to and leave_approver — these 2 fields for all emp should already be
    filled up."* They are what CAF reads to decide who opens an appraisal (OD-76)
    and who may act on a leave application (FBR56).

    A blank is silent in both directions: an employee with no `leave_approver`
    files an application **nobody can act on**, and one with no `reports_to` has no
    appraisal opened for them at all. Neither produces an error anywhere.

    ✅ Measured 2026-09-01 on this site: 0 blanks outside the two roots.
    ⚠️ Production is the copy that still needs this — GO_LIVE_TODO T-10.
    """
    bad = [r for r in frappe.get_all(
        "Employee", filters={"status": "Active"},
        fields=["name", "employee_name", "reports_to", "leave_approver"])
        if r.name not in ORG_ROOTS and (not r.reports_to or not r.leave_approver)]
    return _row("BLOCK" if bad else "ok",
                "active employees missing manager or approver", len(bad),
                ", ".join(f"{r.employee_name} ("
                          f"{'no manager' if not r.reports_to else 'no approver'})"
                          for r in bad[:5])
                or f"all filled; only the {len(ORG_ROOTS)} org roots are blank (FBR50)")


def check_approver_matches_manager():
    """A NOTE, not a block — the approver is usually the manager, but need not be.

    Measured 2026-09-01: all 87 active employees who have a manager satisfy
    `leave_approver == reports_to.user_id`, with zero exceptions. That is a strong
    pattern and worth surfacing when it breaks, because a divergence is almost
    always a data-entry slip rather than a decision.

    ⚠️ Deliberately **not** a BLOCK. HR may legitimately route somebody's leave to
    a person other than their line manager — during cover, or where a manager is
    also the subject. Refusing that would encode a convention as a rule, and the
    convention is not what CAF actually reads: `has_permission` reads
    `leave_approver`, nothing else.
    """
    bad = []
    for r in frappe.get_all("Employee", filters={"status": "Active",
                                                 "reports_to": ("!=", "")},
                            fields=["name", "employee_name", "reports_to",
                                    "leave_approver"]):
        mgr_login = frappe.db.get_value("Employee", r.reports_to, "user_id")
        if (r.leave_approver or "") != (mgr_login or ""):
            bad.append(f"{r.employee_name} → {r.leave_approver or '—'} "
                       f"(manager logs in as {mgr_login or '—'})")
    return _row("note" if bad else "ok",
                "leave approver is not the line manager", len(bad),
                ", ".join(bad[:4])
                or "every approver is the employee's own manager")


CHECKS = [check_naming, check_default_shift, check_holiday_list, check_shift_lists,
          check_alt_pairs, check_manager_logins, check_org_chart,
          check_approver_matches_manager, check_leave_period,
          check_next_year_holidays, check_missing_mc, check_missing_annual]


def audit():
    """Read-only. Returns the rows so a test can assert on them."""
    out = [c() for c in CHECKS]
    blocking = [r for r in out if r["severity"] == "BLOCK"]
    warn = [r for r in out if r["severity"] == "WARN"]

    print(f"{'':2s} {'check':44s} {'count':>6s}  detail")
    for r in out:
        mark = {"BLOCK": "🔴", "WARN": "⚠️ ", "note": "· ", "ok": "  "}[r["severity"]]
        print(f"{mark} {r['check']:44s} {r['count']:>6}  {r['detail'][:70]}")

    print(f"\n{len(blocking)} blocking, {len(warn)} warning, "
          f"{len(out) - len(blocking) - len(warn)} clear.")
    if blocking:
        print("A blocking row does not mean anything is broken TODAY — it means "
              "the first person to use that feature is stopped, with no warning "
              "anywhere until they try.")
    return {"rows": out, "blocking": blocking, "warn": warn}
