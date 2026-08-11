"""Chunk 7.4 — the Who Is Off board, proven AS A ROLE. OD-30 / OD-12.

    bench --site <site> execute caf.tests.fingerlog.test_chunk7_whoisoff.run

🔴 THE ONE ASSERTION THAT MATTERS IS C74-MC
-------------------------------------------
MG made this board visible to **every employee**, and `leave_type` names the
illness — it discloses **MC**. MG's decision, 2026-08-11: it is HR Manager only.

A **Script Report runs its own SQL**, so `permission_query_conditions` never fires
and the `Report` role list decides only who may OPEN the board. `execute()` is the
entire enforcement, exactly as in 7.1 — and here it is enforced by never putting
the value on the row at all. C74-MC therefore searches the **whole payload** for
each leave type HR can see, rather than checking that a key is missing: a value
that survives in a row the front end does not render is still disclosed to anyone
who calls the report over REST (PROTOCOL §C3, §C4).

The mirror image of 7.1: there, everyone saw one column and the question was
*whose rows*; here everyone sees every row and the question is *which column*.

🔴 AND C74-WF, WHICH PROVES THE STAGE COLUMN IS NOT JUST `status` RENAMED
-------------------------------------------------------------------------
No Workflow is attached to Leave Application yet (Chunk 6 / OD-27), so
`workflow_state` is empty on all 775 rows and `stage` currently falls back to
`status`. Without C74-WF every other stage assertion would pass on a column that
had quietly become a permanent alias for `status` — and OD-30 exists precisely
because `status` cannot tell the four pending states apart. C74-WF sets a real
workflow state on **this suite's own fixture** and asserts the column yields to it.

RE-RUNNABLE: artifacts are removed FIRST, not last, and the purge is scoped by
employee AND June date AND this suite's marker (PROTOCOL §F4).
"""

import frappe

from caf.caf.report.who_is_off import who_is_off

EMP_USER = "seriramulu@caffood.com"          # HR-EMP-00075, role Employee
HRM = "hr.manager.test@caffood.com"          # role HR Manager, and NO Employee record

# 🔴 JUNE. The importer owns July; a July fixture deletes real data (§F4d).
# ⚠️ And the dates were CHECKED against this employee's own Holiday List before
# being written here: 2026-06-17 is AWAL MUHARRAM and cost Chunk R six assertions
# at once (§F1c). HR-EMP-00001 is on `CAF Mon-Fri 2026`, and 06-08..06-12 is clear.
FIX_EMP = "HR-EMP-00001"
D_FROM, D_TO = "2026-06-08", "2026-06-12"    # Mon–Fri, no holiday, no existing leave
C_FROM, C_TO = "2026-06-22", "2026-06-23"    # the cancelled row
MARKER = "CHUNK 7.4 WHO IS OFF FIXTURE"
LWP = "Leave Without Pay"                    # is_lwp — skips the balance check

WIN = {"from_date": "2026-06-01", "to_date": "2026-06-30"}
NARROW = {"from_date": "2026-06-10", "to_date": "2026-06-11"}   # inside the span
WF_STATE = "Pending HR Manager Approval"     # spec §4's chain: supervisor -> HR -> director

RESULTS = []


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))


def as_user(user, fn, *a):
    """PROTOCOL §C1b — always restore in a `finally`. A suite that exits still
    switched leaves every later suite in the process running as somebody else."""
    frappe.set_user(user)
    try:
        return fn(*a)
    except Exception as e:
        return ("ERROR", type(e).__name__, str(e))
    finally:
        frappe.set_user("Administrator")


def cleanup():
    """Scoped three ways: this employee, June only, and this suite's marker."""
    for r in frappe.get_all("Leave Application",
                            filters={"employee": FIX_EMP,
                                     "from_date": ("between", ["2026-06-01",
                                                               "2026-06-30"]),
                                     "description": ("like", f"%{MARKER}%")},
                            fields=["name", "docstatus"]):
        doc = frappe.get_doc("Leave Application", r.name)
        doc.flags.ignore_permissions = True
        doc.flags.ignore_links = True
        if doc.docstatus == 1:
            doc.cancel()
        frappe.delete_doc("Leave Application", r.name, ignore_permissions=True,
                          force=True)
    frappe.db.commit()


