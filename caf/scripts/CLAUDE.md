# Production data scripts

Everything that must be **done to a site** rather than deployed to it. Deploying
the app gives production the *shape*; these give it the *content*.

```bash
bench --site <site> execute caf.scripts.<name>.run                        # REPORT
bench --site <site> execute caf.scripts.<name>.run --kwargs "{'apply':1}" # WRITE
bench --site <site> execute caf.scripts.<name>.verify                     # PROVE
```

## The contract every script here keeps

- **Report before it writes.** `run()` with no argument changes nothing and prints
  what it would do. `apply=1` is a separate, deliberate act.
- **Idempotent and re-runnable.** Each checks current state and no-ops where it is
  already correct — *"already on X"*, *"already correct"*. They are meant to run
  **at least twice**: once on prod-test, once on production (T-18).
- **Self-documenting about WHY.** The docstring carries the measurement that
  produced the decision. Deleting the script deletes the reason production holds
  the values it holds — so they are **kept, never deleted after use**.
- **`verify()` is the evidence.** It asserts the end state in *both* directions —
  what must be true and what must no longer be.
- **A comment is the audit trail.** `frappe.db.set_value` writes **no Version**
  (OD-26), so any script changing a person's record adds a `Comment` naming the
  old value and the reason. A shift, a join date or an approver decides somebody's
  pay; a silent change is the hole OD-26 exists to close.

## What is here

| script | does |
|---|---|
| `retire_hr_user_role` | HR User → 3 holders (was 32) |
| `retire_ess_role` | `Employee Self Service` → **0 holders** (was 4) — CAF does not use self-service attendance (OD-84) |
| `caf_permission_matrix` | EPF `if_owner` · ESS write · `track_changes` |
| `hr_manager_user_permissions` | removes self-scoping Employee User Permissions |
| `leave_approver_gap` | fills blank `leave_approver`, grants the role |
| `shift_punch_rule_rollout` | the 4 punch-rule shifts + 8 employee moves · `refresh_held_drafts` |
| `no_clocking_flag` | `caf_no_clocking` for people who genuinely never clock |
| `join_date_from_ingress` | the 9 disputed join dates |
| `leave_naming_fix` | Leave Period named by the year it covers · Leave Policy shows its title |
| `backfill_manifest_employee_name` | makes historical manifests searchable by name |
| `alt_saturday_setup` · `holiday_lists` | alternating-Saturday shifts and calendars |
| `leave_policy_seed` · `leave_formula` | the 3 policies and the under-2-year curve |
| `leave_group_review` | 🟡 read-only — builds the HR confirmation page |
| `join_date_signoff_html` | 🟡 read-only — the joining-date sign-off page, all 89 against ERPNext · Ingress `IssueDate` · the machine's first raw tap (T-28) |
| `leave_workflow` | 🔴 the **`CAF Leave Approval`** workflow — 9 states. **NOT in fixtures**, so this script is the only route to production (T-17 item 16) |
| `leave_type_hygiene` | stock Leave Types that contradict CAF's rules — `Casual Leave.is_carry_forward` 1 → 0 (FBR62a) |
| `join_date_signoff_apply` | HR's four signed-off joining dates (FBR74). **Refuses any row whose current value has drifted** from what she signed |
| `leave_entitlement_signoff_html` | 🟡 read-only — the entitlement page: 3 bands, 4 worked archetypes across 3 cycles each, and the rows that disagree with the rule |
| `shift_signoff_html` | 🟡 read-only — Shift Type rules + who is on each (T-28 items 4+5) |
| `restday_lunch_html` | 🟡 read-only — OD-94/FBR91, the rest-day lunch question with what each option would have cost |
| `shift_reassign` | ⭐ **the template for every production data script**: resolves the employee by `attendance_device_id` (T-32) and the shift by `caf_shift_code` (OD-96), and refuses unless the name agrees too |
| `early_start_setting` | `HR Settings.caf_early_start_minutes` (default 60) + `distribution()`, which prints how many days each threshold would flag |
| `stray_attendance_cleanup` | cancels Attendance that **neither** of FBR69's two sources produced — no Finger Log, no Leave Application. Targets are **named explicitly**, never discovered by pattern: a script that decides for itself which of a director's attendance to cancel is not one anybody should run twice. ⚠️ Cancel, not delete — a cancelled row keeps its number and owner, so the evidence survives |
| `shift_holiday_migration` | 🆕 **T-34 rows 4+8 — the migration itself.** Carries the 18 Shift Types and the gazette dates to another site, regenerates the calendars, and repoints every employee. ⭐ **The only script here that reads a PAYLOAD FILE** (`data/shift_holiday_payload.json`, committed): `export` runs on the authority site, everything else on the target. ⚠️ An existing shift is **reported, not overwritten** (OD-88) unless `overwrite=1`. ⚠️ The calendars are **regenerated, not copied** — a Holiday List is 90% derived, so only ~19 gazette dates a year travel and `caf.caf.holiday_lists` builds the rest |
| `readiness_audit` | ⭐ **15 checks; a clean run is the go-live gate** |

