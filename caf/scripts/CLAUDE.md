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
| `caf_permission_matrix` | EPF `if_owner` · ESS write · `track_changes` |
| `hr_manager_user_permissions` | removes self-scoping Employee User Permissions |
| `leave_approver_gap` | fills blank `leave_approver`, grants the role |
| `shift_punch_rule_rollout` | the 4 punch-rule shifts + 8 employee moves · `refresh_held_drafts` |
| `no_clocking_flag` | `caf_no_clocking` for people who genuinely never clock |
| `join_date_from_ingress` | the 9 disputed join dates |
| `leave_naming_fix` | Leave Period named by the year it covers · Leave Policy shows its title |
| `backfill_manifest_employee_name` | makes historical manifests searchable by name |
| `finger_log_title_backfill` | `date · device · name` on 3,167 logs, so the desk stops showing a name that looks like a device id and is not (FBR67) |
| `alt_saturday_setup` · `holiday_lists` | alternating-Saturday shifts and calendars |
| `leave_policy_seed` · `leave_formula` | the 3 policies and the under-2-year curve |
| `leave_group_review` | 🟡 read-only — builds the HR confirmation page |
| `readiness_audit` | ⭐ **13 checks; a clean run is the go-live gate** |

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
