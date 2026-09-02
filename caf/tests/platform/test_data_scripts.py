"""The production data scripts keep their own contract. T-21.

    bench --site <site> execute caf.tests.platform.test_data_scripts.run

WHY THIS EXISTS
---------------
`caf/scripts/` is what production gets *done to it* rather than deployed to it —
the punch-rule shifts, the join dates, the leave-period naming, the permission
retirements. Every one of them has a `run()` that is supposed to report and a
`verify()` that is supposed to prove. **None of them was exercised by anything.**

That matters more than an untested feature. These run on production, usually
once, usually under time pressure, and a script that has quietly stopped working
is discovered *there*. Worse: the whole contract rests on `run()` with no
argument writing nothing, and nobody had ever checked that it doesn't.

WHAT IS ASSERTED
----------------
  DS01  every script module carries a docstring that explains WHY it exists —
        the scripts CLAUDE.md calls this the reason production holds the values
        it holds, and deleting it deletes the reason
  DS02  every mutating script exposes both `run` and `verify`
  DS03  🔴 `run()` with no argument WRITES NOTHING — measured with a
        `CHECKSUM TABLE` fingerprint taken before and after, not by reading the
        code and believing it
  DS04  `verify()` runs clean where the script has already been applied
  DS05  the readiness audit — the go-live gate — still executes

HOW "WRITES NOTHING" IS MEASURED
--------------------------------
Row counts and `MAX(modified)` are not enough: `frappe.db.set_value(...,
update_modified=False)` moves neither, and several of these scripts use exactly
that (OD-26). So the fingerprint is `CHECKSUM TABLE`, which reads the rows
themselves. Anything written — a value, a comment, a version — moves it.

Each script is followed by `frappe.db.rollback()`, so even a script that breaks
its contract cannot leave the site changed by having been tested.

⚠️ Scripts that need the Ingress PC are SKIPPED, not failed, when it is asleep —
that is a normal operational state (tests/CLAUDE.md). Skips are counted
separately and are **not** passes.
"""

import importlib
import io
from contextlib import redirect_stdout

import frappe

RESULTS = []
SKIPPED = []

# Tables any of these scripts could plausibly touch. CHECKSUM TABLE full-scans,
# so this is a chosen list rather than every table on the site.
WATCHED = [
    "tabEmployee", "tabShift Type", "tabShift Assignment", "tabFinger Log",
    "tabAttendance", "tabLeave Period", "tabLeave Policy", "tabLeave Allocation",
    "tabLeave Policy Assignment", "tabHas Role", "tabCustom DocPerm",
    "tabUser Permission", "tabComment", "tabProperty Setter", "tabCustom Field",
    "tabIngress Import Batch", "tabIngress Import Row", "tabOT Approval",
]

# (module, entry point, needs the Ingress PC, one line on what it does to prod)
SCRIPTS = [
    ("shift_punch_rule_rollout", "run", False,
     "creates the 4 punch-rule Shift Types and moves 8 people onto them"),
    ("no_clocking_flag", "run", False,
     "flags the people who genuinely never clock, so their days stop being held"),
    ("leave_naming_fix", "run", False,
     "renames Leave Periods to the year they cover — the trap that gave 31 people "
     "a second allocation"),
    ("backfill_manifest_employee_name", "run", False,
     "makes historical import manifests searchable by name"),
    ("finger_log_title_backfill", "run", False,
     "fills the Finger Log title so the desk stops showing a name that looks like "
     "a device id and is not"),
    ("retire_hr_user_role", "run", False,
     "cuts HR User from 32 holders to 3"),
    ("caf_permission_matrix", "run", False,
     "EPF if_owner, ESS write, track_changes"),
    ("hr_manager_user_permissions", "run", False,
     "removes the self-scoping Employee User Permissions that hid people from HR"),
    ("leave_approver_gap", "run", False,
     "fills blank leave_approver and grants the role"),
    ("appraisal_data_quality", "run", False,
     "11 data-quality checks over the appraisal inputs"),
    ("naming_series_audit", "audit", False,
     "proves tabSeries.current is ahead of every minted suffix (quirks #37)"),
    ("join_date_from_ingress", "run", True,
     "the 9 disputed join dates, adjudicated against the machine's first tap"),
]

VERIFIERS = [
    ("shift_punch_rule_rollout", False),
    ("no_clocking_flag", False),
    ("leave_naming_fix", False),
    ("backfill_manifest_employee_name", False),
    ("finger_log_title_backfill", False),
    ("retire_hr_user_role", False),
    ("join_date_from_ingress", True),
]


def check(tid, ok, detail):
    RESULTS.append((tid, bool(ok), detail))
    print(f"{tid:38s} {'PASS' if ok else 'FAIL'}  {detail}")


def skip(tid, why):
    SKIPPED.append(tid)
    print(f"{tid:38s} SKIP  {why}")


def _fingerprint():
    """CHECKSUM TABLE over the watched tables. Moves if ANY row changed."""
    out = {}
    for t in WATCHED:
        try:
            rows = frappe.db.sql(f"CHECKSUM TABLE `{t}`")
            out[t] = rows[0][1] if rows else None
        except Exception:
            out[t] = "absent"
    return out


