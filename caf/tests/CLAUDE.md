# Python test suites

Run with `bench execute`, not `pytest`:

```bash
bench --site development.localhost execute caf.tests.<package>.<module>.run
```

Every suite exposes `run()` and prints one line per assertion — an id, PASS/FAIL,
and **a sentence explaining what the assertion protects and why it exists**. That
sentence is the point: a failing test should teach the reader what broke, not just
that something did.

## Layout

| package | covers |
|---|---|
| `fingerlog/` | the bulk — shifts, punches, work hours, OT, leave, roster, appraisal cascade |
| `ingress/` | the importer, the manifest, the catch-up, unmapped employees |
| `workflow_gaps/` | EPF ownership, appraisal cancel/amend, fixture integrity |
| **`platform/`** | ⭐ cross-cutting — **`test_role_matrix`** (every surface × every role, both directions, T-21) and **`test_data_scripts`** (every production script's report mode + `verify()`) |
| `appraisal/` | 🔴 **PowerShell, not Python** — the per-role REST suite. See its own `CLAUDE.md` |

## Conventions that are not optional

- **Self-cleaning.** Build fixtures, remove them in `finally`. Artifacts are
  removed **first** as well, so a suite is re-runnable after a crash.
  ⚠️ `_Batch.__init__` in `caf.caf.ingress.sync` **inserts** — it is not an
  in-memory builder, and a suite that forgets leaves a stray Import Batch.
- **June, not July.** `2026-07-01..31` holds imported Finger Logs; a fixture on
  those dates has deleted real rows before. June is clear.
  ⚠️ Also avoid `2026-06-17` (Awal Muharram) — stock refuses a leave application
  whose every day is a holiday, and the refusal arrives long before any CAF logic.
- **Assert the FACTS a message carries, never its wording.** `test_ot_messages`
  checks that the name, date, hours and blocking document are present, so the
  wording can be improved freely but not impoverished.
- **Skip, never fail, when the Ingress PC is unreachable** — it is a desktop that
  sleeps, so that is a normal operational state. Skips are counted and printed
  separately; they are **not** passes. `test_ingress_import` and `test_catchup`
  both have the guard.
- **A suite must not change the site.** `test_alt_saturday` used to regenerate
  Holiday Lists and repoint every Shift Type — and it repaired the condition
  `ALT-ANCHOR` asserts, so a first run could fail and the next pass with no code
  change. It now snapshots and restores. **A gate that cannot stay red is worse
  than one that is red.**

## Gotchas

- `bench execute` masks the real exception behind its own fake
  `NameError: name 'caf' is not defined` (quirks #18). Read **above** the final
  traceback.
- `--kwargs "{'apply':1}"` is unusable from PowerShell directly — wrap it:
  `wsl docker exec frappe bash -lc '… --kwargs "{''apply'':1}"'`.
- An assertion can pass **by luck**. `leave_naming_fix.verify` once checked
  "does the year appear in the name" and passed on two of three because
  `HR-LPR-2025-00001` contains "2025". Assert the exact expected value.
- Running as `Administrator` proves nothing about permissions (quirks #33/#43).
  Use `frappe.set_user`, or the PowerShell suite for anything reachable by URL.
  ⚠️ `frappe.only_for` **returns early for Administrator**, so an
  Administrator-run permission suite reports a clean matrix against a completely
  open system.
- 🔴 **A permission probe must knock on the door the DESK uses.**
  `frappe.get_doc()` runs **no permission check at all** — the first draft of
  `test_role_matrix` used it and duly reported that every employee could read the
  Ingress database password. They cannot. Use `frappe.client.get` /
  `frappe.has_permission` / `doc.check_permission()`; for a Script Report use
  `frappe.desk.query_report.run`, never `execute()` (quirks #58).
- **"It writes nothing" needs `CHECKSUM TABLE`, not row counts.** Several data
  scripts use `db.set_value(update_modified=False)` (OD-26), which moves neither
  `COUNT(*)` nor `MAX(modified)`. `test_data_scripts._fingerprint()` is the shape.

## Current gate

```
ot_messages 8/8 · shift_family 7/7 · alt_pair_guard 8/8 · required_punches 7/7
chunk3 21/21 · chunk4 10/10 · chunk5 23/23 · chunk7_swap 12/12
alt_saturday 16/16 · monthly_roster 11/11 · readiness 6/6 · chunk_r 12/12
manifest_search 8/8 · unmapped_employee 6/6 · fixture_integrity 18/18
finger_log_title 8/8 · leave_service_bar 9/9 · leave_allocation 18/18
data_scripts 6/6 (+2 skipped)
ingress_import 23/23 · catchup 8/8      (both need the Ingress PC awake)
chunk7_roster 22/23                      ← C75-LIVE, parked by MG
role_matrix 16/18                        ← 🔴 RED ON PURPOSE: both failures are
                                            real findings, GO_LIVE_TODO T-22
                                            (an employee can approve their own
                                            OT) and T-23 (Finger Log DocPerm
                                            drift). Do NOT edit them green
```