🔴 **Identify people by `attendance_device_id`, never by `HR-EMP-xxxxx`** (T-32).
The id is a per-site counter, so the same value is a **different person** on
production. Identify shifts by **`caf_shift_code`**, never by name (OD-96) —
`shift_resolution.by_code()` resolves it and throws on an unknown code.

## Gotchas

- **A Custom Field must be exported in the same chunk** (quirks #44). An
  un-exported field is invisible to git and never reaches production — measured:
  `caf_required_punches` and `caf_shift_family` shipped, were tested 7/7, moved 8
  employees, and existed **only in this site's database** until caught.
- **`frappe.rename_doc` (the top-level wrapper) does not accept
  `ignore_permissions`** — only `frappe.model.rename_doc.rename_doc` does. The
  `TypeError` arrives masked behind `bench execute`'s fake `NameError`.
- **Refuse when the ground has moved.** `shift_punch_rule_rollout` stops if an
  employee is not on the shift its evidence describes, rather than carrying them
  along. A script that adapts silently is worse than one that stops.
- 🔴 **Report mode cannot catch a bug on the CREATE path**, because report mode
  never inserts anything. `shift_holiday_migration` looked clean — 0 pending,
  9/9 verify — while it could not build a single Shift Type: the export
  stringified every value, so stock `Shift Type.validate()` did
  `round(...) + "60"` and threw inside `validate_circular_shift`. ⭐ It was found
  by **deleting the one Shift Type nothing references (`7am Schedule` — 0
  employees, 0 Attendance, 0 Finger Log) and making the script rebuild it**,
  then comparing all 35 fields. If a script's job is to CREATE something, prove
  it by destroying a disposable one and watching it come back.
- ⚠️ **`bench execute` masks the real exception** as `NameError: name 'caf' is
  not defined`. Wrap the call in `try/except` and print `traceback.format_exc()`
  **to stdout** — `traceback.print_exc()` writes to stderr, which does not
  interleave back through `docker exec` and returns a blank block.
- ⚠️ **`holiday_lists.regenerate()` cannot be asked for a year EARLIER than an
  alternating shift's `caf_sat_anchor_date`.** `alt_saturday_rest_days()` walks
  fortnightly forward from the anchor and refuses to walk backwards — *"The
  anchor 2026-04-11 is after 2025; nothing to walk"*. The refusal is correct
  (a guessed Saturday inverts every later one), so callers must pass only the
  current year and later.
- **The allocation is the exception to idempotence.** A Leave Allocation is a
  submitted document; two runs make two of them. That is why allocation goes
  through the **Leave Control Panel** (which skips anyone already allocated) and
  not through a script here (T-14).
- ⚠️ **Never infer group membership from existing data.** *"Whoever already has an
  allocation is the allocated group"* is circular — it cannot distinguish
  *correctly unallocated* from *not yet reached by HR*, and would freeze today's
  split as if somebody had decided it (FBR60).

- **A backfill must not touch `modified`.** `Finger Log.sort_field` is `modified`,
  so stamping 3,167 rows would flatten the list view's natural order to a single
  instant. `update_modified=False`, always — and `verify()` asserts the spread
  survived, because that is the kind of damage nobody notices for a week.
- **The audit-trail Comment is for values that decide someone's PAY** — a shift, a
  join date, an approver. A derived display label backfilled into a field that had
  no previous value gets none: 3,167 comments would bury the ones that matter.
  Say so in the docstring rather than skipping it silently.

**Every script here is now exercised** by
`caf.tests.platform.test_data_scripts` — report mode + `verify()`, with a
`CHECKSUM TABLE` fingerprint proving report mode writes nothing.

**Production parity: `GO_LIVE_TODO.md` T-17** lists which of these production
needs and how to verify each landed.
