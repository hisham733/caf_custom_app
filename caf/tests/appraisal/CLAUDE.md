# PowerShell REST role suite

The **permission** gate. Every probe here runs as a **real role over HTTP**, using
a per-role API token — never as Administrator.

## Why this exists separately from the Python suites

From the suite's own README, and it is the whole point:

> `Administrator` bypasses every permission check in Frappe — `has_permission`
> hooks, `permission_query_conditions`, role gates and `permlevel` filtering. A
> permission test run as Administrator **passes identically against a correct
> model and a completely broken one. It proves nothing.**

The Python suites use `frappe.set_user`, which exercises the permission model but
**not** the HTTP/whitelist layer. Anything that can be reached by URL — a report,
a whitelisted method, a doctype API — belongs here.

## Running

```powershell
cd \\wsl$\Ubuntu-24.04\root\frappe_docker\development\frappe-bench\apps\caf\caf\tests\appraisal
.\probe_2_10b.ps1        # one probe
.\run_all.ps1            # everything — ⚠️ see the blocker below
```

Run from **PowerShell**, not the Bash tool: these are `.ps1`, and the Bash tool
mangles the UNC path.

| file | covers |
|---|---|
| `test_2_1_to_2_4.ps1` | supervisor flow · HR flow · rejection loop · subtree |
| `test_2_5_to_2_8.ps1` | score toggle · BR6 · edge cases · `reports_to` rules |
| `probe_2_10a.ps1` | HR Settings permlevel |
| `probe_2_10b.ps1` | Finger Log restriction (D40) **+ Attendance Follow-Up report roles** |
| `probe_2_10bc.ps1` | EPF permlevel · KRA permissions · workflow present |
| `probe_2_10e.ps1` | cross-checks — did any permission change leak past its scope? |

Role keys in `credentials.ps1` (**gitignored**, values in
`test_fixture_credentials.md`): `HRMgr` `SupA` `EmpB` `SupC` `EmpD` `HRUser`
`Admin`.

## 🔴 `run_all.ps1` cannot currently complete

`test_2_1_to_2_4.ps1` dies on a null index after warning *"3 appraisal(s)
survived the reset"*. **It is not a product fault.**

`_cleanup.ps1`'s shared reset does:

```powershell
GET /api/resource/Appraisal?limit_page_length=0            # EVERY appraisal
GET /api/resource/Employee Performance Feedback?...        # EVERY EPF
```

It assumes it owns every Appraisal on the site. That was true when written and is
not now: three **cancelled** appraisals belonging to real test users survive it —
`HR-APR-2026-00092`, `-00280`, and `-00309`, the last referenced by name in the
appraisal-cancel-state work.

⚠️ **Do not delete them to make the suite green.** Quirks #63 explains why the
reset fails anyway — a delete is blocked by **any** referrer row, cancelled ones
included. **The fix is to scope the reset to its own fixtures.** Tracked as T-21.

Meanwhile the four `probe_2_10*` scripts are independently self-cleaning and can
be run individually.

## Gotchas

- **Test a report through `frappe.desk.query_report.run`**, never by importing its
  module and calling `execute()`. The module call **bypasses the permission gate
  entirely** and passes against a broken model (quirks #58) — the same trap as
  running the test as Administrator.
- **Widening a leak-detector needs a written reason.** `probe_2_10e`'s `$named` and
  `$touched` lists exist to catch a permission change escaping its intended scope.
  When a doctype legitimately joins them, name it *and say why in the file* — both
  current additions (Appraisal via OD-81b, Shift Assignment via R3) do.
- **A failing assertion here is not automatically stale.** Two of the current
  failures are: `T-I2` (the workflow gained a `Cancelled` state on 2026-08-22).
  One is **not** — `T-J25` reports 4 users holding `Employee Self Service` where
  D42/T22 says zero, and that is live drift, not a test to edit away.
- Every script is **re-runnable and order-independent** by design. If one is not,
  that is the bug.
