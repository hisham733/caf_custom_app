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
| **`platform/`** | ⭐ cross-cutting — **`test_role_matrix`** (every surface × every role, both directions, T-21) · **`test_data_scripts`** (every production script's report mode + `verify()`, 15 scripts / 11 verifiers) · **`test_disabled_features`** (everything CAF deliberately switched off, asserted still off — read-only, safe on production) |
| 🆕🔴 **`chain/`** | ⭐ **THE JOINS BETWEEN DOCTYPES — T-45.** `bench execute caf.tests.chain.run_all.run` → **5 suites / 32 assertions**. Each was walked in a **real browser** first (`playbooks/L*.md`) and only the rungs with a **business consequence** were codified; a rung that merely documents a screen stayed in the playbook. `dataset.py` seeds (`report/seed/reset/verify` + `arm_gate/disarm_gate`), `login.py` mints a **password-free** one-time desk login, `free_workdays()` finds clear dates by MEASUREMENT — 🔴 **never hard-code one**, June was exhausted by the fifth climb. 🔴 **`test_guard_order` is the crown jewel**: it pins the order HR is told things in (**OT → not-a-full-day → leave clash → roster gate → submits**), which nothing else can see and which manual row **A18** depends on. ⚠️ **`LLS3-T44-LINK-KEPT` and `SWP5-T46-OT-FALLS-SILENTLY` assert behaviour that is WRONG ON PURPOSE** — they record what is true today while MG decides T-44/T-46, so **when either is fixed the assertion goes RED and that red is the signal to retire it. Do not edit the expectation** |
| 🆕 **`fingerlog/test_import_to_appraisal`** | ⭐ **The first CHAIN test — T-44 came out of it.** MG, 2026-09-12: *"after importing these 616, did you complete the full suite test? unblock some… submit a late leave… then an appraisal."* Walks import ➜ submit ➜ late leave (over a DRAFT day **and** over a SUBMITTED one) ➜ appraisal ➜ a leave filed AFTER submission, which must **refresh** it. ⚠️ **It mutates real data and does not put it back** — run `.cleanup` when finished; it removes the whole 10–16 Aug window. ⚠️ **Skips cleanly** when that window has no drafts. 🔴 Three of its six assertions originally PASSED while testing nothing, or reported correct guards (OD-58's held day, the leave-blocks-log rule, stock's duplicate-leave refusal) as product faults — each is written into the file so nobody re-introduces it |
| **`fingerlog/test_retroactive`** | ⭐ **T-39** — what reaches a decision AFTER the data under it changes. Asserts **FBR94** (the owner of a leave application cannot take the FINAL approval; a second HR Manager can) and records that a **late public holiday** and an **amended Attendance** have NO route to a submitted appraisal. 🔴 `allow_self_approval` is enforced in `has_approval_access`, **not** in `get_transitions` — the button is shown and the refusal is on the press |
| `fingerlog/test_midnight_ot` | overtime past midnight, **both sides** — the log and the OT Approval must agree about how long a night was. ⚠️ **0 live rows exercise it**, so it is the only thing keeping that rule honest; do not delete it as dead code |
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
- 🔴 **A suite that builds its own precondition can never discover the
  precondition is missing.** `test_leave_service_bar` is **9/9 green** because it
  creates an Annual allocation first — and **0 of 29 under-a-year employees hold
  one**, so the guard it tests cannot fire on real data at all. Found by
  `chain/test_joiner_bar`, which asks the question in the state the site is
  actually in. **When a suite is green, ask what it had to build to get there.**
- ⚠️ **A refusal formats dates for the READER, not in ISO** (`01-08-2026`). Use
  `chain.dataset.names_date()` — two suites failed the same way in one hour
  against messages that were working perfectly.
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
leave_service_bar 9/9 · leave_allocation 18/18
basic_validation 14/14 · role_matrix 18/18 · data_scripts 6/6 (+2 skipped)
amend 13/13 · chunk3 21/21               ← both now suspend the roster gate
ingress_import 23/23 · catchup 8/8      (both need the Ingress PC awake)
chunk7_roster 22/23                      ← C75-LIVE, parked by MG
fixture_integrity 17/18                  ← I2-GAPS, the HR-PF naming counter;
                                            readiness_audit reports it too
```

⚠️ **The roster gate is LIVE from `2026-09-01`.** Any suite that submits a Finger
Log dated on or after it must wrap the run in
`caf.tests.roster_gate.suspended()` and assert `restored()` — `test_amend` and
`test_chunk3_decisions` do. Restore **by meaning**: a cleared Date on a Single
reads back as `0001-01-01`, so putting the raw value back leaves a gate that
refuses every Finger Log ever recorded.