def _ingress_awake():
    try:
        from caf.caf.ingress import source
        cfg = frappe.get_doc("Ingress Sync Settings")
        if (cfg.source_mode or "").lower().startswith("snapshot"):
            return True
        import socket
        s = socket.create_connection((cfg.host, int(cfg.port or 3306)), timeout=4)
        s.close()
        return True
    except Exception:
        return False


def _call(module, fn):
    """Run one entry point with its output swallowed. Returns (ok, error)."""
    buf = io.StringIO()
    try:
        mod = importlib.import_module(f"caf.scripts.{module}")
        with redirect_stdout(buf):
            frappe.get_attr(f"caf.scripts.{module}.{fn}")()
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


def run():
    frappe.set_user("Administrator")
    awake = _ingress_awake()
    print(f"Ingress PC reachable: {awake}\n")

    # ── DS01 / DS02 — the contract, read off the modules ───────────────────
    no_doc, no_verify = [], []
    for module, entry, _needs, _what in SCRIPTS:
        mod = importlib.import_module(f"caf.scripts.{module}")
        doc = (mod.__doc__ or "").strip()
        if len(doc) < 120:
            no_doc.append(f"{module} ({len(doc)} chars)")
    check("DS01-DOCSTRING-CARRIES-WHY", not no_doc,
          f"every script explains itself in its own docstring "
          f"({len(SCRIPTS) - len(no_doc)}/{len(SCRIPTS)}); thin or missing: "
          f"{no_doc or 'none'}. Deleting that text deletes the reason production "
          f"holds the values it holds")

    for module, needs in VERIFIERS:
        mod = importlib.import_module(f"caf.scripts.{module}")
        if not hasattr(mod, "verify"):
            no_verify.append(module)
    check("DS02-VERIFY-EXISTS", not no_verify,
          f"every mutating script exposes verify() "
          f"({len(VERIFIERS) - len(no_verify)}/{len(VERIFIERS)}); missing: "
          f"{no_verify or 'none'}. verify() is the evidence the run worked — "
          f"without it 'it printed something' is the only proof production gets")

    # ── DS03 — 🔴 report mode writes nothing ───────────────────────────────
    wrote, broke = [], []
    for module, entry, needs, what in SCRIPTS:
        if needs and not awake:
            skip(f"DS03·{module}", f"needs the Ingress PC — {what}")
            continue
        before = _fingerprint()
        ok, err = _call(module, entry)
        after = _fingerprint()
        frappe.db.rollback()
        moved = [t for t in WATCHED if before[t] != after[t]]
        if not ok:
            broke.append(f"{module}.{entry}() → {err}")
        if moved:
            wrote.append(f"{module}.{entry}() moved {moved}")

    check("DS03-REPORT-MODE-IS-READ-ONLY", not wrote,
          f"{len([s for s in SCRIPTS if not (s[2] and not awake)])} scripts ran "
          f"their report mode and changed nothing: {wrote or 'no table moved'}. "
          f"🔴 Measured with CHECKSUM TABLE, not row counts — several of these use "
          f"db.set_value(update_modified=False), which moves neither COUNT nor "
          f"MAX(modified) and would slip past a lazier fingerprint")

    check("DS03b-REPORT-MODE-RUNS", not broke,
          f"every report mode completed without raising: {broke or 'all clean'}. "
          f"A script that has quietly stopped working is otherwise discovered on "
          f"production, in the middle of a go-live")

    # ── DS04 — verify() is honest about the current state ──────────────────
    failed_verify = []
    for module, needs in VERIFIERS:
        if needs and not awake:
            skip(f"DS04·{module}", "needs the Ingress PC")
            continue
        before = _fingerprint()
        ok, err = _call(module, "verify")
        after = _fingerprint()
        frappe.db.rollback()
        if not ok:
            failed_verify.append(f"{module}.verify() → {err}")
        moved = [t for t in WATCHED if before[t] != after[t]]
        if moved:
            failed_verify.append(f"{module}.verify() WROTE to {moved}")
    check("DS04-VERIFY-RUNS-CLEAN", not failed_verify,
          f"every verify() executed and wrote nothing: "
          f"{failed_verify or 'all clean'}. ⚠️ This asserts that verify() RUNS, "
          f"not that it passes — a verify() reporting a genuine gap is doing its "
          f"job, and that is `readiness_audit`'s call to make, not this suite's")

    # ── DS05 — the go-live gate itself ─────────────────────────────────────
    before = _fingerprint()
    ok, err = _call("readiness_audit", "audit")
    after = _fingerprint()
    frappe.db.rollback()
    moved = [t for t in WATCHED if before[t] != after[t]]
    check("DS05-READINESS-AUDIT", ok and not moved,
          f"readiness_audit.audit() executed ({err or 'no error'}) and wrote "
          f"nothing ({moved or 'no table moved'}). It is the single go-live gate "
          f"— 13 checks — so it has to be the one thing that never breaks quietly")

    failed = [t for t, ok, _d in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
          + (f" — FAILED: {failed}" if failed else "")
          + (f"  ·  {len(SKIPPED)} skipped (Ingress PC asleep)" if SKIPPED else ""))
    return not failed
