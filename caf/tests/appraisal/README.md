# CAF Appraisal — test suite

Executable form of `CAF_appraisal_test_plan.md`. Every probe runs as a **real
role**, never as Administrator.

## Why per-role tokens

`Administrator` bypasses every permission check in Frappe — `has_permission`
hooks, `permission_query_conditions`, role gates and `permlevel` filtering. A
permission test run as Administrator passes **identically** against a correct
model and a completely broken one. It proves nothing.

So each script carries a token per role and compares what each one can actually
see and do.

## Setup

```powershell
cd caf/tests/appraisal
Copy-Item credentials.example.ps1 credentials.ps1
# fill in credentials.ps1 with the real tokens - it is gitignored
```

Dev-site values live in `test_fixture_credentials.md`, outside this repo.

## Running

```powershell
.\run_all.ps1              # everything
.\test_2_1_to_2_4.ps1      # supervisor flow, HR flow, rejection loop, subtree
.\test_2_5_to_2_8.ps1      # score toggle, BR6, edge cases, reports_to rules
.\probe_2_10a.ps1          # HR Settings permlevel
.\probe_2_10b.ps1          # Finger Log restriction
.\probe_2_10bc.ps1         # EPF permlevel, KRA permissions, workflow present
.\probe_2_10e.ps1          # cross-checks: did anything leak?
```

The suites are **re-runnable** — each cleans up its own artifacts first. That
was not originally true, and a run once failed on the *previous* run's leftover
draft rather than on anything real.

## Coverage against the test plan

| Block | Covered |
|---|---|
| §2.1–2.4 supervisor / HR / rejection / subtree | ✅ `test_2_1_to_2_4.ps1` |
| §2.5–2.8 score toggle, BR6, edges, reports_to | ✅ `test_2_5_to_2_8.ps1` |
| §2.9 model shipped | ✅ `probe_2_10bc.ps1` |
| §2.10a–c permlevel, Finger Log, KRA | ✅ the `probe_2_10*` scripts |
| **§2.10d** | **void** — tests cancel/amend and the `Appraisal Supervisor` role. D54 replaced cancel+amend with a backward workflow transition; D55 deleted the role. T-J20's expectation is *inverted* by D55 (the Employee role keeps `create`). **T-I3 replaces it.** |
| §2.10e cross-checks | ✅ `probe_2_10e.ps1` |
| §3 desk-UI sign-off | **browser, not scripted** — see below |

## What is deliberately not scripted

**§3 is a browser checklist.** It exists to prove the JS *executed*, not merely
that it was served — which no API call can establish. Run it by hand in the desk
UI, or drive the in-app browser per `frappe-dev-protocol` §6.

Also not scripted, and worth knowing:

- **Server-side data checks** live in `caf/scripts/appraisal_data_quality.py`,
  not here. Run that too.
- **`T-E3`** (stock scoring produces a non-zero total) cannot pass in CAF's
  configuration: stock `set_goal_score()` reads the **Goal** doctype, which CAF
  does not use, so the score is structurally 0. The toggle's real behaviour is
  proven by `T-E2` (guard fires when on) and `T-E1b` (same data passes when off).
- **`T-G2`** (employee with no `default_shift`) has no natural fixture — the only
  employees without one are excluded from appraisal anyway.

## Reading a failure

Not every red line is a product bug. During the build, four "failures" in one
run were all stale test data:

- an email address where `EPF.reviewer` wants an **Employee ID** — the guard was
  working, the fixture was wrong
- a hardcoded appraisal name that no longer existed
- a fixture collision between two scripts using the same employee + cycle

Check the message before the code. A `409` is a duplicate, a `405` usually means
a URL was built from a null, and a `417` is a `ValidationError` carrying a real
explanation.