def file_draft(lo, hi):
    """A DRAFT, deliberately. Most of this board is drafts — 12 of the 17 rows in
    the live window — and a draft fires no CAF hook: `check_leave_window` and the
    appraisal refresh are both on `before_submit` / `on_submit`."""
    la = frappe.new_doc("Leave Application")
    la.employee = FIX_EMP
    la.leave_type = LWP
    la.from_date, la.to_date = lo, hi
    la.status = "Open"
    la.description = MARKER
    la.company = frappe.db.get_value("Employee", FIX_EMP, "company")
    la.flags.ignore_permissions = True
    la.insert()
    return la


def names(cols):
    return [c["fieldname"] for c in (cols or [])]


def run():
    cleanup()
    try:
        span = file_draft(D_FROM, D_TO)
        canc = file_draft(C_FROM, C_TO)
        canc.db_set("status", "Cancelled", update_modified=False)
        frappe.db.commit()

        # ------------------------------------------------------------- C74-FIX
        clash = frappe.db.count("Leave Application",
                                {"employee": FIX_EMP,
                                 "from_date": ("between", ["2026-06-01", "2026-06-30"]),
                                 "description": ("not like", f"%{MARKER}%")})
        june_total = frappe.db.count("Leave Application",
                                     {"from_date": ("<=", "2026-06-30"),
                                      "to_date": (">=", "2026-06-01")})
        check("C74-FIX", clash == 0 and june_total > 2,
              f"fixture is clean and NOT alone: {FIX_EMP} has {clash} unmarked June "
              f"leave(s) (must be 0 — the dates were picked because this employee had "
              f"none), and June holds {june_total} overlapping rows in total, so every "
              f"assertion below runs against real data as well as the fixture")

        admin_cols, admin_data = who_is_off.execute(WIN)

        # ------------------------------------------------------------- C74-ALL
        # The board is deliberately NOT scoped per employee — unlike 7.1. Prove an
        # Employee-role caller really does see other people, or the leave_type
        # assertion below would be passing on an empty result.
        res = as_user(EMP_USER, who_is_off.execute, WIN)
        cols, data = res if isinstance(res, tuple) and len(res) == 2 else (None, None)
        who = {r["employee_name"] for r in (data or [])}
        own = frappe.db.get_value("Employee", {"user_id": EMP_USER}, "employee_name")
        check("C74-ALL", data is not None and len(data) == len(admin_data)
              and len(who) > 1 and any(w != own for w in who),
              f"an Employee-role caller sees the WHOLE board: {len(data) if data is not None else 'ERROR'} "
              f"rows across {len(who)} people (Administrator sees {len(admin_data)}), "
              f"including people who are not {own!r} — MG made this board all-employee")

        # ------------------------------------------------------------- C74-MC 🔴
        hres = as_user(HRM, who_is_off.execute, WIN)
        hcols, hdata = hres if isinstance(hres, tuple) and len(hres) == 2 else (None, None)
        hr_types = {r.get("leave_type") for r in (hdata or []) if r.get("leave_type")}
        # Exact VALUE match across every cell, not a substring sweep: a leave type
        # like "MC" would collide with ordinary text and make this pass or fail for
        # the wrong reason.
        leaked = [(t, r) for r in (data or []) for v in r.values()
                  for t in hr_types if v == t]
        check("C74-MC", "leave_type" not in names(cols) and not leaked
              and MARKER not in str(data) and LWP not in str(data),
              f"🔴 leave_type is ABSENT FROM THE PAYLOAD, not merely from the column "
              f"list: HR can see {sorted(hr_types)}, and none of those {len(hr_types)} "
              f"values appears in any of the Employee caller's {len(data or [])} rows "
              f"({len(leaked)} leaks). It discloses MC — health information (MG, OD-30)")

        # -------------------------------------------------------------- C74-HR
        check("C74-HR", hdata is not None and "leave_type" in names(hcols)
              and hr_types and len(hdata) == len(admin_data),
              f"HR Manager gets the column and real values: {sorted(hr_types)} across "
              f"{len(hdata) if hdata is not None else 'ERROR'} rows "
              f"⚠️ and note {HRM} has NO Employee record — the split is by ROLE, so a "
              f"user with no employee row still gets the HR view")

        # ----------------------------------------------------------- C74-STAGE
        blank = [r for r in (data or []) if not r.get("stage")]
        fallback = [r for r in (data or []) if r.get("stage_from_status")]
        check("C74-STAGE", data and not blank and len(fallback) == len(data),
              f"every row carries a Stage: {len(blank)} blank of {len(data or [])}. "
              f"All {len(fallback)} are flagged as coming FROM STATUS — correct today, "
              f"because no Workflow is attached to Leave Application yet (Chunk 6). "
              f"Without the fallback this column would be empty on every row, which is "
              f"the failure 7.1 hit with `status`")

        # -------------------------------------------------------- C74-WF 🔴
        # The assertion that stops `stage` silently becoming an alias for `status`.
        span.db_set("workflow_state", WF_STATE, update_modified=False)
        frappe.db.commit()
        wres = as_user(EMP_USER, who_is_off.execute, WIN)
        _, wdata = wres if isinstance(wres, tuple) and len(wres) == 2 else (None, None)
        row = next((r for r in (wdata or [])
                    if str(r["from_date"]) == D_FROM and r["total_leave_days"] == 5.0), None)
        check("C74-WF", row and row["stage"] == WF_STATE
              and not row["stage_from_status"] and row["stage"] != "Open",
              f"the moment a workflow state EXISTS the column yields to it: "
              f"{row['stage'] if row else 'ROW NOT FOUND'!r} (not 'Open'), and the "
              f"from-status flag drops to {row['stage_from_status'] if row else '-'}. "
              f"This is what OD-30 asked for — 'Open' covers all four pending states "
              f"at once and cannot say where an application is stuck")

        # ------------------------------------------------------- C74-OVERLAP 🔴
        # Overlap, not containment. Someone whose leave STARTED before the window
        # and has not ended is exactly who a who-is-off board exists to show — two
        # live 52-day spans on this site would vanish under a containment test.
        nres = as_user(EMP_USER, who_is_off.execute, NARROW)
        _, ndata = nres if isinstance(nres, tuple) and len(nres) == 2 else (None, None)
        found = [r for r in (ndata or []) if str(r["from_date"]) == D_FROM]
        check("C74-OVERLAP", found,
              f"a leave running {D_FROM}..{D_TO} IS returned by a "
              f"{NARROW['from_date']}..{NARROW['to_date']} window it merely overlaps "
              f"({len(found)} match of {len(ndata or [])} rows) — it started before the "
              f"window and the person is still off")

        # ------------------------------------------------------- C74-CANCEL 🔴
        # ⚠️ Cannot be folded into the docstatus test: 57 rows on this site are
        # `status = Cancelled` while still sitting at `docstatus = 0`.
        #
        # ⚠️ SCOPED TO THE FIXTURE EMPLOYEE, and that is not fussiness. The first
        # version matched on `from_date` alone and went red against an imported
        # APPROVED leave that another employee happened to file on the same date
        # (HR-EMP-00013, 2026-06-22). The exclusion was working perfectly. That is
        # §F1 in the failing direction — a red assertion is as capable of being
        # about the wrong thing as a green one.
        fix_name = frappe.db.get_value("Employee", FIX_EMP, "employee_name")
        mine = [r for r in (data or []) if r["employee_name"] == fix_name]
        cancelled = [r for r in mine if str(r["from_date"]) == C_FROM]
        kept = [r for r in mine if str(r["from_date"]) == D_FROM]
        check("C74-CANCEL", not cancelled and kept and canc.docstatus == 0,
              f"of {fix_name}'s two fixtures the board shows {len(kept)} (the live one) "
              f"and hides {len(cancelled)} (the Cancelled one) — whose docstatus is "
              f"still {canc.docstatus}. Both exist, same employee, so the live row is "
              f"the positive control: 57 rows on this site are Cancelled-but-draft and "
              f"`docstatus < 2` alone would show them as people being off")

        # -------------------------------------------------------- C74-DRAFT 🔴
        # The mirror of 7.1's C7-DRAFT, and for the opposite reason: here the drafts
        # are the PENDING applications, which is the whole second question the board
        # answers. Filtering to docstatus = 1 would show the answers and hide the
        # questions.
        drafts = frappe.db.count("Leave Application",
                                 {"docstatus": 0, "status": "Open",
                                  "from_date": ("<=", "2026-06-30"),
                                  "to_date": (">=", "2026-06-01")})
        subs = frappe.db.count("Leave Application",
                               {"docstatus": 1,
                                "from_date": ("<=", "2026-06-30"),
                                "to_date": (">=", "2026-06-01")})
        check("C74-DRAFT", drafts > 0 and len(data or []) > subs,
              f"drafts are INCLUDED: {drafts} pending June application(s), and the board "
              f"returns {len(data or [])} rows against {subs} submitted — a pending "
              f"application is the reason the Stage column exists")

        # --------------------------------------------------------- C74-PENDING
        pres = as_user(EMP_USER, who_is_off.execute, dict(WIN, pending_only=1))
        _, pdata = pres if isinstance(pres, tuple) and len(pres) == 2 else (None, None)
        check("C74-PENDING", pdata is not None and 0 < len(pdata) < len(data)
              and all(r["stage"] in ("Open", WF_STATE) for r in pdata),
              f"'Pending only' narrows {len(data)} -> {len(pdata) if pdata is not None else 'ERROR'} "
              f"rows and every one is still undecided: "
              f"{sorted({r['stage'] for r in (pdata or [])})}")

        # ------------------------------------------------------------ C74-DEPT
        dept = frappe.db.get_value("Employee", FIX_EMP, "department")
        dres = as_user(EMP_USER, who_is_off.execute, dict(WIN, department=dept))
        _, ddata = dres if isinstance(dres, tuple) and len(dres) == 2 else (None, None)
        check("C74-DEPT", ddata is not None and 0 < len(ddata) <= len(data)
              and all(r["department"] == dept for r in ddata),
              f"the Department filter is honoured server-side: {dept} -> "
              f"{len(ddata) if ddata is not None else 'ERROR'} of {len(data)} rows, "
              f"all in that department")

        # ------------------------------------------------------------ C74-COLS
        check("C74-COLS", names(cols) == ["employee_name", "department", "from_date",
                                          "to_date", "total_leave_days", "stage",
                                          "leave_approver", "posting_date"]
              and names(hcols) == names(cols) + ["leave_type"],
              f"columns are MG's proposed list in MG's order: {names(cols)} "
              f"(+leave_type for HR). `leave_approver` is the email because "
              f"`leave_approver_name` is populated on 0 of 775 rows — a second blank "
              f"column is what 7.1 already paid for")
    finally:
        # Always: a suite that dies mid-way must not leave a fixture behind, and
        # must not leave the session switched.
        frappe.set_user("Administrator")
        cleanup()
        frappe.db.commit()

    print("\n=== Chunk 7.4 — Who Is Off, as a role ===")
    for tid, ok, detail in RESULTS:
        print(f"{tid:13s} {'PASS' if ok else 'FAIL'}  {detail}")
    failed = [t for t, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else ""))
    print(f"   session restored to: {frappe.session.user}")
    return not failed
